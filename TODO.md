# EMR AutoMate — To-Do List

Living checklist for the ATI coaching-encounter automation. Check items off as we
finish them. Newest priorities at the top of each section.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

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
