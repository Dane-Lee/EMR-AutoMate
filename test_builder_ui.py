"""Regression tests for the encounter_builder window (2026-09-03 rebuild).

Run:  python test_builder_ui.py          (exit 0 = all pass)

WHAT THESE PROTECT
------------------
Three things Dane asked for, each of which has a way of quietly breaking:

1. INDIVIDUAL MODE IS SEARCH-ONLY. Its panel hides the shift/role/area filters, so those
   filters must also stop APPLYING. A filter you cannot see is a filter you cannot undo:
   with 'Admin' hidden between runs, a name inside it would simply never appear and
   nothing on screen would say why. The test hides every area and shift and then insists
   every name is still reachable.

2. FOLDED IS NOT HIDDEN. Every collapsed section's header must still show its current
   value. This form writes controlled values into medical records; a field that folds
   away and stops saying what it holds is how a wrong encounter type gets shipped.

3. DETAILS FOLDS ON THE ACCORDION, NOT ON A CLICK. It is multi-select -- folding on the
   first checkbox would put the second out of reach.

Plus the palette contrast, computed rather than eyeballed: the 2026-09-03 flip to a warm
gray ground broke every colour that had been chosen against the old near-black one, and
two of them (the amber, the shift rails) failed measurably while still looking fine.

FAKE DATA ONLY -- _demo_people() / _demo_library(), and the window is withdrawn.
NEEDS A DESKTOP SESSION: it builds a real Tk window.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import encounter_builder as eb

fails = []
def check(label, cond):
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        fails.append(label)

app = eb.EncounterBuilder(eb._demo_people(), eb._demo_library(), demo=True)
app.withdraw()                      # don't flash a window on Dane's screen
app.update_idletasks()

print("\nInitial fold state (items 8-12)")
check("Encounter type starts collapsed", app.etype_section.collapsed)
check("Coaching type starts open (no default, must be set)",
      not app.type_section.collapsed)
check("Details starts collapsed", app.details_section.collapsed)
check("Category starts collapsed", app.cat_section.collapsed)
check("Prompted by starts open", not app.prompted_section.collapsed)

print("\nFolded headers carry the value, so nothing is hidden")
check("Encounter type header shows its pick",
      app.etype_section.value.cget("text") == app.etype_var.get())
check("Category header shows its pick",
      app.cat_section.value.cget("text") == app.cat_var.get())
check("Open section shows no duplicate value",
      app.prompted_section.value.cget("text") == "")

print("\nPicking a coaching type folds it and opens Details (item 9/10)")
app.type_var.set("Safety Coaching")
app._pick_coaching_type()
app.update_idletasks()
check("Coaching type folded on select", app.type_section.collapsed)
check("Coaching type header names the pick",
      app.type_section.value.cget("text") == "Safety Coaching")
check("Details opened", not app.details_section.collapsed)
check("Details rebuilt for that type", len(app.detail_vars) > 0)

print("\nDetails is multi-select: a tick must NOT fold it")
first = sorted(app.detail_vars)[0]
app.detail_vars[first].set(True)
app.details_section.refresh()
app.update_idletasks()
check("still open after one tick", not app.details_section.collapsed)
second = sorted(app.detail_vars)[1] if len(app.detail_vars) > 1 else None
if second:
    app.detail_vars[second].set(True)
    app.details_section.refresh()
    check("second detail reachable", app.detail_vars[second].get())
app.details_section.collapse()
check("folded header names the picks",
      first.split()[0] in app.details_section.value.cget("text"))

print("\nAccordion: opening one folds the others")
app.etype_section.expand()
app.update_idletasks()
check("opened section is open", not app.etype_section.collapsed)
check("every other section folded",
      all(s.collapsed for s in app.sections if s is not app.etype_section))

print("\nCategory / Prompted by fold on selection (items 11/12)")
app.cat_section.expand()
app.cat_var.set(eb.ace.FIELD_OPTIONS.get("Category", [""])[-1])
app.cat_section.collapse()
check("Category header follows the var",
      app.cat_section.value.cget("text") == app.cat_var.get())
app.prompted_section.expand()
app.prompted_var.set(eb.ace.WHAT_PROMPTED_OPTIONS[-1])
app.prompted_section.collapse()
check("Prompted by header follows the var",
      app.prompted_section.value.cget("text") == app.prompted_var.get())

print("\nIndividuals mode strips the name picker (items 1-7)")
app.mode.set("individuals")
app._on_mode()
app.update_idletasks()
hidden = [w for w in app._roster_individual_hide if w.winfo_manager()]
check("shift / role / areas / separator / tally / hint all off the grid", not hidden)
check("'checked only' unpacked", not app.checked_only_box.winfo_manager())
check("search box still there", bool(app.find_entry.winfo_manager()))
check("roster list still there", bool(app.listbox.winfo_manager()))
check("mode switch still there", bool(app.mode_hint.winfo_manager()))

print("\nHidden filters must stop applying, or a name becomes unfindable")
app.hidden_areas = set(app.all_areas)          # hide every area
app.hidden_shifts = set(app.all_shifts)        # and every shift
app._refresh_list()
check("every name still reachable in individuals mode",
      len(app.shown) == len(app.people))
target = app.people[3]["name"]
app.filter_var.set(target.split(",")[0])
app._refresh_list()
check("search finds a name inside a hidden area",
      any(p["name"] == target for p in app.shown))

print("\nBack to Groups restores the filter block")
app.filter_var.set("")
app.mode.set("groups")
app._on_mode()
app.update_idletasks()
check("filters back on the grid",
      all(w.winfo_manager() for w in app._roster_individual_hide))
check("'checked only' back", bool(app.checked_only_box.winfo_manager()))
check("group filters apply again", len(app.shown) == 0)

print("\nShift Pool mode still builds")
app.hidden_areas, app.hidden_shifts = set(), set()
app._refresh_list()
app.mode.set("pool")
app._on_mode()
app.update_idletasks()
check("pool window opened", bool(app.pool_win.winfo_exists()))
check("filters visible in pool mode",
      all(w.winfo_manager() for w in app._roster_individual_hide))

print("\nPalette is a light warm gray (item 13)")
def lum(hexcol):
    r, g, b = (int(hexcol[i:i+2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)
def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + .05) / (lb + .05)

check("ground is light", lum(eb.UI_BG) > 0.6)
check("ground is warm (red channel highest)",
      int(eb.UI_BG[1:3], 16) > int(eb.UI_BG[5:7], 16))
check("body text on ground >= 4.5:1", ratio(eb.UI_TEXT, eb.UI_BG) >= 4.5)
check("body text on card  >= 4.5:1", ratio(eb.UI_TEXT, eb.UI_CARD) >= 4.5)
check("muted text on ground >= 4.5:1", ratio(eb.UI_MUTED, eb.UI_BG) >= 4.5)
check("accent TEXT on ground >= 4.5:1 (headers, legends)",
      ratio(eb.UI_ACCENT_TEXT, eb.UI_BG) >= 4.5)
check("accent focus ring on card >= 3:1", ratio(eb.UI_ACCENT_TEXT, eb.UI_CARD) >= 3)
check("text ON the amber fill >= 4.5:1", ratio(eb.UI_ON_ACCENT, eb.UI_ACCENT) >= 4.5)
check("amber fill still reads as amber, not brown (light enough to be a fill)",
      lum(eb.UI_ACCENT) > lum(eb.UI_ACCENT_TEXT) * 1.5)
check("confirm green on ground >= 4.5:1", ratio(eb.UI_CONFIRM, eb.UI_BG) >= 4.5)
check("checked-row text on its wash >= 4.5:1", ratio(eb.CHECK_FG, eb.CHECK_BG) >= 4.5)
# Separation between the SURFACES, not just text on them. Darkening the ground on
# 2026-09-04 put both of these at risk in opposite directions: the card had to stay
# clearly lighter than its new ground, and the checked-row wash had to stay clearly
# distinguishable from the card it sits on -- a pale amber on a near-white list is the
# whole "which names did I check" signal, and it can wash out while every text-contrast
# check above still passes.
check("card lifts off the ground", ratio(eb.UI_CARD, eb.UI_BG) >= 1.18)
check("checked row reads against the card", ratio(eb.CHECK_BG, eb.UI_CARD) >= 1.15)
check("borders read against the ground", ratio(eb.UI_BORDER, eb.UI_BG) >= 1.12)
for shift, colour in eb.SHIFT_RAIL.items():
    check(f"{shift} rail on card >= 4.5:1", ratio(colour, eb.UI_CARD) >= 4.5)
# Distinctness here is a HUE question, not a luminance one — a blue and an amber at
# the same lightness are still trivially distinguishable, and the first version of this
# check used a luminance ratio and failed a palette that was fine.
def hue(hexcol):
    r, g, b = (int(hexcol[i:i+2], 16) / 255 for i in (1, 3, 5))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60
def hue_gap(a, b):
    d = abs(hue(a) - hue(b)) % 360
    return min(d, 360 - d)
for shift, colour in eb.SHIFT_RAIL.items():
    check(f"{shift} rail is a different hue from the accent (>=60 deg)",
          hue_gap(colour, eb.UI_ACCENT) >= 60)
rails = list(eb.SHIFT_RAIL.values())
check("the three rails are distinct hues from each other",
      all(hue_gap(rails[i], rails[j]) >= 40
          for i in range(len(rails)) for j in range(i + 1, len(rails))))


print("\nCase list report tab (2026-09-08)")
# The whole window moved into a Notebook. If the build panels ever end up parented to
# the root again they still LOOK right -- they just stop being on a tab, which is how
# a working batch flow disappears behind a tab strip.
tabs = [app.book.tab(i, "text") for i in app.book.tabs()]
check("two tabs, batch first", tabs == ["Build a batch", "Case list report"])
check("the roster list lives on the build tab",
      str(app.listbox).startswith(str(app.build_tab)))
check("the batch buttons live on the build tab",
      str(app.add_btn).startswith(str(app.build_tab)))
check("the report controls live on the report tab",
      str(app.rep_status).startswith(str(app.report_tab)))

# The range presets. Weeks start Monday; last month is the whole previous month.
app._report_preset("last_week")
lw_from = eb.datetime.strptime(app.rep_from.get(), "%m/%d/%Y").date()
lw_to = eb.datetime.strptime(app.rep_to.get(), "%m/%d/%Y").date()
check("last week starts on a Monday", lw_from.weekday() == 0)
check("last week is seven days", (lw_to - lw_from).days == 6)
check("last week is in the past", lw_to < eb.date.today())

app._report_preset("last_month")
lm_from = eb.datetime.strptime(app.rep_from.get(), "%m/%d/%Y").date()
lm_to = eb.datetime.strptime(app.rep_to.get(), "%m/%d/%Y").date()
check("last month starts on the 1st", lm_from.day == 1)
check("last month ends before this month starts",
      lm_to < eb.date.today().replace(day=1))
check("last month is one month", lm_from.month == lm_to.month)

# A backwards range is corrected, not reported as empty -- an empty report reads as
# "a quiet week", which is the wrong answer that looks right.
app.rep_from.set("09/10/2026")
app.rep_to.set("09/01/2026")
rng = app._report_range()
check("a backwards range is swapped, not rejected",
      rng is not None and rng[0] < rng[1])

# _open_calendar took a `var` argument so the report tab could reuse it. If that
# defaulting ever slips, picking a REPORT date silently rewrites the ENCOUNTER date --
# a field that goes into medical records.
before_encounter = app.date_var.get()
app.rep_from.set("01/01/2020")
top = app._open_calendar(app.rep_from)
def click_today(widget):
    for w in widget.winfo_children():
        if isinstance(w, eb.ttk.Button) and w.cget("text") == "Today":
            w.invoke()
            return True
        if click_today(w):
            return True
    return False
clicked = click_today(top)
app.update_idletasks()
check("the picker wrote into the var it was handed", clicked and
      app.rep_from.get() == eb.date.today().strftime("%m/%d/%Y"))
check("and left the encounter date alone", app.date_var.get() == before_encounter)

check("the reader is measured and live", eb.case_report.PARSER_READY is True)
# Dane asked not to have to go hunting in the project folder for the file.
latest = eb.case_report.newest_report()
check("Open-last-report is offered exactly when there IS one",
      (str(app.rep_open_btn["state"]) == "normal") == bool(latest))
check("the tab reaches the same range parser the reader uses",
      eb.case_report.parse_date("09/02/2026") == eb.date(2026, 9, 2))


app.destroy()
print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
