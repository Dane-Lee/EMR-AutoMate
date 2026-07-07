# EMR AutoMate — Work Log

A running history of what we've worked on, session by session. Newest entries at
the top. This is our "saved chat" record — each session I append what changed,
what decisions we made, and where we left off. See `TODO.md` for the forward list.

---

## Sessions 6–13 — 2026-06-26 → 07-06 (Roster-update feature, field-mapping engine, mobile bridge, 3 encounter batches)

Big stretch; grouped by theme rather than day.

### Encounter batches drafted (dictation → CSV → EMR drafts)
- **6/30 (40)**, **7/1 (97)**, **7/2 (66)** coaching encounters drafted via `encounters.csv`.
  Flow: Dane dictates → a cleanup pass structures it (`DICTATION_PROMPT.md`) → I build the
  validated `encounters.csv` → `emr_automate.py` → **Coaching Encounters** drafts each ("Save
  in progress").
- **Dept/Division/Category/Shift enrichment:** captured the EMR's real dropdown options
  (`ati_coaching_encounter.py --capture-fields` → `emr_field_options.json`; Dept 49 / Div 8 /
  Category / Shift) and built **`emr_field_map.py`** — a reusable *area-text → Department*
  resolver + Dane-confirmed *Department → Division* map (+ station-number ranges, and a
  work-title fallback for when no area is captured). Category = "Full Time/Part Time"; Shift
  from the roster.
- **Tolerant name matching** (`name_pattern`): the EMR stores names inconsistently —
  `Doe , Jane` (space before comma), `Roe, John` (missing "Jr."), `Van Dam, Kay`
  (compound last name), `Poe, William "Will"` (nickname). Matcher is now whitespace/comma
  tolerant + substring; we correct to the EMR's stored form and re-run only failed rows.

### Employee Roster Update feature (`update_employees.py`, launched via "Update Roster")
- Matches each roster row to an EMR employee (**Identifier then Name**, via the UUID embedded
  in dashboard rows), drives `/editemployee?id=<UUID>`, sets Identifier (`ID-Title-Shift`) +
  Date of Hire, auto-applies. `--from-hc` converts the HC Reporting export → `roster.xlsx`.
- Extras: `--nicknames` report, gender auto-default (blank→Male + flag), EMR-not-in-roster
  report, identifier length-cap infra (`MAX_IDENTIFIER_LEN`).
- **First full run (246) failed midway:** EMR **session timed out ~1 hr in** → every later
  `editemployee` load hit the login screen (140 failed). FIXED with `open_edit_form()` session
  guard (detects login → prompts re-login → retries). Date picker was also only ~35% reliable
  (two `ati-datepicker`s; unscoped selector grabbed the hidden one) → FIXED by scoping to
  `.rc-calendar:visible` + retry. Redo on the new 262 roster running as of 7/6.

### Launcher dialog
- `emr_automate.py` popup: relabeled buttons (Coaching Encounters / Update Roster). tkinter
  rendered **blank** on Dane's machine → switched to a native Windows **Task Dialog**
  (`comctl32.TaskDialogIndirect`). Lesson: don't launch interactive GUI runs from a background
  shell — it can't reach Dane's desktop.

### Mobile-capture pivot (interim bridge)
- Decided to move encounter intake from dictation → the **mobile-encounter-companion** app
  (the PLAN.md integration direction; dictation stays fallback). Built **`mobile_import.py`**
  (`--from-mobile`): mobile JSON export → `encounters.csv` (only `ready_for_export` records;
  real Navarre areas resolve via `emr_field_map`; reads a `shift` field once the app adds it).

### Data / housekeeping
- `EMR Easy Enter Worksheets.xlsx` (Dane's standard-description library) got overwritten with
  roster data → recovered (14 tabs) from OneDrive version history.
- New authoritative roster **`Active Associates - Navarre  7-2-26.xlsx`** (262 people, with a
  **Nickname column** — resolves identities, e.g. a formal first name to its nickname).
- **Project relocated 2026-07-06** to `C:\Users\dane.lee\Alternate Desktop\Dane - Coding
  Projects\EMR AutoMate` (+ `…\Dane - ATI Stuff`). This is now the live git repo (the old
  OneDrive copy's `.git` is broken).

### Open / next
- Finish + analyze the 262 roster redo; handle unmatched employees; check the ~8 long
  identifiers (>40 chars) for server-side truncation → set `MAX_IDENTIFIER_LEN` if needed.
- **Nickname re-split:** saving an edit makes the EMR strip `First "Nick"` out of the
  searchable First Name box (search ignores the Nickname box). Needs a quick live test (does
  re-entering survive a save?); the roster nickname column would then let the tool set First
  Name = `Formal "Nick"` automatically.
- Mobile: a real export to confirm areas resolve end-to-end; then live mobile → ETS → AutoMate
  (Phase 1 in PLAN.md).

---

## Session 5 — 2026-06-23 (Live test #2 — employee lookup fixed)

- Persistent profile worked: browser opened straight to **Hendrickson / Navarre**
  (correct org, no Lancaster).
- Ran the 1-row `encounters.csv` (Sample Employee). Stopped again at employee
  selection — search showed "No Employee Found" even though she exists exactly as
  `Sample, Employee`.
- **Root cause found:** the dashboard preloads the **entire roster (938 rows)** into
  `.employee-list` at load; the search box is just a client-side filter whose
  matching does NOT handle the "Last, First" comma format. That's why every search
  came back empty.
- **Fix:** stopped using the search. Now locate the employee row directly by name
  in the preloaded list (`.employee-list .details` filtered by full name),
  scroll into view, and click. Search box kept only as a fallback to narrow the
  list. Renamed capture `02_search_results` → `02_employee_list`.
- Next run should finally get PAST employee selection into Add Case → Step 1 →
  Step 2, which we'll see in the new captures (`03_employee_selected` onward).

**Live test #3 (1:44 PM):** Got through employee select → clicked **+ Add Case** →
captured the **"Select Assessment Type"** modal (8 tiles: Task/Office Ergo/Work
Readiness/Physical/Health & Wellbeing/Outside Care Referral/**Coaching Encounter**/
Human Movement). Timed out 30s in the modal.
- **Cause:** two buttons match "Add Case" — the background `+ Add Case`
  (`next-btn`) and the modal's confirm `Add Case` (`btn btn-primary disabled` until
  a tile is picked). `.first` grabbed the background one behind the overlay → click
  blocked → timeout. Also tiles are `.assessment-type-container` divs.
- **Fix:** click the `.assessment-type-container` tile by text; confirm with
  `get_by_role("button", name="Add Case", exact=True)` to avoid the `+ Add Case`.
- Next unknowns: Step 1 form (date, encounter-type radio, the 4 react-select
  dropdowns dept/div/category/shift).

**Live test #4 (1:48 PM):** Reached **Step 1 (Encounter Details)** but it loaded
behind a spinner and our selectors were wrong. From the captures:
- Date is a **custom calendar popup** (text input + Cancel/**Apply**), not a plain
  field — `fill()` didn't register.
- Encounter type is **tiles with a HIDDEN radio**: `<input name='encounteredType'
  value='In Person'>` wrapped by `<label for='In Person' class='segment-select'>`.
  `.check()` on the hidden input timed out.
- Dropdowns are **`ati-react-select`** tied to field **labels** (Department/
  Division/Category/Shift), with auto-generated ids `react-select-3/4/...` (NOT the
  8/9/10/11 we hard-coded). Placeholder shows "Select Category" for several.
- **Fixes:** `fill_date` now types + clicks Apply; `click_radio` clicks
  `label.segment-select[for=VALUE]`; **`react_select` rewritten to target by field
  LABEL** (kills the fragile-id problem) with a `required` flag + 6s timeouts so
  optional dropdowns don't hang. Added a 20s wait for the form to load past the
  spinner, a `05b_step1_filled` capture, and a text-based Next button. Step 2
  coaching-type/what-prompted labels are GUESSED ("Coaching Type" / "What Prompted
  Coaching") — `06_step2_form` capture will confirm/correct them.

---

## Session 10 — 2026-06-24 (Repos confirmed current; ready to build)

- Pulled latest for all three repos. **ETS** (`ef3c91a`, today — "Add worksite
  taxonomy, desktop capture feed, and UI/sync improvements") and **mobile companion**
  (`9c37fff`, today — "Remove tags, add sync status indicator and desktop import
  store") fast-forwarded clean. **HMA-app** had a rewritten history (force-push) →
  hard-reset to origin/main (`0bc05e9` "Add manual scoring workflow", May 13); now a
  real app (api/web/config/docs/Docker + manual scoring + HMA scoring-sheet PDFs).
  Dane confirmed May 13 is HMA-app's latest (untouched ~1 month). All three 0 behind.
- ⚠ The new commit messages are directly relevant to our gaps: ETS adds a **"desktop
  capture feed"**, mobile adds a **"desktop import store"** — these may already
  address parts of auto-conversion / the API feed. RE-READ the current code before
  building (yesterday's notes were against the pre-update source).
- Source-currency risk is cleared. Next: begin building per PLAN.md / TODO.md.

**Reconciliation of the new commits (re-read 2026-06-24):** the "desktop capture
feed" + "desktop import store" are **prioritization plumbing**, NOT our pipeline —
a Desktop→Mobile feed (`GET /sync/desktop_capture_feed` via `desktop_capture_feed.ts`)
that tells the phone who's already handled / open follow-ups, to improve floor
prioritization. New worksite taxonomy = departments→locations→stations (station-based
prioritization). Mobile also REMOVED `tags` from captures.
- Verified `POST /sync/mobile_capture_entries` STILL only inserts `pending_review` —
  **auto-conversion NOT added.** AutoMate read / mapping / gap-fixes all still unbuilt.
- So the plan is unchanged. Worksite taxonomy may later help seed the EMR Department
  dropdown + roster (Gap A); Division/Category/Shift still not first-class in ETS.
- **Recommended first build:** Phase 1 thin slice on the AUTOMATE side — read a
  coaching encounter from ETS `GET /encounters`, map, draft into EMR, mark drafted.
  Lowest risk (touches AutoMate, ETS read-only). Pending Dane's go + a read of the
  `/encounters` route + auth.

---

## Session 9 — 2026-06-23 (Direction shift: integrate with the capture apps)

**Context:** With the core EMR-drafting working, Dane wanted a more seamless entry
system than dictating into VS Code. Discovered he already built TWO relevant repos:
- **mobile-encounter-companion** — React/Vite PWA, phone capture (IndexedDB,
  local-first, voice-capable), uploads `mobile_capture_entry` records to ETS.
- **encounter-tracking-system (ETS)** — full app (React/TS + Express/TS + SQLite),
  REST API `localhost:3001` token auth, stores encounters + personnel + description
  templates + mobile-sync intake. (See [[project-encounter-tracking]] in memory.)
- NOTE: these are SEPARATE from the HMA exercise tracker repo — I initially looked
  in the wrong repo; the encounter system is `Dane-Lee/encounter-tracking-system`
  and the mobile app is `Dane-Lee/mobile-encounter-companion`.

**Key realization:** Dane already captures encounters in these tools. The seamless
path is for EMR AutoMate to READ from that pipeline and draft into the EMR, instead
of dictation/CSV. The 11 tracker/mobile coaching types map ~1:1 to the EMR coaching
types (labels differ across all three systems → mapping layer needed). Assessment
types are separate EMR case types, out of scope.

**Decision:** Dane wants to integrate via the **mobile companion** as the capture
surface. Hard constraint: Playwright must run on the PC (EMR session lives there),
so phone captures → existing sync → ETS → EMR AutoMate (PC) drafts → review/finalize.

**Saved `PLAN.md`** (checkpoint; expected to change). **No build started** — planning only.

**Decisions/findings this session:**
- **AutoMate reads from ETS via the REST API** (not SQLite) — ETS is running anyway,
  the API gives a stable contract + filtering/joins + safe write-back to mark
  encounters drafted (avoid double-drafting).
- Traced the real flow: mobile sync is **manual** (tap upload, `ready_for_export`
  only); ETS only **inserts** uploads into `mobile_capture_entries` as
  `pending_review` — **no auto-conversion** to a real encounter; nothing triggers
  AutoMate. So today only the EMR-drafting link is proven; the rest is unbuilt.
- Brainstormed fixes for the 4 end-state gaps (employee-name reconciliation,
  assessments not covered, failure handling, trigger timing) with picks — saved in
  PLAN.md "Gap fixes" section. Synergy noted: ETS + AutoMate on the same PC, so ETS
  can be both the API source and the trigger.
- Added tasks: confirm sync works, fix auto-conversion, ensure capture reliability,
  use the API.
- **Gap-fix decisions:** A (employee names: roster dropdown + normalize + alias
  table; badge/ID later — caveat: not all employees have an EMR ID yet), C (failure
  handling: all four), D (trigger: queue + "Push to EMR" button in ETS, Task
  Scheduler later) — all DECIDED.
- **Assessments DECIDED:** AutoMate just **starts** the assessment and Saves in
  progress with only the shared first ("Encounter Details") screen filled; Dane
  finishes the rest manually. Generalizes the existing engine (pick tile → fill
  Step 1 → save). Coaching = Step 1+2; assessments = Step 1 only. VERIFY first-screen
  parity when building (fills are best-effort, so low risk).
- **Parked (future):** HMA score double-entry — AutoMate enters HMA scores into the
  EMR AND the HMA Corrective Exercise Tracker in one shot (→ EMR record + auto
  corrective-exercise plan). Bigger separate build; needs a richer HMA-score capture
  (the `Dane-Lee/HMA-app` repo — currently only a stub on GitHub; Dane has a more
  fleshed-out local version not yet pushed).

**⚠ Before any code changes to the mobile companion / ETS:** the local clones on
this PC are GitHub's version and may be BEHIND Dane's unpushed work on his personal
computer (the HMA-app showing only a README proved this risk). Verify/pull current
source first — do NOT edit stale code.

**NEXT SESSION (planned for the day after 2026-06-23):** Dane checks all repos
tonight + pushes latest. Tomorrow: confirm the clones are current, then START
BUILDING per PLAN.md / TODO.md. Capability confirmed (repos cloned locally, tooling
available); waiting on (a) current source + (b) Dane's explicit go.

---

## Session 8 — 2026-06-23 (🎯 FULL END-TO-END WORKING)

**Milestone:** a complete, accurate draft was created start to finish from the CSV.
Sample's run filled EVERYTHING correctly: date (Jun 23 2026), In Person, all 4
dropdowns (Sample Dept / Weld / Full Time-Part Time / 1st), CoachingType =
Health/Wellness Coaching, detail **Other** ticked, description, What Prompted =
Specialist initiated → "Save in progress" draft in InProgress. No errors, no manual
fields. The detail-checkbox label-click fix worked.

**The pipeline now works:** dictate → Claude writes `encounters.csv` → run → robot
finds the employee, opens a Coaching Encounter, fills Step 1 + Step 2 (incl. detail
checkboxes), and drafts via Save in progress for Dane to review/finalize.

**Next:** test a real multi-row BATCH (the actual efficiency goal); test other
coaching types / multiple details; double-click launcher; cleanup (delete test
drafts, eventually turn off DEBUG_CAPTURE). Detail checkboxes for OTHER coaching
types use identical markup, so they should work, but worth a spot-check.

---

## Session 7 — 2026-06-23 (Full flow reached; Step 2 + popups)

- Add Case resilience fix worked (settle wait + force-click fallback) and the date
  fix worked — Step 1 now fills 100% (date "Jun 23 2026", In Person, all 4
  dropdowns). Reached the REAL Step 2 ("Coaching Assessment / Coaching Details").
- Step 2 from the `06`/`07` captures:
  - **Description of Coaching** — filled (`textarea[name='description']` works).
  - **What Prompted Coaching** — filled ("Specialist initiated"; case-insensitive
    match handled the capital-I value).
  - **CoachingType** — was EMPTY: the field label is the one-word "CoachingType",
    not "Coaching Type". **Fixed** the react_select label. Same `ati-react-select`
    structure as the others.
- Added **native popup prompts** (`popup()` via MessageBoxW): login gate, batch
  confirm, do-another, continue-on-error — no more PowerShell back-and-forth
  (Dane's request).
- After the CoachingType fix, a no-details encounter (like Sample's
  Health/Wellness) should draft fully. STILL UNTESTED: detail checkboxes for
  coaching types that have them (their markup not yet captured — likely hidden
  inputs needing label clicks, like the encounter-type radios were).

**Update — CoachingType fix worked + detail checkboxes solved:** Sample's run
filled CoachingType/description/what-prompted, but no detail was selected because
the transcription left details blank. Dane clarified: a **PHD check-in maps to
detail "Other"** under Health/Wellness. Codified that (+ a general "use Other when
nothing specific fits" rule) in the CSV, TRANSCRIPTION_PROMPT.md, and the
[[feedback-emr-defaults]] memory. The detail-checkbox markup (now captured) is
`<label class="custom-checkbox"><input name="coachingDetailTypes" value="<uuid>"
hidden>...` — our UUID map is correct, but the input is hidden, so **`tick_checkbox`
now clicks the wrapping `label.custom-checkbox`** instead of `.check()`. Next run
tests the "Other" tick → should be a 100% complete draft.

---

## Session 6 — 2026-06-23 (Live test #5 — Step 1 working; draft mode added)

- Added **draft mode** (`SAVE_MODE="draft"`): robot clicks "Save in progress"
  (drafts only, never finalizes); Dane reviews/finalizes in the EMR's InProgress
  list. Dane's idea. Confirmed: partial saves allowed; drafts easy to find
  (InProgress nav, under Overview/Case List); finalize is reasonably quick.
- Made Step 2 fills best-effort (non-blocking) since partial drafts are fine.
- **Live test #5:** reached Step 1 and filled it ALMOST completely —
  **In Person + all 4 dropdowns (Sample Dept / Weld / Full Time-Part Time / 1st)
  worked** (label-based `react_select` is solid). But the **Date didn't fill** —
  it's an **rc-calendar** popup that ignores typed input, so Next was blocked by
  the required-date validation ("Please choose Date of Encounter") and we never
  actually advanced to Step 2 (06/07 captures were still Step 1).
- **Date fix:** `fill_date` now opens the calendar, navigates months relative to
  today (`rc-calendar-next/prev-month-btn`), and clicks the day cell by its title
  (`td[role=gridcell][title='June 23, 2026']`), then Apply. Verified title format.
- Next run should pass the date, advance to the REAL Step 2, and draft a more
  complete Sample Employee — and finally capture genuine Step 2 markup to fix the
  coaching-type / details / description / what-prompted selectors.

---

## Session 4 — 2026-06-23 (CSV batch pipeline)

**Goal:** Address the "changed the work but not the efficiency" problem. Decided
the real leverage is batch entry from an AI-transcribed CSV, not one-at-a-time
typing.

**Workflow we're building (Dane's idea, refined):**
`handwritten notes → dictate to Claude → Claude writes encounters.csv → script
reads it → fills each form, pauses for per-row review → approve/skip/quit`.
Using Claude as the transcriber (Dane's work account is Claude, not OpenAI).
Mobile-capture app he already built can target the same CSV later.

**Done this session:**
- Added **CSV batch mode** to the script:
  - `load_encounters_csv` / `row_to_encounter` parse `encounters.csv` and
    **validate every row** against the exact EMR values (encounter type, coaching
    type, per-type detail labels, what-prompted), with clear row-numbered errors.
    Browser won't open if the CSV is invalid.
  - `prepare_batch` shows a summary and asks to confirm before entering.
  - `run_batch` enters each row; `run_interactive` keeps the old one-at-a-time
    loop. Mode auto-selected by whether `encounters.csv` exists.
  - SAVE/review now returns `saved`/`skipped`/`quit` so each row can be approved,
    skipped, or the batch stopped. Added `_do_save` helper.
- CSV format: columns `employee,date,encounter_type,department,division,category,
  shift,coaching_type,details,description,what_prompted`. `details` is
  semicolon-separated; `employee` is "Last, First" (quoted).
- Wrote **TRANSCRIPTION_PROMPT.md** (the reusable spec/prompt encoding all allowed
  values) and **encounters_template.csv** (example rows).
- **Tested the data layer** (no browser): valid file → 2 parsed, 0 errors, blank
  date defaults to today; broken file → all 5 errors caught correctly. Script
  still compiles cleanly.

**Dictation test (good news + a discovery):** Dane dictated an encounter verbally
(voice-to-text). The transcription mapped cleanly to nearly all fields — the
dictation pipeline works. BUT the example turned out to be a **Physical Assessment
follow-up**, which is a **separate EMR case type, not a Coaching Encounter** — the
tool can't enter it. Logged as a scope item (see TODO "🔵 Scope"). Need to learn
the Physical Assessment form later and possibly map Dane's full case-type mix.

**Where we left off / next:**
- Still owe the live browser verification: Add Case → Step 1 → Step 2 → Save are
  UNVERIFIED. Need a real *Coaching Encounter* (not a Physical Assessment) to test.
  Plan unchanged: dictate one → Claude writes 1-row `encounters.csv` → Dane runs it.

---

## Session 3 — 2026-06-23 (Live test #1)

**Goal:** First live run against the real EMR; fix selectors from real captures.

**What happened:**
- Added debug instrumentation (`DEBUG_CAPTURE`, `snap()`): saves a screenshot +
  page HTML at each step into `./debug`. These captures are on Dane's machine, so
  they can be read directly to fix selectors against the real page.
- First run reached the dashboard and the employee search, then stopped.
- **Confirmed working:** login, dashboard load, and the search-box selector
  `input[placeholder='Search Employee or Identifier']` (it received the typed name).
- **Bug found + fixed:** results container is `.employee-list` (we had
  `.assigned-employee-list`). Real result rows are `.employee-list .details`, each
  with `.info > span.name` (e.g. "Coburn, William"). Updated the click selector to
  `.employee-list > div:not(.empty-result)` and added an explicit "No employee
  found" error (checks `.employee-list .empty-result`).
- **Real blocker:** the run landed in the **"AWS Employee Training – Lancaster"**
  org (a default/sandbox), and the example name "Example, Name" didn't exist there,
  so the search returned `No Employee Found`. Dane does not work at Lancaster and
  does not want to test against it.

**Resolution of the org issue:** Dane's real worksite is **Navarre**. The Lancaster
default happened only because Playwright launched a fresh, empty browser profile
(no cache) — his normal Edge remembers Navarre. Fixed by switching the script to a
**persistent profile** (`launch_persistent_context` with `.browser_profile/`), so
login + the Navarre selection persist across runs like a normal browser. Also
removed the separate `browser` object (persistent context closes directly).

**Where we left off / next:**
- Re-run: first time, log in + confirm Navarre once; afterwards it opens straight
  to Navarre. Then test with a real Navarre employee to finally exercise Add Case →
  Step 1 → Step 2 → Save (all still unverified).

---

## Session 2 — 2026-06-23

**Goal:** Run one encounter at a time; install the tooling needed to run it.

**Done this session:**
- Confirmed the project premise: Playwright automation that fills Coaching
  Encounter forms in the ATI Worksite Solutions EMR so encounters don't have to
  be entered by hand.
- Decided on **terminal Q&A** as the input style (vs. a pop-up form window).
- Rewrote `ati_coaching_encounter.py`:
  - Removed the hard-coded `ENCOUNTER` config block.
  - Added interactive prompts (`prompt_encounter`, plus `ask_text` / `ask_choice`
    / `ask_multi` helpers) that collect one encounter's data per run, with a
    review summary and an option to re-enter.
  - The coaching-detail menu auto-adjusts to only the checkboxes valid for the
    chosen coaching type.
  - Split `run()` into a one-time login plus a per-encounter `fill_encounter()`,
    wrapped in a loop with a **"Do another encounter? (y/N)"** prompt — log in
    once, enter many encounters; an error on one doesn't crash the rest.
- Installed tooling on this machine:
  - Python 3.12.10 → `C:\Users\dane.lee\AppData\Local\Programs\Python\Python312\python.exe`
  - `playwright` 1.60.0 + Chromium browser.
  - Confirmed the script compiles cleanly (`py_compile`).
- Created `TODO.md` and this `WORKLOG.md`.

**Key facts / gotchas:**
- `python` is not reliably on PATH (Windows Store stub shadows it). Use the full
  interpreter path above, or a fresh terminal.
- The script has **NOT yet been run against the live EMR** — selectors are
  unverified. That live test is the #1 next step.

**Where we left off / next:**
- Top of `TODO.md`: do a live REVIEW-mode test run and fix whatever selectors
  don't match the real form.

---

## Session 1 — 2026-06-22

- Located `ati_coaching_encounter.py` in Downloads and moved it into the project
  folder: `...\Desktop\Dane - Coding Projects\EMR AutoMate`.
- Reviewed the original script: hard-coded `ENCOUNTER` dict, Playwright flow
  (manual login → find employee → Add Case → fill Step 1 & 2 → pause before Save),
  and the captured coaching-type / checkbox UUID maps.
