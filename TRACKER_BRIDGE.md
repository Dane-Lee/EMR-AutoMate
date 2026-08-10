# Tracker Lite → Encounter Builder

Capture an encounter on the floor, finish it at the desk.

```
Tracker Lite (phone / Vercel)
      │  "→ Send to Builder"
      ▼
tracker_capture.json  in the shared folder (OneDrive / Google Drive)
      │  OneDrive syncs it to the PC
      ▼
encounter_builder.py  "📥 From Tracker Lite"     ← finish, group, batch here
      │  "Write & enter batch"
      ▼
encounters.csv → ati_coaching_encounter.py → the EMR (as drafts)
```

Captures re-enter the pipeline **at the builder**, never at the EMR. Everything still
passes the builder, the validator and the pre-flight exactly as a hand-built batch does.

## The rule that makes this safe

**The phone sends an identity and free text. Every controlled value is looked up here.**

| Tracker Lite sends | The builder supplies |
|---|---|
| employee (`Last, First`) | department — from the roster |
| date | division — from the roster |
| coaching_type | shift — from the roster |
| details (checkboxes) | category — from the form |
| description | encounter_type — from the form |
| what_prompted | |

Department, division and shift are **never** taken from the capture, even if it carries
them. The phone's copy of a work area can be weeks stale, and a stale department is not
a visible error — it is a wrong value in a medical record that looks exactly like a
right one. `test_tracker_import.py` pins this down with a deliberately poisoned capture.

Coaching type is checked against AutoMate's own list and **refused** if unknown — not
corrected, not guessed. An ambiguous or unrecognised name is refused the same way, using
the same `name_match` that the entry engine uses.

## Setup, once

**In Tracker Lite** — open Records and press **Set folder**, then choose the folder
OneDrive (or Drive) syncs to the PC, e.g. `OneDrive/EMR Tracker`. The browser remembers
it, so every later send is one click.

Needs Chrome or Edge on desktop. Safari and iOS have no File System Access API, so
there the send falls back to a normal download and you move the file across yourself.
That fallback is expected, not a failure.

**In AutoMate** — nothing, if you used one of the folders it already checks:

```
%EMR_TRACKER_DIR%              (set this to override everything)
%OneDrive%\EMR Tracker         ← the drop folder, already created
%OneDrive%\Downloads           ← where a Safari/iOS download lands
%OneDrive%
~/Google Drive/EMR Tracker
~/My Drive/EMR Tracker
~/Downloads                    (only exists without Known Folder Move)
the repo folder
```

First match wins. **The OneDrive path is read from Windows' own `%OneDrive%`, never
spelled out** — on this machine it resolves to `OneDrive - ATI Holdings LLC`, and an
earlier version of this file guessed "ATI Physical Therapy" and matched nothing.

Note that Known Folder Move is on for this account: **Downloads lives inside OneDrive**
and a bare `~/Downloads` does not exist. That matters for the Safari/iOS fallback, whose
whole path is a browser download.

## Day to day

1. On the floor: log encounters in Tracker Lite as they happen.
2. When you're done: **Records → → Send to Builder**. It sends what's **on screen**, so
   filter first if you don't want everything.
3. At the PC: `python encounter_builder.py` → **📥 From Tracker Lite**. Each capture
   arrives as its own group of one, so you can review and delete them individually.
4. Finish anything incomplete, add roster sweeps as usual, **Write & enter batch**.

After a successful import the capture file is **renamed** to
`tracker_capture.imported.<timestamp>.json`, so the same encounters can't be pulled in
twice. Renamed rather than deleted — if an import turns out wrong, the file is still
there.

## Checking it without the GUI

```bash
python tracker_import.py            # report what would be imported; changes nothing
python tracker_import.py <path>     # point it at a specific file
python test_tracker_import.py       # 12 tests, fake data
```

The report is redacted: `Employee #1`, description lengths. It tells you which capture
failed and why, never who.

## PHI

`tracker_capture.json` holds real names and clinical descriptions. It is gitignored here
(along with the `.imported.*` archives), and Tracker Lite gitignores its own exports.
Don't move one into either repo.

## If you change the format

The schema string `emr-tracker-lite/capture@1` appears in exactly two places:

- `tracker_import.py` → `SCHEMA`
- Tracker Lite `src/lib/builderExport.js` → `CAPTURE_SCHEMA`

Change one and you must change the other. A mismatch is reported as a warning and the
file is still read, so it degrades loudly rather than silently.
