"""Regression tests for notes -> descriptions and suggested coaching types.

Run:  python test_description_writing.py          (exit 0 = all pass)

WHAT THESE PROTECT
------------------
This is the only path in the tool that talks to anything but the EMR, so the tests that
matter are the ones about what LEAVES and what is allowed back IN.

1. WHAT LEAVES. A job is the note, a head count, and the coaching type. The test asserts
   that no employee name, date, department or shift appears anywhere in the serialised
   payload -- not by inspecting the fields it expects, but by searching the whole JSON
   for every name in the batch and every value that came off the roster. A future field
   added to the job dict fails this test the moment it carries a person.

2. WHAT COMES BACK. A suggested coaching type is a controlled EMR value and is checked
   against COACHING_TYPE_UUIDS before it can reach a row. The 2026-07-16 Copilot removal
   was exactly this failure -- an LLM guessing controlled values -- and the guard is that
   an off-list answer cannot be written, no matter how confident it sounds.

3. ALL OR NOTHING. If any job comes back short, encounters.csv is not written. A note is
   not a description and the sentinel is not a coaching type; neither belongs in a
   medical record because a batch was half successful. Groups that DID resolve keep their
   text, so a second press re-sends only what is still outstanding.

4. THE SENTINEL NEVER VALIDATES. If a suggested type ever survived to the CSV, the batch
   must fail the pre-flight rather than open a browser.

5. THE NAME SCAN. ENCOUNTER_INTAKE.md says Claude cannot check a note for names, because
   by the time it could look it has already read it. The builder can: the roster is in
   memory. The scan is asserted here on a note that names somebody.

FAKE DATA ONLY -- _demo_people() / _demo_library(), and the window is withdrawn.
NOTHING HERE CALLS CLAUDE: _run_with_progress is replaced with a canned reply, so a run
of this file sends nothing and costs nothing.
NEEDS A DESKTOP SESSION: it builds a real Tk window.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import encounter_builder as eb
import ati_coaching_encounter as ace

fails = []


def check(label, cond):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        fails.append(label)


# ── a builder with fake people, and no dialogs ────────────────────────────────

class _Dialogs:
    """Stand in for tkinter.messagebox: answer yes, and remember what was shown."""

    def __init__(self):
        self.errors = []
        self.asked = []
        self.answer = True

    def showerror(self, title, text, **kw):
        self.errors.append((title, text))

    def showwarning(self, title, text, **kw):
        self.errors.append((title, text))

    def showinfo(self, title, text, **kw):
        pass

    def askyesno(self, title, text, **kw):
        self.asked.append((title, text))
        return self.answer


dialogs = _Dialogs()
eb.messagebox = dialogs

app = eb.EncounterBuilder(eb._demo_people(), eb._demo_library(), demo=True)
app.withdraw()                      # don't flash a window on Dane's screen
app.update_idletasks()

NAMES = sorted(app.by_name)[:6]
sent = []                           # every jobs payload handed to the runner
reply = {}                          # what the canned runner hands back


def fake_run(jobs, options):
    sent.append(jobs)
    return dict(reply)


app._run_with_progress = fake_run


def add_group(names, note, coaching_type, note_only):
    """Drive the real form the way Dane does, then add the group."""
    app.checked = set(names)
    app.type_var.set(coaching_type)
    app._on_type_change()
    app.note_var.set(note_only)
    app.desc_text.delete("1.0", "end")
    app.desc_text.insert("1.0", note)
    app._add_group()


def reset():
    app.groups = []
    del sent[:]
    reply.clear()
    dialogs.errors = []
    dialogs.asked = []
    dialogs.answer = True
    app._update_batch()


# ── 1. the pending spec ───────────────────────────────────────────────────────

print("\nA group only carries a pending spec when something is outstanding")

reset()
add_group(NAMES[:2], "EIS and EEs reviewed glove selection for the task.",
          "Safety Coaching", note_only=False)
check("a finished description leaves no pending spec",
      app.groups[0].get("pending") is None)

add_group(NAMES[2:4], "hydration and magnesium", "Health/Wellness Coaching",
          note_only=True)
check("a note asks for a description",
      app.groups[1]["pending"]["description"] is True)
check("a note with a chosen type does NOT ask for a type",
      app.groups[1]["pending"]["coaching_type"] is False)
check("the note is kept on the group, not on the rows",
      app.groups[1]["pending"]["note"] == "hydration and magnesium"
      and "note" not in app.groups[1]["rows"][0])

add_group(NAMES[4:6], "talked through wrist pain from repetitive scanning",
          eb.SUGGEST_TYPE, note_only=True)
check("the sentinel asks for a coaching type",
      app.groups[2]["pending"]["coaching_type"] is True)
check("the note switch resets after a group is added", not app.note_var.get())

print("\nThe sentinel is not an EMR value")
check("SUGGEST_TYPE is not a coaching type",
      eb.SUGGEST_TYPE not in ace.COACHING_TYPE_UUIDS)
check("SUGGEST_TYPE has no checkbox set",
      eb.SUGGEST_TYPE not in ace.CHECKBOX_UUID_MAP)
_, sentinel_errs = ace.row_to_encounter(dict(app.groups[2]["rows"][0]), 1)
check("the real pre-flight rejects a row still holding the sentinel",
      any("coaching_type" in e and "is not valid" in e for e in sentinel_errs))


# ── 2. what leaves the machine ────────────────────────────────────────────────

print("\nWhat crosses the line carries no one")

reply.update({
    2: {"ref": 2, "description": "EIS and EEs discussed hydration through the shift "
                                 "and where magnesium fits in their daily intake."},
    3: {"ref": 3, "description": "EIS and EEs reviewed wrist positioning while "
                                 "scanning and went over a stretch to break it up.",
        "coaching_type": "Job-Specific Coaching"},
})
ok = app._resolve_pending()
check("the batch resolved", ok is True)
check("one call for the whole batch, not one per group", len(sent) == 1)

payload = json.dumps(sent[0], ensure_ascii=False)
leaked = [n for n in app.by_name if n.split(",")[0].strip() in payload
          or n.split(",")[-1].strip() in payload]
check("no employee name is in the payload", not leaked)

roster_values = set()
for row in app.batch:
    for field in ("employee", "date", "department", "division", "shift"):
        if row[field]:
            roster_values.add(row[field])
check("no date, department, division or shift is in the payload",
      not [v for v in roster_values if v in payload])
check("the job keys are only the ones the writing needs",
      all(set(j) == {"ref", "note", "people", "write_description",
                     "suggest_type", "coaching_type", "examples"} for j in sent[0]))
check("only the outstanding groups were sent", len(sent[0]) == 2)


# ── 3. what comes back lands on every row ─────────────────────────────────────

print("\nThe reply lands on every row of its group")

check("the note was replaced by the description",
      all("hydration through the shift" in r["description"]
          for r in app.groups[1]["rows"]))
check("the description reached BOTH people in the group",
      len({r["description"] for r in app.groups[1]["rows"]}) == 1
      and len(app.groups[1]["rows"]) == 2)
check("the suggested type replaced the sentinel",
      all(r["coaching_type"] == "Job-Specific Coaching"
          for r in app.groups[2]["rows"]))
check("every row now holds a real EMR coaching type",
      all(r["coaching_type"] in ace.COACHING_TYPE_UUIDS for r in app.batch))
check("nothing is left pending", not [g for g in app.groups if g.get("pending")])
check("the group label no longer shows the sentinel",
      eb.SUGGEST_TYPE not in app.groups[2]["label"])
check("a second resolve is a no-op, not a second call",
      app._resolve_pending() is True and len(sent) == 1)

print("\nThe untouched group is untouched")
check("the finished description was not rewritten",
      app.groups[0]["rows"][0]["description"].startswith("EIS and EEs reviewed glove"))


# ── 4. an off-list coaching type cannot be written ────────────────────────────

print("\nAn off-list coaching type is refused")

reset()
add_group(NAMES[:1], "back safety talk on the dock", eb.SUGGEST_TYPE, note_only=True)
reply.update({1: {"ref": 1, "description": "EIS and EE went over lifting mechanics.",
                  "coaching_type": "Back Safety Coaching"}})   # not an EMR value
check("resolve refuses it", app._resolve_pending() is False)
check("the row still holds the sentinel, not the invented type",
      app.groups[0]["rows"][0]["coaching_type"] == eb.SUGGEST_TYPE)
check("Dane is told nothing was written",
      any("Nothing was written" in t for t, _ in dialogs.errors))

print("\nAn empty coaching type is refused too")
reset()
add_group(NAMES[:1], "not sure what this one is", eb.SUGGEST_TYPE, note_only=True)
reply.update({1: {"ref": 1, "description": "EIS and EE talked it through.",
                  "coaching_type": ""}})
check("resolve refuses an unanswered type", app._resolve_pending() is False)


# ── 5. all or nothing, and only the outstanding go back ───────────────────────

print("\nOne short job stops the write; the rest keep what they got")

reset()
add_group(NAMES[:1], "hydration on a hot day", "Health/Wellness Coaching",
          note_only=True)
add_group(NAMES[1:2], "stretching at the press", "Safety Coaching", note_only=True)
reply.update({
    1: {"ref": 1, "description": "EIS and EE discussed water intake across the shift."},
    2: {"ref": 2, "description": ""},          # came back short
})
check("resolve refuses the batch", app._resolve_pending() is False)
check("the group that answered kept its description",
      app.groups[0]["rows"][0]["description"].startswith("EIS and EE discussed water"))
check("the group that answered is no longer pending",
      app.groups[0].get("pending") is None)
check("the short group is still pending", bool(app.groups[1].get("pending")))
check("the short group still holds its note",
      app.groups[1]["rows"][0]["description"] == "stretching at the press")

reply.clear()
reply.update({2: {"ref": 2, "description": "EIS and EEs went over a shoulder stretch "
                                           "to break up time at the press."}})
check("a second press resolves it", app._resolve_pending() is True)
check("only the outstanding group was re-sent",
      len(sent) == 2 and len(sent[1]) == 1 and sent[1][0]["ref"] == 2)


# ── 6. the name scan ──────────────────────────────────────────────────────────

print("\nA note that names somebody is caught before anything is sent")

reset()
surname = sorted(app.by_name)[0].split(",")[0].strip()
add_group(NAMES[:1], f"follow up with {surname} about the wrist",
          "Job-Specific Coaching", note_only=True)
hits = app._notes_naming_people([(0, app.groups[0])])
check("the scan finds the name", len(hits) == 1 and hits[0][1].lower() == surname.lower())

dialogs.answer = False
check("cancelling stops the send", app._resolve_pending() is False)
check("nothing was sent", not sent)
check("Dane was asked, not blocked outright",
      any("name in it" in t for t, _ in dialogs.asked))

dialogs.answer = True
reply.update({1: {"ref": 1, "description": "EIS and EE followed up on wrist symptoms."}})
check("he can send it anyway", app._resolve_pending() is True)

print("\nA note about nobody is not flagged")
reset()
add_group(NAMES[:1], "hydration and magnesium", "Health/Wellness Coaching",
          note_only=True)
check("no false positive on an ordinary note",
      not app._notes_naming_people([(0, app.groups[0])]))


# ── 7. the examples come off the workbook, not out of thin air ────────────────

print("\nThe writing standard is the workbook")
check("a known type gets examples from its own tab",
      len(app._library_examples("Health/Wellness Coaching")) > 0)
check("a suggestion gets a spread instead of one tab's worth",
      len(app._library_examples(None)) > 0)
check("examples are description text, never labels or hints",
      all(isinstance(t, str) and not t.startswith("Choose")
          for t in app._library_examples("Safety Coaching")))

app.destroy()
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
