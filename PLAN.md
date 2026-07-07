# EMR AutoMate — Integration Plan (Mobile Companion → EMR)

> **Status: DRAFT, expected to change.** Saved 2026-06-23 as a checkpoint so we
> don't lose the thinking. Decisions in the "Open decisions" section are not yet
> made. Nothing here is built yet.

> **Related (separate feature):** Employee **roster update** (update employee file
> info in the EMR from an Excel roster) is a distinct function with its own plan
> (`inherited-launching-mitten.md`), spec (`ROSTER_UPDATE_PROMPT.md`), and code
> (`update_employees.py`, launched from `emr_automate.py`). It's not part of this
> mobile→EMR integration; see TODO.md "Employee Roster Update".

## Goal
Make Dane's existing capture tools the single point of entry, and have EMR AutoMate
push those encounters into the official ATI EMR as **drafts** ("Save in progress")
for him to review and finalize. No dictation, no hand-built CSV, no double entry.

## Architecture decision (2026-06-24): SEPARATE programs for v1
AutoMate stays a standalone Python/Playwright tool; it is NOT merged into ETS.
AutoMate talks to ETS over the local REST API, and ETS (same PC) spawns AutoMate on
the "Push to EMR" trigger. ETS runs continuously (server); AutoMate runs on demand,
drafts, and exits. Unifying into one Node program (port Playwright to TS) is a
possible later optimization, not v1 (would require rewriting/re-testing all the
working automation).

## The one hard constraint that shapes everything
The EMR automation (Playwright) **must run on the work PC** — that's where the
authenticated Navarre session lives. A phone web app can't drive the EMR, and the
PC can't read the phone's local IndexedDB. **So the phone captures; the PC drafts.**
"Integrate into the mobile companion" means the companion is the **capture + trigger
surface**, and data travels through the existing sync to the PC, where EMR AutoMate
drafts it.

## The two upstream repos (already built by Dane)
- **mobile-encounter-companion** (`C:\Users\dane.lee\mobile-encounter-companion`):
  React/Vite PWA, local-first (IndexedDB). `Capture Mode` records
  `employeeDisplayName`, `encounterType`, `summaryShort`, `tags`, `followUpNeeded`,
  status `draft` → `ready_for_export`. Uploads `mobile_capture_entry` records to the
  ETS server (`POST /api/sync/mobile_capture_entries`). Backend-mediated sync only.
- **encounter-tracking-system (ETS)** (`C:\Users\dane.lee\encounter-tracking-system`):
  React/TS client + Express/TS server + SQLite (`server/data/encounter_system.sqlite`).
  REST API on `localhost:3001`, token auth. Stores encounters, personnel/roster,
  description templates, exports, and the mobile-sync intake (`mobile_capture_entries`).

## End-to-end flow (left two-thirds already exists)
```
Mobile companion (Capture Mode)
   │  capture encounter, mark "ready"
   ▼
existing sync  →  POST /api/sync/mobile_capture_entries
   ▼
ETS desktop (Express + SQLite)        ← already receives & stores these
   ▼
EMR AutoMate (PC, Playwright)         ← NEW: reads "ready" coaching encounters
   ▼
EMR draft via "Save in progress"  →  Dane reviews/finalizes in InProgress
```

## What's new vs. existing
- **Existing:** capture UI, mobile→ETS sync, ETS storage, EMR AutoMate's EMR-drafting
  engine (working end-to-end as of 2026-06-23 for a single coaching encounter).
- **New:**
  1. **Mapping layer** — mobile/ETS labels → EMR coaching types + detail checkboxes;
     defaults for EMR-only fields.
  2. EMR AutoMate **"pull from ETS" mode** — read ready coaching encounters for a
     date, draft each.
  3. **Trigger + dedupe** — don't draft the same encounter twice.
  4. *(Optional, later)* extend the mobile **capture form** with EMR-specific fields.

## Open decisions (not yet made — will shape the build)
1. **Where EMR AutoMate reads from:** ETS **REST API** (clean; server must run) vs.
   the **SQLite file directly** (simplest; nothing running). And: read **reviewed
   `encounters`** (needs Dane's desktop import step) or raw **`mobile_capture_entries`**
   (skips review)?
2. **Trigger:** Dane **runs EMR AutoMate on the PC** and it pulls everything marked
   "ready" (simplest, since the phone can't easily poke the PC) vs. something fancier.
3. **Field gaps now:** lean on **draft mode** — fill what we have, default the rest
   (modality = In Person, what-prompted = Specialist Initiated, details = best/Other),
   finish at finalize? Or invest up front in **extending the capture form**?

## Suggested phasing (nothing starts without Dane's go)
- **Phase 1 — thin slice:** EMR AutoMate reads one "ready" coaching encounter from ETS,
  maps with defaults, drafts it. Proves the chain with the companion as real source.
- **Phase 2 — coverage:** all 11 coaching types + detail mapping; clean skip of
  assessments; "ready/already-sent" status so nothing double-drafts.
- **Phase 3 — capture enrichment:** add EMR modality / details / what-prompted to the
  capture form so drafts are near-complete (the real "integrate into the companion").
- **Phase 4 — trigger & UX polish.**

## ETS API contract for AutoMate (confirmed 2026-06-24, read-only)
- **Read a date's encounters:** `GET /api/day?date_text=YYYYMMDD` (capability
  `view_operational`). Returns `{ date_text, encounters[], activities[],
  scheduled_tasks[] }`; each encounter = full row + joined `employee_name`,
  `personnel_name`. Query excludes deleted but returns BOTH Open and Complete —
  AutoMate filters `status='Complete'` itself. NOTE: there is NO `GET /encounters`;
  it's all writes. `GET /api/bootstrap` returns employees + personnel + description
  templates + rules.
- **Auth:** send `x-api-token: <token>` (or `Authorization: Bearer`). Token = a
  user's `api_token`; coach/admin/viewer have `view_operational`.
  - ⚠ API-token auth is OFF unless ETS runs with env `ALLOW_DEV_API_TOKENS=true`
    (else only browser-session cookies work → token = 401).
  - ⚠ Verify `require_policy_acknowledgement` middleware doesn't 403 a token user.
  - Origin check only blocks mutations, so the GET is unaffected.
- **Phase 1 needs ZERO ETS changes:** AutoMate reads `/day`, drafts coaching
  encounters, tracks drafted IDs in its OWN local file (defer the ETS `emr_drafted`
  flag/endpoint to later).
- **date_text** is compact `YYYYMMDD` (ETS) vs ISO elsewhere — convert in AutoMate.

---

## Gap fixes (theoretical end-state) — brainstormed 2026-06-23, not yet decided
The "drafts, not finished records" gap is accepted by design. These are the other
gaps in the ideal hands-off flow, with options and a recommended pick each.

### A. Employee-name reconciliation (phone name → ETS → exact EMR roster name)
- Roster-synced pickers: capture from an ETS-roster dropdown (seeded from the EMR
  Navarre roster) so the chosen name is already a valid EMR name.
- Normalize + fuzzy-match at draft time (exact first, then fuzzy w/ confidence
  threshold; low confidence → skip + flag).
- Growing alias table for stubborn cases (Mike/Michael, maiden names).
- Badge/ID as the gold key — EMR search supports "or Identifier"; store EMR id in ETS.
- **DECIDED (2026-06-23):** roster-synced dropdown + normalization + growing alias
  table now; badge/ID later as the durable key. CAVEAT: not all employees have an
  EMR ID entered yet, so badge/ID is only partially available — name reconciliation
  + alias table must carry the load for now.

### B. Assessments — DECIDED (2026-06-23): "start + first screen only" approach
Don't try to fill assessment-specific data. AutoMate just **starts** the assessment
and **Saves in progress with only the first ("Encounter Details") screen filled**;
Dane finishes the assessment-specific screens manually (for now).

- Generalizes the existing engine: pick the case-type tile in the "Select Assessment
  Type" modal → fill the common first screen → Save in progress. Tile-select is
  already solved; the first screen is the Step 1 we already automate.
- **Branch by case type:** Coaching Encounter = fill Step 1 **+** Step 2 → save;
  Assessments = fill Step 1 **only** → save (Save-in-progress button is on screen 1).
- **VERIFY (not assume):** that the first screen is truly the same across types —
  esp. whether assessments have the "In Person/Phone" encounter-type tiles or
  different required fields. Safety net: Step 1 fills are already best-effort, so a
  slightly different first screen still drafts (shared fields fill, rest skipped).
  Confirm with one capture when building.
- Covers: Physical, HMA, Task, Office, Work Readiness, etc. — all as "started drafts."

### B-future. HMA score double-entry (parked — separate, later phase)
Dane keys HMA scores manually today (the HMA Corrective Exercise Tracker does NOT
generate scores). Idea: AutoMate enters HMA scores into BOTH the EMR assessment AND
the HMA Corrective Exercise Tracker in one shot → one entry yields the EMR record
*and* the auto-generated corrective exercise plan. Strong force-multiplier; bigger
separate build (and HMA scores need a richer capture source than the quick mobile
capture — eventually the other HMA app). Not v1.

### C. Failure handling (one bad encounter shouldn't sink a batch)
- Flag `emr_drafted` ONLY on confirmed "Save in progress" success → failures retry
  next run automatically (idempotent).
- Categorize: transient (slow/session) → auto-retry once; structural (no employee,
  unmapped type) → skip + flag.
- Session-expiry guard: if on a login screen, pop the re-auth dialog and resume.
- Run report: "Drafted 8, skipped 2 (why)" on screen + written back to ETS per-encounter.
- **DECIDED (2026-06-23):** all four (flag-on-success, categorize transient vs
  structural, session-expiry guard, run report).

### D. Trigger timing (PC must be on + EMR session alive)
- Queue model: conversion sets `emr_draft_status = 'queued'`; AutoMate drains the
  queue whenever it runs (no real-time coupling).
- Kickoff options: "Push to EMR" button in ETS (ETS + AutoMate are on the SAME PC, so
  ETS can spawn the AutoMate process) · manual run · Windows Task Scheduler (hands-off).
- **DECIDED (2026-06-23):** queue model + a "Push to EMR" button in ETS for v1; add
  Windows Task Scheduler later once trusted.

**Synergy:** ETS and AutoMate live on the same PC, so ETS can both BE the API source
and BE the trigger (spawn AutoMate on "Push to EMR") — collapsing trigger + hand-off
into one integration.

---

## Appendix — coaching-type mapping (the 11 that map to EMR Coaching Encounters)
Labels differ across all three systems; a mapping table is required.

| Mobile companion label | ETS key (`rule_config.ts`) | EMR coaching type |
|---|---|---|
| Job-Specific Coaching | JobSpecificCoaching | Job-Specific Coaching |
| Job-Specific Mobility / Stretching | JobSpecificPreventionMobilityStretching | Job-Specific Preventative Mobility/Stretching |
| Safety Coaching | SafetyCoaching | Safety Coaching |
| Ergonomic Adjustments | ErgonomicAdjustment | Ergonomic Adjustment |
| Health and Wellness Coaching | HealthAndWellness | Health/Wellness Coaching |
| General Medical Coaching | GeneralMedicalEducation | General Medical Education |
| Relationship Development | RelationshipDevelopment | Relationship Development Encounter |
| Group Class | LargeGroupClass | Group Class |
| Fitness Center Visit | FitnessCenterVisit | Fitness Center Visit |
| Near Miss Education | NearMissEducation | Near Miss Education |
| Friend/Family Consultation | FriendFamilyConsultation | Friend/Family Consultation |

**Out of scope (separate EMR "Select Assessment Type" case types, not Coaching
Encounters):** Physical Assessments / PA Follow-Ups, Human Movement Assessments / HMA
Follow-Ups / Reassessments, Office Assessments, Task Assessments, Work Readiness.

**EMR fields not captured upstream today** (default or finish at finalize): encounter
modality (In Person / Phone / Telehealth / Email), Division, Category (Full/Part-Time),
detail checkboxes (Hydration / Other / …), what-prompted.
