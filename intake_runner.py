"""
intake_runner.py — hand a batch of intake rows to a headless Claude
===================================================================
The middle of the loop. `intake_grid.py` collects de-identified rows; this runs
`claude -p` against them and returns one written block per `ref`.

WHY HEADLESS AND NOT AN API
    No API key, no credits, no new dependency — this is the same Claude Code that
    Dane already runs, invoked with -p. It loads CLAUDE.md on its own (measured
    2026-08-25: it answered a question that only CLAUDE.md contains, with no tool
    call), so the PHI boundary, the description voice, and the protective-
    recommendation rule arrive with it rather than being restated here and drifting.

ONE CALL PER BATCH, NEVER ONE PER ROW
    Measured 2026-08-25: a trivial -p call costs ~$0.24 and a small one with a file
    read ~$0.38, almost all of it fixed overhead — ~22k tokens of system prompt and
    project instructions get cached on every invocation. Cost tracks the number of
    INVOCATIONS, not the number of rows. Forty rows in one call is roughly the price
    of one row in one call.

PHI
    Rows arrive already de-identified — the sheet has no name column. Nothing here
    prints row content: progress is counts, and failures name the ref, never the
    text. The prompt goes to the local claude binary, which talks to Anthropic the
    same way this chat does; it does not go anywhere else.
"""

import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_MD = os.path.join(_HERE, "pa_templates.md")

MODEL = "claude-opus-5"
TIMEOUT_S = 600          # a 40-row batch is a lot of writing; the GUI shows progress

# Claude Code ships inside the VS Code extension on this machine and is NOT on PATH
# (checked 2026-08-25). PATH is still tried first so that installing it properly later
# just works and this fallback stops being used.
_EXT_DIR = os.path.join(os.path.expanduser("~"), ".vscode", "extensions")
_EXT_RE = re.compile(r"^anthropic\.claude-code-(\d+(?:\.\d+)*)-")


class RunnerError(RuntimeError):
    """Something went wrong that Dane needs to see in the window."""


def find_claude():
    """Locate the claude binary, newest first. Returns a path or raises."""
    from shutil import which
    found = which("claude")
    if found:
        return found

    best = None
    if os.path.isdir(_EXT_DIR):
        for name in os.listdir(_EXT_DIR):
            match = _EXT_RE.match(name)
            if not match:
                continue
            exe = os.path.join(_EXT_DIR, name, "resources", "native-binary",
                               "claude.exe" if os.name == "nt" else "claude")
            if not os.path.exists(exe):
                continue
            # Version-sort numerically. Twelve versions sit side by side and a string
            # sort puts 2.1.99 above 2.1.245.
            key = tuple(int(p) for p in match.group(1).split("."))
            if best is None or key > best[0]:
                best = (key, exe)
    if best:
        return best[1]

    raise RunnerError(
        "Could not find the claude command.\n\n"
        "It is not on PATH and no copy was found in the VS Code extensions folder.\n"
        "Installing it globally fixes this permanently:\n\n"
        "    npm i -g @anthropic-ai/claude-code")


def _templates():
    """The voice, the controlled vocabularies, and the protective-recommendation rule.

    Embedded rather than left to a tool call: it makes the run deterministic (the
    same rules every time, not whatever the agent chose to look at), removes a
    permission surface, and saves a round trip. CLAUDE.md is NOT embedded — the CLI
    loads it by itself."""
    try:
        with open(TEMPLATES_MD, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


_TASK = """\
You are writing encounter descriptions for Dane's EMR entries, exactly as you would
in chat with him. Your project instructions (CLAUDE.md) are already loaded — the
description voice, the plain-language rule, the protective-recommendation rule and
the red-flag rule all apply here unchanged.

The rows below are DE-IDENTIFIED. Each is keyed by `ref`; Dane maps ref back to a
person on his own machine. There are no names and you must never invent one, never
address the employee by name, and never refer to a specific date.

For each row, write what goes in the EMR.

COACHING rows (kind = Coaching)
    One field: `description`. One to three sentences, third person, EIS / EE, past
    tense, they/their. Plain language, athletic-trainer level, not clinical. Say what
    happened and what was covered, then stop.

ASSESSMENT rows (kind = Assessment)
    Return the page-2 fields you are entitled to write:
      - `incident_details`  — free text, written from the row's description
      - `primary_complaint` — one of the recorded options
      - `mechanism`         — one of the recorded options

    NEVER return a controlled value as an empty string with only a flag. Dane picks
    these from a dropdown in the EMR and a blank field helps him less than nothing.
    If one option is clearly right, give it. If two or three could fit, leave the
    field "" and list those candidates — VERBATIM from the recorded list, most likely
    first — in `primary_complaint_options` / `mechanism_options`. Never invent an
    option that is not on the recorded list, and never leave both the value and the
    candidates empty.
    Palpation and observation are DANE'S OWN EXAM FINDINGS. Leave them as the literal
    string "[ ]". Never write a plausible-sounding finding.
    If protective recommendations are called for, put them in `protective_recs` using
    permissive verbs only. Never a numeric limit, never "restricted to", "may not",
    "must", "light duty", or "unable to".
    Never write a red-flag field as negative and never clear anyone. If the row
    touches a red-flag item, name it in `flags` and leave the triage to Dane.

STATUS on every row
    "READY"  — complete, nothing needed
    "SLOTS"  — contains [ ] slots for Dane to fill
    "OPEN"   — you could not write it; say why in `flags`

Anything you cannot decide goes in `flags` as a short phrase. Do not guess a
controlled value that is not on a recorded list, and do not guess work-relatedness.

OUTPUT
Return ONLY a JSON object, no prose and no code fence, shaped:

{"results": [{"ref": 1, "status": "READY", "description": "...", "flags": []},
             {"ref": 2, "status": "SLOTS", "incident_details": "...",
              "primary_complaint": "Musculoskeletal", "primary_complaint_options": [],
              "mechanism": "", "mechanism_options": ["Overuse", "Insidious onset"],
              "palpation": "[ ]", "observation": "[ ]",
              "protective_recs": "...", "flags": []}]}

Every ref from the input must appear exactly once in the output.
"""


def build_prompt(rows, sheet_date=""):
    """The whole instruction, built here so a run is reproducible and inspectable."""
    templates = _templates()
    parts = [_TASK]
    if templates:
        parts.append(
            "\n=== pa_templates.md — the shapes, the controlled vocabularies, and the\n"
            "=== protective-recommendation rule. Treat the option lists as closed.\n\n"
            + templates)
    parts.append("\n=== ROWS (%d)%s\n\n%s"
                 % (len(rows),
                    (", sheet date %s" % sheet_date) if sheet_date else "",
                    json.dumps({"rows": rows}, indent=2, ensure_ascii=False)))
    return "\n".join(parts)


def _extract_json(text):
    """The contract asks for bare JSON. Models sometimes fence it anyway, so peel a
    fence if there is one and fall back to the outermost braces."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("no JSON object in the reply")


def _invoke(prompt, on_progress, sending):
    """One call to the CLI: send `prompt`, hand back the parsed JSON body and the meta.

    Shared by both entry points so a coaching batch and an assessment batch fail the
    same way with the same messages. Nothing on an error path carries row content —
    only counts, costs, and the CLI's own stderr."""
    exe = find_claude()
    if on_progress:
        on_progress(sending)

    cmd = [exe, "-p", prompt, "--output-format", "json", "--model", MODEL]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT_S, cwd=_HERE,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise RunnerError("The run took longer than %d seconds and was stopped.\n\n"
                          "Nothing came back and nothing was changed." % TIMEOUT_S)
    except OSError as exc:
        raise RunnerError("Could not start claude:\n\n%s" % exc)

    if done.returncode != 0:
        raise RunnerError("claude exited with code %d.\n\n%s"
                          % (done.returncode, (done.stderr or "").strip()[:800]))

    try:
        envelope = json.loads(done.stdout)
    except ValueError:
        raise RunnerError("claude did not return JSON. First 400 characters of "
                          "stderr:\n\n%s" % (done.stderr or "").strip()[:400])

    if envelope.get("is_error"):
        raise RunnerError("The run reported an error:\n\n%s"
                          % str(envelope.get("result", ""))[:800])

    if on_progress:
        on_progress("Reading the reply...")

    try:
        parsed = _extract_json(envelope.get("result", ""))
    except ValueError as exc:
        raise RunnerError("Could not read the reply as JSON (%s).\n\n"
                          "The run cost $%.2f and produced %d characters."
                          % (exc, envelope.get("total_cost_usd") or 0.0,
                             len(str(envelope.get("result", "")))))

    meta = {"cost_usd": envelope.get("total_cost_usd") or 0.0,
            "session_id": envelope.get("session_id", ""),
            "duration_ms": envelope.get("duration_ms") or 0}
    return parsed, meta


def _by_ref(parsed, rows, meta):
    """Index the reply by ref and account for every row that was sent.

    A ref that never came back is recorded as an absence rather than dropped, so the
    caller always holds one entry per row and can name the ones left unanswered."""
    results = {}
    for item in parsed.get("results") or []:
        try:
            results[int(item["ref"])] = item
        except (KeyError, TypeError, ValueError):
            continue      # a malformed entry is reported by absence, below

    missing = [r["ref"] for r in rows if int(r["ref"]) not in results]
    for ref in missing:
        results[ref] = {"ref": ref, "status": "OPEN",
                        "flags": ["no result came back for this row"]}

    meta = dict(meta)
    meta["missing"] = missing
    results["_meta"] = meta
    return results


def run(rows, sheet_date="", on_progress=None):
    """Run one intake-grid batch. Returns {ref: result_dict}.

    `rows` are payload dicts from the grid. Raises RunnerError with something worth
    showing in a dialog; never prints row content."""
    if not rows:
        return {}
    parsed, meta = _invoke(
        build_prompt(rows, sheet_date), on_progress,
        "Sending %d row%s..." % (len(rows), "" if len(rows) == 1 else "s"))
    results = _by_ref(parsed, rows, meta)
    if on_progress:
        on_progress("%d back, $%.2f" % (len(results) - 1, meta["cost_usd"]))
    return results


# ─────────────────────────────────────────────
# COACHING BATCH — the encounter builder's path
# ─────────────────────────────────────────────
# Narrower than the grid's job above, deliberately. By the time a group reaches here the
# builder has already collected every controlled value except, optionally, the coaching
# type — and Dane ticks the detail checkboxes himself in the EMR. So there are exactly
# two things to return: the description text, and the coaching type when he asked for a
# suggestion. Anything else that comes back is ignored by the caller.

_COACHING_TASK = """\
You are finishing encounter descriptions for a batch Dane has already built in the
encounter builder. Your project instructions (CLAUDE.md) are loaded — the description
voice and the plain-language rule apply here unchanged.

Each job below is ONE group of encounters. It carries a `note`: what Dane wants the
description to say, in his own words. The jobs are DE-IDENTIFIED — no names, no dates,
no departments. Never invent one, never address anyone by name, never refer to a
specific date, and never write anything that could only be true of one person.

WRITE THE DESCRIPTION  (jobs with "write_description": true)
    Replace the note with the text that goes in the record. One to three sentences,
    third person, EIS / EE, past tense, they/their. Plain language at an athletic
    trainer's level, not clinical. Say what happened and what was covered, then stop —
    no closing reassurance, no explaining why it matters, no listing every variation.
    `people` is how many employees the group covers: write EE for one, EEs for several.
    `examples` are real descriptions already in use for that coaching type, taken from
    Dane's own workbook. They are the standard — match their scale and their voice
    rather than any rubric of your own.
    When "write_description" is false the text is already Dane's: leave `description`
    out of that result entirely and do not rewrite it.

SUGGEST THE COACHING TYPE  (jobs with "suggest_type": true)
    Return `coaching_type`, copied VERBATIM from `coaching_type_options`. It is a
    controlled EMR value; anything not on that list cannot be entered. Dane reviews
    every suggestion before it is saved, so give your best single pick rather than
    hedging. Only if the note genuinely does not say enough to choose, return "" and
    put the candidates in `coaching_type_candidates`, verbatim, most likely first.
    Never return a type that is not on the list.
    When "suggest_type" is false he has already chosen it: leave `coaching_type` out.

NOT YOURS TO SET
    Detail checkboxes, encounter type, category, department, shift and date. Dane sets
    every one of them himself. Do not mention them and do not return them.

OUTPUT
Return ONLY a JSON object, no prose and no code fence, shaped:

{"results": [{"ref": 1, "description": "EIS and EE discussed ...", "flags": []},
             {"ref": 2, "description": "...", "coaching_type": "Safety Coaching",
              "flags": []}]}

Every ref from the input must appear exactly once.
"""


def build_coaching_prompt(jobs, options):
    """The whole instruction for a builder batch — inspectable, and the same every run."""
    return "\n".join([
        _COACHING_TASK,
        "\n=== COACHING TYPES — the closed list. A value not on it is not enterable.\n\n"
        + json.dumps({"coaching_type_options": list(options)}, indent=2,
                     ensure_ascii=False),
        "\n=== JOBS (%d)\n\n%s" % (len(jobs),
                                   json.dumps({"jobs": jobs}, indent=2,
                                              ensure_ascii=False)),
    ])


def run_coaching(jobs, options, on_progress=None):
    """Run one encounter-builder batch. Returns {ref: result_dict} plus `_meta`.

    `jobs` are de-identified group specs from the builder. Raises RunnerError with
    something worth putting in a dialog; never prints or returns note text on an
    error path."""
    if not jobs:
        return {}
    parsed, meta = _invoke(
        build_coaching_prompt(jobs, options), on_progress,
        "Writing %d description%s..." % (len(jobs), "" if len(jobs) == 1 else "s"))
    results = _by_ref(parsed, jobs, meta)
    if on_progress:
        on_progress("%d back, $%.2f" % (len(results) - 1, meta["cost_usd"]))
    return results


def main():
    """`python intake_runner.py --dry-run` prints the prompt without calling anything.

    Row content is Dane's to look at, so the dry run writes to a file he opens rather
    than to stdout, which is redacted for a reason."""
    if "--where" in sys.argv:
        print(find_claude())
        return
    if "--dry-run" not in sys.argv:
        print("usage: python intake_runner.py [--dry-run | --where]")
        return

    outbox = os.path.join(_HERE, "intake_outbox.json")
    if not os.path.exists(outbox):
        print("No intake_outbox.json — send some rows from the grid first.")
        return
    with open(outbox, encoding="utf-8") as fh:
        data = json.load(fh)
    prompt = build_prompt(data.get("rows") or [], data.get("sheet_date", ""))
    path = os.path.join(_HERE, "intake_prompt.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(prompt)
    print("Wrote %s (%d characters, %d rows). Nothing was sent."
          % (os.path.basename(path), len(prompt), len(data.get("rows") or [])))


if __name__ == "__main__":
    main()
