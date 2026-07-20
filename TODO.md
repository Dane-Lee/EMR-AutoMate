# EMR AutoMate — To-Do List

Living checklist for the ATI coaching-encounter automation. Check items off as we
finish them. Newest priorities at the top of each section.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

> **Status 2026-07-20:** Copilot dictation intake **REMOVED** — replaced by
> **`encounter_builder.py`** (check names off the roster; no AI anywhere in the
> pipeline). Per-person Department/Division now come from the roster (Dane hand-set all
> 261). Entry engine hardened (session guard + `--resume`). Full builder **UI overhaul**
> (flat modern theme, work-area filter, card-based description library, `--demo` mode).
> Three production bugs fixed (window size / preflight name-read / description-library
> join — see `WORKLOG.md`). **IN PROGRESS: the add-employee feature** (below). After
> that: physical & follow-up assessments. Full narrative in `WORKLOG.md`.
>
> ⚠️ Sections further down that mention M365 Copilot, dictation, `TRANSCRIPTION_PROMPT.md`
> or "pivot to mobile" are **historical** — superseded by the local builder above.

---

## 🔨 IN PROGRESS — Add-employee grouping (attach a group to ONE encounter)

The EMR lets you add extra employees to an encounter before saving; it creates **one
shared record** covering all of them, and **finalizing that one encounter finalizes it
for everyone attached** (confirmed by Dane 2026-07-20). Dane's manual finishing per
draft is just "check the description + hit save", so collapsing a group of N into one
shared encounter turns a ~91-draft day into a handful — and the automation fills far
fewer forms, so timeouts stop mattering.

- [x] **Design locked (2026-07-20):** group `encounters.csv` rows that are identical
      except `employee` → one EMR encounter with all attached. **No CSV change** — the
      builder's groups already emit identical rows per person. Cross-department groups
      split naturally into one encounter per area (rows differ), nothing lost.
- [x] **Control located:** already in our step-2 capture —
      `<div class="add-more">` in the `employee-info-container` header.
- [x] **Capture tool built:** `python ati_coaching_encounter.py --capture-addmore "Last, First"`
      drives to a Coaching Encounter form, clicks `.add-more`, snaps
      `debug/ADDMORE_00_form|01_opened|02_after_add.html` (scrubbed), pausing for Dane to
      add one employee by hand. **Never saves.**
- [ ] **NEXT — Dane runs `--capture-addmore`**, then Claude reads the ADDMORE captures to
      learn what clicking add-more opens and how an attached employee is stored in the DOM.
- [ ] **Wire it:** group rows in `run_batch`; fill one encounter (`fill_encounter`), click
      add-more, add the rest (reuse `locate_employee`), one `Save in progress` per group.
      Update the audit log to record per-group.
- [ ] **Open question (non-blocking):** does an added employee take the encounter's
      Department/Division, or keep their own? Determines whether we can merge across areas.
- [ ] **Prove on ONE small group as a draft** before any real batch.

## 🔜 NEXT FEATURE — Physical & Follow-Up Assessments (requested 2026-07-20)

A **separate EMR case type** — other tiles in the "Select Assessment Type" modal, not
Coaching Encounter, so the current tool can't enter them yet. Same pattern as everything
else here.
- [ ] Capture the Physical Assessment + Follow-Up forms (like `--capture-fields` /
      the add-case flow).
- [ ] Map the fields; decide **"start + first screen only"** vs full fill (see PLAN.md
      Gap B — the first-screen approach was the earlier plan for assessments).
- [ ] Wire + prove on one draft.

---

## 📌 Historical (pre-2026-07-16) — superseded by the builder above

> Kept for context. The dictation/Copilot/mobile items below reflect the OLD flow.

## 📌 Today (2026-07-01)

- [x] **Dept/Division/Category/Shift mapping built (2026-07-01).** Captured the EMR
      option lists (`--capture-fields` → `emr_field_options.json`: Dept 49 / Div 8 /
      Category / Shift). Built `emr_field_map.py`: area-text → Department resolver +
      Dane-confirmed Department→Division correlation; Category = "Full Time/Part Time";
      Shift from the HC roster. Enriched all 40 of 6/30 → validated (0 errors, every
      value is a real EMR option). Reusable for the mobile-JSON path too.
      TODO: verify the `(?)`-inferred Department→Division rows in `emr_field_map.py` as
      new areas come up; "Team Lead" isn't an option (used "Line Lead").
- [ ] **Redo the roster run (not now — later today).** `roster.xlsx` is filtered to the
      207 not-done rows; re-run with a FRESH login. Session guard + date-picker fix are
      in. Details in "Employee Roster Update" below. Regenerate full 246 via `--from-hc`.
- [ ] **Draft the 40 coaching encounters for 6/30.** `encounters.csv` is built + passes
      the validator (40 rows, 0 errors). Run `emr_automate.py` → **Coaching Encounters**.
      One assessment (Wyler, Sandra follow-up) is manual. NOTE: descriptions were
      composed in Dane's EIS/EE voice because the Easy Enter file was unreadable — swap
      to verbatim templates once it's recovered. New descriptions logged to
      `new_descriptions_for_library.csv`.
- [ ] **Recover `EMR Easy Enter Worksheets.xlsx`.** It was overwritten with roster data
      (~6/30 2:57 PM) — the 14 template tabs are gone from the local copy. Restore the
      good version via OneDrive **Version history** (or OneDrive recycle bin). Then align
      the 6/30 encounter descriptions to the verbatim templates.
- [ ] **Pivot encounter intake: Claude dictation → Mobile Encounter capture system.**
      Decided 2026-07-01: use the existing **mobile-encounter-companion → ETS** pipeline
      as the real input instead of dictation/CSV (which drops to fallback). This IS the
      documented integration direction — see "Next up — INTEGRATION DIRECTION" below +
      PLAN.md. Known prereqs (already listed there): verify mobile→ETS sync works E2E;
      decide how `mobile_capture_entries` become real encounters (auto-convert vs import);
      build the label-mapping layer + name reconciliation; do the Phase-1 thin slice.
- [ ] **FUTURE capture UX (ETS + Mobile Encounter Companion) — requested 2026-07-01:**
      - **Employee -> location correlation table:** default each employee to their
        most-likely Department/Division (learned from past encounters), correctable
        inline. (The 6/30->7/1 "reuse prior entry" logic + `emr_field_map.py` are the
        seed of this — formalize as a per-employee, self-updating table.)
      - **Cascading auto-fill:** Department -> likely locations (from past encounters)
        -> likely stations (from the chosen location + past encounters).
      - **"Add other employees":** after capturing one encounter, offer (non-nagging) to
        duplicate it for additional employees just by typing their names — auto-recreates
        the identical encounter for each.

---

## ✅ Core flow — DONE (verified end-to-end against live EMR, 2026-06-23)

- [x] **Live end-to-end test run.** A complete, accurate sample draft was created
      from the CSV: date, In Person, all 4 dropdowns, CoachingType, detail "Other",
      description, what-prompted → Save in progress. No errors, no manual fields.
- [x] **Correct org/worksite (Navarre).** Persistent profile opens straight to
      Hendrickson/Navarre.
- [x] **Add Case → Coaching Encounter flow.** Real "Select Assessment Type" modal;
      click the tile + exact-name "Add Case" button. Hardened with settle wait +
      force-click fallback for the re-rendering Employee Overview.
- [x] **All form fields wired to real markup:** employee (direct locate in the
      preloaded roster), date (rc-calendar day-cell + Apply), encounter type
      (hidden-radio → click `label.segment-select`), dropdowns (label-based
      `ati-react-select`), CoachingType (one-word label), detail checkboxes
      (hidden input → click `label.custom-checkbox`), description, what-prompted.
- [x] **Save = draft** ("Save in progress"); never finalizes.

## 🆕 Employee Roster Update (NEW function — added 2026-06-26)

Update employee FILE INFO (Name, Identifier, Date of Hire, Email, etc.) in the EMR
from an Excel roster. Reached via the `emr_automate.py` launcher popup (Yes =
encounters, No = update employees). Plan: `inherited-launching-mitten.md`.
Spec: `ROSTER_UPDATE_PROMPT.md`. Decisions: .xlsx source · match Identifier-then-Name ·
update-existing-only · auto-apply with up-front confirm + audit log.

- [x] `update_employees.py` — roster reader (openpyxl), Identifier→Name matcher,
      edit flow, orchestration, audit log; `emr_automate.py` launcher; spec doc +
      `roster_template.xlsx`. *(2026-06-26)*
- [x] **Offline-verified:** reader (int/datetime/blank cells + validation) and matcher
      against the saved 938-row dashboard capture — 16/16 checks pass. *(2026-06-26)*
- [x] **STEP 0 — captured the `/editemployee` form** (a test employee, 2026-06-26) and wired
      VERIFIED selectors into `EDIT_FIELD_SPECS`: firstName/middleName/lastName/
      nickName, badgeNumber (Identifier = "number - title"), contactEmail, 3-part phone
      (area/exchange/subs) + contactExt, Gender react-select, Date of Hire / Date of
      Birth pickers, and the `.save-button` div (SAVE is a div, not a `<button>`).
      Medical-history/screening section + read-only Location intentionally NOT wired.
- [x] **Field set decided (2026-06-29):** Name (first/middle/last) + Identifier + Date
      of Hire. NOT edited: Gender, Date of Birth, Phone, Email, Nickname box, medical
      section. `roster_template.xlsx` trimmed to: identifier, name, first_name,
      middle_name, last_name, new_identifier, date_of_hire.
- [x] **Nickname handling:** nicknames go in First Name as `First "Nick"` (the EMR only
      searches first/last boxes). Built `--nicknames` report → `nickname_candidates.csv`
      (live roster preview: 223 candidates, 40 already done).
- [x] **Gender auto-default:** not edited, but blanks default to "Male" + flagged to
      `gender_review_needed.csv` so Save (required field) doesn't fail.
- [x] **Identifier format decided (2026-06-30):** `ID-Title-Shift`, e.g.
      `12345-Technician II-2nd` (no spaces around joining dashes; suffixed IDs like
      `11111-01` preserved). `new_identifier` column now active.
- [x] **HC roster importer built** (`--from-hc <xlsx>`): maps Associate ID/Name/Shift/
      Primary Position/Hire Date → `roster.xlsx` (identifier, name as "Last, First",
      new_identifier, date_of_hire). Ran on Dane's file → 246 rows, 0 errors; 242/246
      matched vs the 2026-06-23 snapshot (live will be fresher). Fixed `parse_badge_
      identifier` to keep ID suffixes.
- [ ] **Handle the ambiguous match** (a name with 2 records in the EMR) — correctly
      skipped+flagged. Dane disambiguates manually (or add an `identifier` that's
      already in EMR). A few recent hires were absent from the old snapshot —
      recheck on the live run.
- [x] **EMR-not-in-roster report (2026-06-30):** `run()` writes `emr_not_in_roster.csv`
      (EMR employees no roster row matched) at the end of a run, per Dane's request.
- [x] **Identifier length-cap infra (2026-06-30):** `MAX_IDENTIFIER_LEN` (None until the
      server cap is known) → importer shortens the TITLE part (keeps ID+shift) to fit
      and logs each change to `identifier_shortened.csv`. Lengths run 16–58 chars
      (median 21); ~8 are >40 (e.g. EHS Rep III = 58).
- [x] **Live single-employee test PASSED (2026-06-30):** a test employee — identifier AND
      Date of Hire both set + saved; Gender untouched; verified in log + screenshot.
- [x] **Date of Hire picker SOLVED:** the field rejects typing — it's an rc-calendar
      (wrapped in `ati-calender-container`). `_set_date` now opens it, navigates by
      year/month buttons, clicks the day cell by title ("January 5, 2026"), clicks
      Apply, and **Cancels on failure so it never wipes** an existing date. Added
      `--capture-date` mode used to capture the open calendar.
- [ ] **Confirm Gender option label** is `Male` — not yet exercised (the employee already had a
      gender set); will trigger only for a blank-gender employee.
- [ ] **⚠ KNOWN ISSUE (2026-06-30): EMR strips quoted nicknames on save.** When a record
      is saved, the EMR moves a `First "Nick"` (e.g. `James "Jim"`) out of First Name into
      the Nickname box — which search ignores, breaking find-by-nickname. Our tool does
      NOT touch the name fields (only Identifier + Date of Hire), so this is EMR save
      behavior affecting any nickname employee whose record we save. PAUSED the run.
      NEED a manual test: re-enter `First "Nick"`, clear Nickname, save, reopen — does it
      stick or re-split? If sticks → tool recombines nickname into First Name per record
      (also repairs already-changed ones). If re-splits → skip nickname employees in the
      auto-run; real fix = get ATI to include the Nickname box in search.
- [x] **First full run (2026-06-30) — diagnosed + fixed.** Result: 35 fully done, 66
      identifier-only (date failed), 140 untouched, ~5 unmatched. NO data wiped. Two
      root causes found + fixed:
      1. **Session timeout ~1hr in (14:27):** every later `editemployee` load hit the
         login screen (confirmed by EMP_edit_241 screenshot) → all 140 failed silently.
         FIX: `open_edit_form()` session guard — detects the login screen, prompts
         re-login, retries.
      2. **Date picker only ~35% reliable:** page has TWO ati-datepickers, each with an
         `.rc-calendar`; unscoped selector grabbed the wrong/hidden one. FIX: scope to
         `.rc-calendar:visible` + retry once.
- [ ] **Redo run:** `roster.xlsx` filtered to the 207 not-done rows. Re-run with a FRESH
      login; the guard will pause for re-login if it times out again (~2/3 through).
      Regenerate the full 246 anytime with `--from-hc`. Still watch long identifiers for
      server truncation → set `MAX_IDENTIFIER_LEN` if needed.
- [ ] **Discover the Identifier server length cap** from the live run (esp. a long one
      like the 58-char EHS Rep), then set `MAX_IDENTIFIER_LEN`.

## 🆕 Batch encounter/assessment intake (requested 2026-06-30)
Dane has 40+ encounters/assessments from one day to enter, from dictated notes, mostly
coaching encounters.

- [x] **Intake prompt updated:** `TRANSCRIPTION_PROMPT.md` now routes coaching encounters
      → `encounters.csv` and lists assessments separately under
      `ASSESSMENTS — manual entry` (Dane enters those by hand for now). *(2026-06-30)*
- [x] **Launcher buttons relabeled (2026-06-30):** `emr_automate.py` `popup_choice()`
      switched from MessageBoxW Yes/No/Cancel to a tkinter dialog with real labeled
      buttons — **Coaching Encounters / Update Roster / Cancel** (Dane disliked clicking
      "No" to mean Roster).
- [ ] **NEXT BUILD — "start + first screen only" drafting** (Dane wants it for the rest
      of the week): extend the tool to pick the case-type tile, fill the shared
      Encounter-Details first screen, and "Save in progress" — for BOTH encounters and
      assessments. Per PLAN.md Gap B: Coaching = Step 1+2; Assessments = Step 1 only.
      VERIFY first-screen parity by capturing one of each assessment type.

## 🔴 Next up — INTEGRATION DIRECTION (see PLAN.md)

Direction chosen 2026-06-23: stop relying on dictation/CSV and feed EMR AutoMate
from Dane's existing capture pipeline (mobile-encounter-companion → ETS → EMR
AutoMate drafts into the EMR). Full plan in **PLAN.md** (draft, expected to change).
No build started — planning only until Dane gives the go.

- [x] **DECIDED: AutoMate reads from ETS via the REST API** (not the SQLite file).
      ETS is already running for sync/auto-convert anyway; the API gives a stable
      contract, ETS's own filtering/joins, and a safe write-back path to mark
      encounters "drafted to EMR" (avoids double-drafting). *(2026-06-23)*
- [ ] **Remaining open decision** (PLAN.md): default missing EMR fields vs. extend
      the capture form to collect them. (Trigger is now decided — see "queue +
      Push-to-EMR" below.)
- [ ] **Confirm ETS internals (read-only):** `GET /encounters` shape, the
      `mobile_sync` import path, mobile capture record fields, how
      `mobile_capture_entries` become real encounters.
- [ ] **Confirm working behavior of mobile→ETS sync.** The upload code exists
      (`captureSyncService.uploadMobileCaptureEntries`), but verify it actually works
      end to end — endpoint reachable, ETS accepts the record, env vars configured,
      capture lands in `mobile_capture_entries`. Don't assume the code is functional.
- [ ] **Fix lack of auto-conversion.** On sync, ETS only inserts the capture into
      `mobile_capture_entries` as `pending_review` — it does NOT become a real
      encounter; it waits for manual desktop review/import. Decide/build how captures
      become live encounters (auto-convert on sync, or a streamlined import) so the
      EMR-draft pipeline has real encounters to read.
- [ ] **Ensure raw capture from the mobile companion is 100% reliable.** Auto-convert
      is only safe if the captured data can be trusted — verify capture accuracy
      (employee match, encounter type, required fields, dedup) before removing the
      manual review gate.
- [ ] **Phase 1 thin slice:** EMR AutoMate reads one "ready" coaching encounter from
      ETS, maps with defaults, drafts it.
- [ ] **Build the label-mapping layer** (mobile/ETS → EMR coaching types + details;
      defaults for EMR-only fields). Mapping table is in PLAN.md.

### Decided build items (from the gap-fix brainstorm — details in PLAN.md)
- [ ] **Assessments — "start + first screen only."** Pick the case-type tile, fill
      only the shared Encounter-Details screen, Save in progress; Dane finishes the
      rest manually. Coaching = Step 1+2; Assessments = Step 1 only. VERIFY first-screen
      parity (esp. encounter-type tiles) when building; fills already best-effort.
- [ ] **Employee-name reconciliation (Gap A):** roster-synced dropdown (seeded from
      EMR roster) + normalization + a growing alias table. Badge/ID later (caveat:
      not all employees have an EMR ID entered yet).
- [ ] **Failure handling (Gap C):** flag `emr_drafted` only on confirmed save;
      categorize transient (auto-retry once) vs structural (skip + flag); session-
      expiry re-auth guard; end-of-run report (on screen + written back to ETS).
- [ ] **Trigger = queue + "Push to EMR" button (Gap D):** conversion sets
      `emr_draft_status='queued'`; ETS (same PC) spawns AutoMate on a "Push to EMR"
      button to drain the queue. Windows Task Scheduler later once trusted.

### Parked (future phase)
- [ ] **HMA score double-entry:** AutoMate enters HMA scores into the EMR AND the HMA
      Corrective Exercise Tracker in one shot (→ EMR record + auto corrective-exercise
      plan). Needs a richer HMA-score capture source (`Dane-Lee/HMA-app`, not built yet).

### Deprioritized (CSV/dictation path — now a fallback, not the main route)
- [ ] ~~Test a real multi-row BATCH~~ — Dane declined; superseded by the integration.
- [ ] **Spot-check other coaching types / multiple details** (still useful for the
      drafting engine regardless of source — e.g. Safety Coaching → PPE Use).

## 🟠 Reliability (so it doesn't silently do the wrong thing)

- [x] **Stable selectors instead of fragile React-Select IDs.** `react_select` now
      targets fields by their visible label, not auto-generated ids. *(2026-06-23)*
- [ ] **Employee-match confirmation.** Right now it clicks the FIRST search result.
      If two employees share a name, it could pick the wrong person. Add a step to
      show matches and confirm before proceeding.
- [x] **Screenshot on failure.** Done — `snap()` saves a screenshot + page HTML to
      `./debug` at each step and on any error. *(2026-06-23)*
- [ ] **Handle "Other" checkboxes that reveal a text box.** Several coaching types
      have an "Other" option that opens a free-text field — currently not filled.
- [ ] **Constrained dropdown values.** Department/Division/Category/Shift are real
      dropdowns in the EMR but free-text in our prompt. Capture their option lists
      and offer them as menus (prevents typos that won't match).
- [ ] **Make detail options easy to see per coaching type.** Dane wants to know
      which `details` are valid for a chosen type (or have the AI pick them for
      him). The AI transcriber already auto-selects details from his narrative, and
      interactive mode shows only valid options — but add a quick reference (e.g. a
      one-page cheat sheet) so he can eyeball the lists too. *(requested 2026-06-23)*

## 🟡 Convenience / usability

- [ ] **Double-click launcher.** A `Run EMR AutoMate.bat` so you can start it
      without typing terminal commands (also dodges the `python` PATH/Store-stub
      issue by calling the full interpreter path).
- [x] **Native popup prompts (no PowerShell back-and-forth).** Login gate, batch
      confirm, do-another, and continue-on-error now use on-top Windows dialogs
      (`popup()` via MessageBoxW) instead of terminal `input()`, so you stay in the
      browser. *(2026-06-23)*
- [ ] **Encounter log file.** Append each saved encounter (employee, date, type) to
      a CSV so there's a record of what was entered and when.
- [x] **Stay-logged-in between launches.** Done via persistent browser profile
      (`.browser_profile/`) — remembers login + worksite across runs. *(2026-06-23)*

## 🔵 Scope — case types beyond Coaching Encounter

- [ ] **Physical Assessment case type.** Discovered 2026-06-23: Dane dictated a
      "physical assessment / follow-up" (piriformis stretches, trigger-point
      self-massage) — it is a SEPARATE EMR case type, not a Coaching Encounter, so
      the current tool can't enter it. Need to learn its form (capture HTML like we
      did for Coaching) and add support. Priority TBD pending Dane's case-type mix.
- [ ] **Map all the case types Dane actually enters** and their volumes, so we
      build for his real workload rather than just the one type the tool started on.

## 🟢 Later / nice-to-have

- [ ] Support additional case types beyond Coaching Encounter, if useful.
- [ ] Field validation before Save (warn on missing required fields).
- [x] **Draft mode ("Save in progress") instead of finalizing.** Dane's idea
      (2026-06-23): the robot only saves DRAFTS via "Save in progress"; he
      reviews/finalizes them in the EMR's InProgress list. Reframes the tool as a
      drafting assistant (never commits), enables unattended batches, and lowers
      the bar (imperfect fills are fine — fixed at finalize). Implemented as
      `SAVE_MODE = "draft"` (also "review" / "final"). Confirm on first success:
      does it allow partial saves, do drafts land in InProgress, is finalize quick.

---

## ✅ Done

- [x] Move script into the EMR AutoMate project folder. *(2026-06-22)*
- [x] Convert from edit-the-source config to interactive terminal Q&A,
      one encounter at a time. *(2026-06-22)*
- [x] Add the "do another encounter?" loop with single login per session
      and per-encounter error handling. *(2026-06-23)*
- [x] Install Python 3.12 + Playwright + Chromium on this machine;
      confirm the script compiles cleanly. *(2026-06-23)*
- [x] Switch to a persistent browser profile (remembers login + Navarre). *(2026-06-23)*
- [x] Add debug capture (`snap()`): screenshot + HTML per step and on error. *(2026-06-23)*
- [x] Build the **CSV batch pipeline**: `encounters.csv` reader with full row
      validation, batch vs interactive modes, per-row review (save/skip/quit),
      plus `TRANSCRIPTION_PROMPT.md` and `encounters_template.csv`. Data layer
      tested (valid + broken files). *(2026-06-23)*
