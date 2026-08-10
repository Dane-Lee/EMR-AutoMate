"""
EMR Tracker Lite capture -> encounter_builder
=============================================
Reads the JSON file Tracker Lite drops into the shared folder (OneDrive / Google Drive)
and turns it into builder rows, so a floor capture lands in the builder to be finished,
grouped and batched — exactly like a row Dane checked off the roster himself.

    Tracker Lite (phone/Vercel)  ->  shared folder  ->  encounter_builder  ->  AutoMate

WHAT THE PHONE IS ALLOWED TO SEND
---------------------------------
Only what it legitimately knows: who, when, what coaching type, which detail boxes, the
description, and what prompted it.

It does NOT send department, division, category or shift. Those come from the roster on
this side, every time. The phone's copy of a work area can be weeks stale, and a stale
department is not a visible error — it is a wrong value in a medical record that looks
exactly like a right one. The roster is the single source of truth for controlled values
and this bridge does not get to override it.

The same reasoning caps the trust on coaching_type: it is checked against AutoMate's own
list and a value that is not on it is REFUSED, not corrected or guessed at.

PHI
---
Captures contain real names and clinical text. This module prints through phi_redact —
counts and `Employee #1`, never a name — so a redacted run says which capture failed and
why, never who. The capture file itself is gitignored.
"""

import json
import os
import sys
from datetime import datetime

import name_match
import phi_redact
from phi_redact import ph, pd

_HERE = os.path.dirname(os.path.abspath(__file__))

# The file Tracker Lite writes. Kept in sync with src/lib/builderExport.js over there —
# both repos name the schema so a mismatch is loud instead of silent.
CAPTURE_FILENAME = "tracker_capture.json"
SCHEMA = "emr-tracker-lite/capture@1"

# The subfolder Tracker Lite drops captures into, inside whichever cloud folder is in use.
TRACKER_SUBDIR = "EMR Tracker"


def onedrive_root():
    """Dane's OneDrive folder, from Windows itself — never guessed.

    Windows sets %OneDrive% (and %OneDriveCommercial% for a work tenant) to the real sync
    root, so the tenant name never has to be spelled out. It is spelled differently than
    you would assume, too: this machine's is "OneDrive - ATI Holdings LLC", and an earlier
    version of this file guessed "OneDrive - ATI Physical Therapy" and silently matched
    nothing. Read it, don't predict it.
    """
    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        path = os.environ.get(var, "").strip()
        if path and os.path.isdir(path):
            return path
    return ""


def default_search_dirs():
    """Where to look for a capture, best first. The first existing file wins.

    The OneDrive sync folder is the intended transport: Tracker Lite writes there from
    the browser, OneDrive carries it to this PC, the builder picks it up. Downloads is
    the fallback for the browsers with no File System Access API (Safari, all of iOS),
    where the send is a plain download Dane moves himself.
    """
    home = os.path.expanduser("~")
    dirs = [os.environ.get("EMR_TRACKER_DIR", "")]

    root = onedrive_root()
    if root:
        # Known Folder Move is on for this account, so Downloads lives INSIDE OneDrive
        # and ~/Downloads does not exist at all. The browser-download fallback lands
        # there, so it has to be on this list or that path finds nothing.
        dirs += [os.path.join(root, TRACKER_SUBDIR), os.path.join(root, "Downloads"), root]

    # Google Drive's desktop client mounts a letter rather than a home subfolder, so
    # check both shapes. Absent ones are skipped by the caller.
    dirs += [
        os.path.join(home, "Google Drive", TRACKER_SUBDIR),
        os.path.join(home, "My Drive", TRACKER_SUBDIR),
        os.path.join(home, "Downloads"),      # only exists without Known Folder Move
        _HERE,
    ]
    return dirs


def suggested_drop_folder():
    """Where Dane should point Tracker Lite's "Set folder" — created if missing.

    Returns (path, created). Falls back to Downloads if there is no OneDrive at all.
    """
    root = onedrive_root()
    if not root:
        return os.path.join(os.path.expanduser("~"), "Downloads"), False
    target = os.path.join(root, TRACKER_SUBDIR)
    if os.path.isdir(target):
        return target, False
    try:
        os.makedirs(target, exist_ok=True)
        return target, True
    except OSError:
        return root, False


def find_capture_file(explicit=None):
    """Locate the capture file. Returns a path, or None."""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for folder in default_search_dirs():
        if not folder:
            continue
        candidate = os.path.join(folder, CAPTURE_FILENAME)
        if os.path.exists(candidate):
            return candidate
    return None


def _mdy(value):
    """Tracker Lite sends ISO 'YYYY-MM-DD'; the builder and CSV want 'MM/DD/YYYY'."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return ""


def load_captures(path):
    """Read + validate the capture file. Returns (captures, errors).

    A capture that fails validation is dropped with a reason rather than repaired.
    Repairing a half-understood record is how a guess reaches a medical record.
    """
    errors = []
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"Could not read the capture file: {exc}"]

    if isinstance(data, list):          # tolerate a bare array
        data = {"schema": SCHEMA, "captures": data}
    if not isinstance(data, dict):
        return [], ["The capture file is not an object or an array."]

    schema = data.get("schema", "")
    if schema and schema != SCHEMA:
        errors.append(f"Capture file says schema '{schema}', this build expects "
                      f"'{SCHEMA}'. Reading it anyway — check the fields look right.")

    raw = data.get("captures") or data.get("records") or []
    captures = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            errors.append(f"Capture {i}: not an object — skipped.")
            continue
        name = (item.get("employee") or "").strip()
        date = _mdy(item.get("date"))
        ctype = (item.get("coaching_type") or "").strip()
        if not name:
            errors.append(f"Capture {i}: no employee name — skipped.")
            continue
        if not date:
            errors.append(f"Capture {i}: date '{item.get('date')}' isn't a date I "
                          f"recognise — skipped.")
            continue
        details = item.get("details")
        if isinstance(details, list):
            details = "; ".join(str(d).strip() for d in details if str(d).strip())
        captures.append({
            "employee": name,
            "date": date,
            "coaching_type": ctype,
            "details": (details or "").strip(),
            "description": (item.get("description") or "").strip(),
            "what_prompted": (item.get("what_prompted") or "").strip(),
            "capture_id": str(item.get("id") or f"row{i}"),
        })
    return captures, errors


def match_to_roster(captures, people, valid_coaching_types=None):
    """Resolve each capture against the roster. Returns (matched, problems).

    matched  — [(capture, person)] ready to become builder rows
    problems — [(capture, reason)] for Dane to look at; nothing is guessed

    Name matching reuses name_match, so a nickname resolves here exactly as it does in
    the entry engine, and an ambiguous name is REFUSED rather than resolved to whoever
    sorts first. Coaching type is validated against AutoMate's own list.
    """
    names = [p["name"] for p in people]
    by_name = {p["name"]: p for p in people}
    matched, problems = [], []

    for cap in captures:
        if valid_coaching_types and cap["coaching_type"] and \
                cap["coaching_type"] not in valid_coaching_types:
            problems.append((cap, f"coaching type '{cap['coaching_type']}' is not one "
                                  f"the EMR accepts"))
            continue
        idx, how = name_match.find_matches(cap["employee"], names)
        if len(idx) == 1:
            matched.append((cap, by_name[names[idx[0]]]))
        elif len(idx) > 1:
            problems.append((cap, f"name matches {len(idx)} people on the roster — "
                                  f"too ambiguous to pick one"))
        else:
            problems.append((cap, "no one on the roster matches that name"))
    return matched, problems


def to_builder_rows(matched, encounter_type="In Person", category=""):
    """Turn matched captures into builder/CSV rows.

    Department, division and shift come from the ROSTER person, never from the capture.
    That is the whole safety argument for this bridge: the phone contributes free text
    and an identity, and every controlled value is looked up here.
    """
    rows = []
    for cap, person in matched:
        rows.append({
            "employee": person["name"],
            "date": cap["date"],
            "encounter_type": encounter_type,
            "department": person.get("dept", ""),
            "division": person.get("div", ""),
            "category": category,
            "shift": person.get("shift", ""),
            "coaching_type": cap["coaching_type"],
            "details": cap["details"],
            "description": cap["description"],
            "what_prompted": cap["what_prompted"],
        })
    return rows


def archive_capture(path):
    """Move a consumed capture aside so the same encounters can't be imported twice.

    Renamed rather than deleted — if an import turns out wrong, the file is still there.
    Returns the new path, or None if the move failed (which is not fatal).
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder, base = os.path.split(path)
    target = os.path.join(folder, f"{os.path.splitext(base)[0]}.imported.{stamp}.json")
    try:
        os.replace(path, target)
        return target
    except OSError:
        return None


def import_for_builder(people, path=None, valid_coaching_types=None,
                       encounter_type="In Person", category=""):
    """One call for the builder: find, load, match, convert.

    Returns (rows, problems, errors, path). `rows` are builder rows ready to add;
    `problems` are captures that could not be resolved, each with a reason.
    """
    found = find_capture_file(path)
    if not found:
        return [], [], [f"No {CAPTURE_FILENAME} found. Looked in: " +
                        ", ".join(d for d in default_search_dirs() if d)], None
    captures, errors = load_captures(found)
    matched, problems = match_to_roster(captures, people, valid_coaching_types)
    rows = to_builder_rows(matched, encounter_type=encounter_type, category=category)
    return rows, problems, errors, found


def _cli():
    """python tracker_import.py [path] — report what would be imported. Changes nothing."""
    import encounter_builder as eb
    import ati_coaching_encounter as ace

    path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    people, problem = eb.load_roster()
    if problem:
        sys.exit(problem)

    rows, problems, errors, found = import_for_builder(
        people, path, valid_coaching_types=set(ace.CHECKBOX_UUID_MAP))
    for e in errors:
        print(f"  ! {e}")
    if not found:
        return
    print(f"Capture file: {found}")
    print(f"  ready to import : {len(rows)}")
    print(f"  needs attention : {len(problems)}")
    for cap, why in problems:
        print(f"    - {ph(cap['employee'])} [{cap['coaching_type'] or 'no type'}] — {why}")
    if rows:
        print("\n  Rows (redacted):")
        for r in rows:
            print(f"    {ph(r['employee']):<14} {r['date']}  {r['coaching_type']:<38} "
                  f"{r['department'] or '(no dept)':<18} {pd(r['description'])}")


if __name__ == "__main__":
    _cli()
