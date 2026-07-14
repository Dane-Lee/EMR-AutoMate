r"""
make_copilot_prompt.py — build the paste-ready M365 Copilot prompt
==================================================================
M365 Copilot lives in a browser, not in this folder — it cannot read your description
library off disk. So we paste the library *into* the prompt.

    copilot_spec.md          (the instructions — tracked, PHI-free)
  + description_library.md   (your standard descriptions — from library_export.py)
  = copilot_prompt.md        (paste this whole file into M365 Copilot)

RUN IT
    python make_copilot_prompt.py

    Re-run whenever you add descriptions to the workbook (after library_export.py).

WHY THE TWO-FILE SPLIT
    Claude maintains the spec but is not cleared to read the library. Keeping them in
    separate files, glued together by this script, means Claude can edit the
    instructions without ever touching your descriptions. This script prints only
    counts — never content — so its output is safe to show anyone.

DAILY USE
    1. Open copilot_prompt.md, select all, copy.
    2. Paste into a fresh M365 Copilot chat. It will wait for your notes.
    3. Dictate the day's encounters.
    4. Copy its whole reply, then run:  .\Paste-Encounters.ps1
"""

import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "copilot_spec.md")
LIBRARY = os.path.join(HERE, "description_library.md")
OUTPUT = os.path.join(HERE, "copilot_prompt.md")

# The spec file explains itself to a human reader before the actual prompt starts.
# Everything above this marker is for Dane; everything below is for Copilot.
SPEC_MARKER = "\n---\n"


def read(path, what):
    if not os.path.exists(path):
        sys.exit(f"Missing {os.path.basename(path)} — {what}")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def build():
    spec = read(SPEC, "the instruction spec should be in this folder.")
    library = read(LIBRARY, "run `python library_export.py` first to generate it.")

    # Drop the human-facing preamble; Copilot only needs what follows the marker.
    if SPEC_MARKER in spec:
        spec = spec.split(SPEC_MARKER, 1)[1].strip()

    # Strip the library's own preamble down to just the tables — the prompt already
    # told Copilot how to use them, and repeating it wastes the context window.
    lib_body = library
    if "\n## " in lib_body:
        lib_body = lib_body[lib_body.index("\n## "):].strip()

    out = "\n".join([
        spec,
        "",
        "---",
        "",
        "# STANDARD DESCRIPTION LIBRARY",
        "",
        "Reuse one of these whenever it fits the encounter, filling any `____`",
        "placeholder with what was actually said. Only write a new description when",
        "nothing here fits — and list any you write under `NEW DESCRIPTIONS`.",
        "",
        lib_body,
        "",
    ])

    with open(OUTPUT, "w", encoding="utf-8") as fh:
        fh.write(out)

    # Counts only — no content — so this output is safe anywhere.
    print(f"Wrote {os.path.basename(OUTPUT)}  ({date.today():%m/%d/%Y})")
    print(f"  spec    : {len(spec.splitlines())} lines")
    print(f"  library : {len([l for l in lib_body.splitlines() if l.startswith('|')])} table rows")
    print(f"  total   : {len(out.splitlines())} lines, {len(out):,} characters")
    print("\nOpen copilot_prompt.md, copy all of it, paste into a fresh M365 Copilot")
    print("chat, then dictate your notes.")


if __name__ == "__main__":
    build()
