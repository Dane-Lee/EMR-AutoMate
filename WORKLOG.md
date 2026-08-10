# EMR AutoMate — Work Log

A running history of what we've worked on, session by session. Newest entries at
the top. This is our "saved chat" record — each session I append what changed,
what decisions we made, and where we left off. See `TODO.md` for the forward list.

---

## Session 17 — 2026-07-31 (new worksheet synced; hints activated; "Shift Board" redesign)

Three items from Dane, gated one at a time. The workbook was also **cleared as non-PHI**
by Dane this session — see the new note in `CLAUDE.md`; it's his own template file.

### 1. New Easy Enter workbook synced — and the hints finally work
Dane replaced the workbook (47 → 64 description cells, +18 added, 1 removed, 2 rewritten;
diffed structurally by hashing each cell, so it was reviewable before the PHI question was
settled). `DESCRIPTION_MIN_CHARS = 60` re-measured on the new file and still clean:
longest short cell 54, shortest description 62.

He then added `Choose …` hints across every tab — and **only 1 of 64 reached the builder.**
Cause, found by mapping the row SHAPE of each tab (structure only, no text): the workbook
has two conventions. NHO Encounters puts the hint on the same row as its description, which
is what `load_library()` expected; **every other tab puts it on the row BELOW**, and those
were read and thrown away. Three NHO hints were also ≥60 chars, so the length test caught
them first and filed them as pickable *descriptions* — instruction text posing as
documentation, the 77-records bug in a new place.

Fixed in `load_library()`: a `Choose` cell is a hint at any length; a hint row carrying no
description of its own attaches to the description row above it; same-row hints still win.
One hint row after a multi-description row applies to all of them (Dane's call — they're
variations of one scenario). Result: **61 real entries, 42 with working hints, up from 1.**

### 2. "Shift Board" — the UI redesign (Dane picked it from two directions)
Two directions were pitched as a published mockup rather than hex values in a terminal.
Dane picked **Shift Board**: slate ground `#14181D`, safety amber `#F0A32B` on every active
state, hi-vis `#9DBE3B` reserved for the batch tally alone, **Bahnschrift** (Windows' DIN
face — machine-panel lettering) for legends, Consolas for counts. Font availability was
checked against the real installed list, not assumed, and `_set_fonts()` re-resolves it at
startup because Tk substitutes silently.

**The roster list is now a `tk.Text`, not a `Listbox`** — that's what made the shift rail
possible. A Listbox allows exactly one foreground per row, so a coloured bar that differs
from the name beside it cannot exist there. Nothing was lost: the Listbox was created
`selectmode=EXTENDED`, but `_on_click` returned `"break"`, pre-empting the class binding
that sets a selection — so mouse selection never existed and `curselection()` was always
empty. Click-to-toggle is unchanged; keyboard access is now real (focus row, Up/Down/PgUp/
PgDn, Return/Space) instead of nominal.

Two deliberate departures from the approved mockup:
- **The rail is not amber for 1st shift.** Amber already means active/selected, and one
  colour cannot carry two meanings. Rail is blue/orchid/teal, none of them the accent.
- **The checked wash spans the line including its newline** (the only way a Text background
  reaches full width), which repaints everything under it — so the rail tag is re-applied
  and raised above it. That's the regression most likely to break silently later, so the
  smoke test asserts tag order explicitly.

Measured, not guessed: the tracked legend `WHAT WAS THE ENCOUNTER? (APPLIES TO EVERYONE
CHECKED)` renders 497px against a 431px panel, so the legend was cut to the short form.
261 rows render in 3ms. **Also found: the roster tally line needs 448–670px in a 431px
panel and has been clipping — pre-existing, not from this work.**

### 3. Description variations — proposed, Dane applies them himself
Picked `Target-Check Ins`, `General-Relate`, `Target-Add-Ons` on evidence: Check-Ins has
3 byte-identical Team Lead rows out of 5 and is used daily; Relate's first three entries
are one sentence reworded and it's a large share of real batches; Add-Ons is 16 entries
sharing a single sentence frame. Variations rephrase only what the original documents —
adding technique or findings to a template would be falsifying a record.

Defects found and handed to Dane (he's editing the workbook himself): the 3 duplicate rows;
`Target-Add-Ons` [7] missing "with" and duplicating [8]; `Target-JobCoaching` [1] is a
fill-in-the-blank template that is **pickable** and could enter `______` into a record;
`NHO-HMA's` [1] is a heading, not a description; `General-GroupClass` hints have an
unbalanced quote so they tick nothing; `Protective Recommendations` [5] has a stray `”`;
`General-Relate` [3] slips into first person ("my help").


## Session 16 — 2026-07-29/30 (first big live batch: 52/62 saved; two entry bugs found and fixed)

Dane built and ran a 62-row batch (the first real run since the builder rework). Result:
**52 saved, 4 name-unmatched, 6 errors.** Audited via `--audit` + the scrubbed `debug/`
captures; both error causes were found in the page HTML, not guessed. Dane has since
**abandoned that batch** (drafts and all) — the fixes are what carry forward, not the data.

### ✅ Live-confirmed: the "In Progress" modal dismissal works
Session 15's `dismiss_in_progress_prompt()` was only verified offline. This run settles it:
**58 `INPROGRESS_prompt` captures** and the batch still saved 52 in a row. It detects the
real modal and clicks No without derailing. That TODO item is closed.

### Bug 1 — "+ Add Case" is DISABLED for an employee who already has an In Progress case
Rows 38/41/46/55 (all Group Class, purely by coincidence of position) failed with a bare
`Locator.click: Timeout 30000ms exceeded`. Cause, read off the `03_employee_selected`
capture taken *before* the click: `<button ... disabled="">+ Add Case</button>` plus an
"In Progress" badge on the employee header. **4 of 4 failures had it; 52 of 52 successes
had neither** (correlation rebuilt on this run's captures only — `debug/` filenames carry
no date and accumulate across days, so an unfiltered sweep silently mixes in other runs).

The old code made it worse rather than reporting it:
- it waited for the button to be **visible**, and a disabled button is visible;
- the 8s click timed out, and the fallback **force-clicked** it — `force=True` skips the
  actionability checks and clicks a disabled button, doing nothing, silently;
- so the modal never opened and the *tile* click below burned its full 30s default
  waiting for markup that was never coming.

Two minutes of the run spent producing four timeout notes that named neither cause nor fix.
**Fix:** wait for *enabled* (8s grace), never force-click a disabled button, raise the new
`AlreadyInProgress` — logged as its own `already-in-progress` status, counted as skipped
not error, and excluded from the circuit breaker (it's the employee's EMR state, not a
systemic failure). The tile click is now bounded at 10s with a message that says the modal
never opened.

### Bug 2 — an empty employee list was reported as a misspelled name
Rows 9 and 36 failed with "Couldn't find employee … check the spelling and the
'Last, First' format" — **but both names were fine**; the pre-flight had already matched
them against the full roster. Their `02_employee_list` capture: **0 `.name` spans**, a
19,770-byte skeleton of 10 placeholder `.details` rows, where a healthy capture in the same
run had **938 names**. `roster_names()` waits 30s for a `.name` to attach, returns `[]`,
and `find_matches` turns the empty list into "not found".

This is exactly the distinction `preflight_names` already makes — *an empty roster is a
LOAD failure, not 77 bad names* — that `locate_employee` was missing. It's the same class
of bug as the 2026-07-16 preflight name-read, and it fails the same way: **it blames Dane's
data for the automation's blind spot.**

**Fix:** on an empty list, reload and re-match against the **unfiltered** roster (the
surname search box is only a speed-up, and it is what emptied the list — which also means
entry-time matching can no longer disagree with the pre-flight that already succeeded).
Only if that also comes back empty does it raise, and then it says plainly that it's a
page/render failure and **encounters.csv is fine, leave it alone**.

### Note for next time
Both bugs cost 30s each because both waits were Playwright's silent default. When a click
can legitimately never succeed, bound it and say why — a 30s timeout that names neither the
cause nor the fix is barely better than a hang.


## Session 15 — 2026-07-22/24 (assessment capture mode; six builder fixes; EMR "In Progress" modal)

### EMR change — new "In Progress" navigation modal, auto-dismissed (2026-07-24)
The EMR tech team added a modal that pops on the dashboard whenever drafts exist —
"There are active encounters that have been saved 'In Progress'. Would you like to
navigate to the 'In Progress' case list?" (Yes / No) — and it blocks the next save. Since
the batch is mid-draft, it fires **every row** after the first. Fix in
`ati_coaching_encounter.py`: `dismiss_in_progress_prompt()` detects it on the LIVE DOM
(regex `navigate to the|active encounters`) and clicks **No** (stay and keep drafting;
Yes would derail the batch). Wired into `open_dashboard` (twice — on load and once the
roster attaches) and defensively after employee-select. Non-fatal (never raises, returns
fast when absent) and it `snap()`s the modal the first time so the real markup is on
record. Modal strings registered with `phi_redact`. **Verified offline** against a local
HTML replica with Playwright (`scratchpad/modal_test.py`): detects the prompt, clicks No,
stays (doesn't navigate), returns False when absent. Live confirmation comes on Dane's
next batch run — if the real markup differs, it degrades to today's behavior (stall) plus
a captured `INPROGRESS_prompt.html` to refine the selector.



### Assessment work — first step built, then paused for builder fixes
Scoping decided with Dane: assessment data **source = the builder** (extend it, no CSV,
no dictation), **first type = Physical Assessment**, **fill depth = decide after we see
the form**. Built `--capture-assessment "Last, First" ["Tile Label"]` in
`ati_coaching_encounter.py`: reuses the add-case navigation, **lists the modal's tile
labels** (so we learn the exact labels from the page, not a guess) + the first-screen
field labels, and snaps the scrubbed form to `./debug` (`ASSESS_*.html`). Nothing saved.
**Not yet run by Dane** — paused when he moved to builder changes.

### Six builder changes requested by Dane (items 1–6 of his list)
Items 1–5 done and verified; 6 folded into 7 (below).
- **(1) Role filter** — "Line Leads" / "Supervisors" checkboxes next to the Shift chips
  in "Who did you see?". Measured the roster first (counts only): there is **no**
  "Line Lead"/"Supervisor" *title* — leads are `Team Lead` (17) + `Training Lead` (1) =
  18; supervisors are `Prod Sup` (8) + `Maint Sup` (1) = 9. So the filter matches those
  real titles by word-prefix (`ROLE_FILTERS`), not Dane's label. Inclusion filter,
  inactive until ticked; not persisted (momentary view). **If "Line Leads" should mean
  something other than Team/Training Lead, adjust `ROLE_FILTERS`.**
- **(2) Library auto-filters by coaching type** — opening the Library defaults its
  category to the tab matching the chosen coaching type (`library_category_for`, token
  overlap), with a "(matched to …)" note; falls back to "All categories".
- **(3) Review batch is cards, not CSV text** — each group shows *N people · coaching
  type*, a meta line (date/encounter/prompted/dept/shift/category), details, full
  description, and **the actual names**, plus per-card Delete. `_group_summary` reads it
  back off the rows (dept/shift shown as "per employee" when they vary).
- **(4) Category dropdown shows all at once** — Library category combobox
  `height = min(len(cats), 25)`.
- **(5) Group Class description box visibility** — cause: in per-employee mode the
  group-wide dept/div/shift block sat there as 5 *disabled* rows, and Group Class's 10
  detail checkboxes pushed the description off a 700px-tall window. Fix: **hide** that
  block when it doesn't apply (`grid_remove`), a description min-height floor, and
  trimmed the two group-panel separators. **Verified by direct geometry measurement** at
  a 700px window: description fully on-screen in all four mode×type combos (tightest,
  group + Group Class, clears by 12px).
- Verification note: the agent **cannot screenshot** the builder (the launched window is
  on a window station the agent's PowerShell can't reach — `FindWindow` returns nothing).
  So item 5 was proven by measuring widget geometry, and items 1–5 by a headless
  construct-and-exercise probe (`scratchpad/ui_probe.py`, `UIPROBE_VERIFY=1`). The
  *look* (item 6) genuinely can't be seen from here.

### (6)+(7) Individuals mode — faster one-at-a-time entry (built 2026-07-23)
Dane: batching groups works, but distinct one-at-a-time encounters are too slow; item 6
(builder "looks outdated") **folded in** since this reshapes the layout. Design decided
with Dane: rapid **"Add & Next"** card; per person, coaching + description + person all
vary; descriptions are a library/free-type mix.

Built a **`Groups | Individuals` mode switch** (segmented Toolbutton, top-left where the
panel has vertical slack). Individual mode is a *lens over the same form*, not a second
panel — lowest risk, reuses every widget:
- Click a name → **loads** that one person (doesn't check); the location chooser + bulk
  controls hide; the add button becomes **Add & Next** (also **Ctrl+Enter** — plain
  Enter stays free for description newlines).
- **Add & Next** stores the person as a **group of one** located to their own roster
  dept/div/shift, then clears person/description/detail-ticks and **carries forward**
  date · encounter type · prompted · category · coaching type. So Review / Write / the
  automation are all unchanged — a single is just a 1-row group.
- Picking a Library description now **auto-sets the coaching type** from its tab
  (`coaching_type_for_tab`, the reverse of item 2) *only when the type is unset*, and
  auto-ticks details from the "Choose…" hint — so a library-based single is ~person +
  one pick.
Shared `_encounter_fields` / `_make_row` back both add paths (no duplicated validation).

**Verified headlessly** (`scratchpad/ui_probe.py individuals`, `geom_check.py`): a single
produces exactly the CSV columns with per-employee location from the roster; carry-forward
works; the mode toggles both ways without error; the description box is visible in both
modes and item-5's group-mode geometry is unregressed. **Still can't screenshot the
window** — Dane opened the real builder 2026-07-23 to enter that day's encounters and to
eyeball the look; the visual (item 6) is his to confirm/redirect.

---

## Session 14 — 2026-07-16 → 07-20 (Copilot intake removed → local Encounter Builder; UI overhaul; add-employee feature started)

### Copilot dictation intake RETIRED → `encounter_builder.py`
The M365 Copilot dictation→CSV flow was miserable — dictation mangled names and the
LLM kept guessing controlled values (it once stamped one coaching type across 80
records). Removed it whole: deleted `copilot_spec.md`, `make_copilot_prompt.py`,
`library_export.py`, `Paste-Encounters.ps1`, `DICTATION_PROMPT.md`,
`TRANSCRIPTION_PROMPT.md`, `M365_WORKFLOW.md`, the dormant `.github` prompt.
`WORKFLOW.md` replaces `M365_WORKFLOW.md`.
- **`encounter_builder.py`** (tkinter): check names off the roster (never typed → never
  mis-transcribed), set the coaching once per group, write `encounters.csv`. Every
  controlled value is imported from `ati_coaching_encounter` so the picker can't drift
  from the validator. `coaching_type` has no default — a dropdown can't guess it.

### Three production bugs — all the same mistake: couldn't see it, guessed, shipped confident
- **Window 850px tall on an 800px screen** → the action buttons were off-screen. Now
  sizes from `winfo_screenheight()`; the batch bar is pinned to a zero-weight row.
- **Preflight read each roster row's first line of text as the employee name** → all 77
  names came back "not found" and it blamed Dane's data. The name is
  `<span class="name">` (see `update_employees._ROW_RE`). Also now waits for the React
  roster to render, and treats an empty roster as a load failure, not bad names.
- **The description library joined every worksheet cell with `" | "`** → wrote
  `Choose "Other" | Job-Specific Coaching | EIS asked…` into 77 records, and dropped
  row 1 of every tab as a "header". Now classifies cells by length (labels ≤54,
  descriptions ≥62 — clean gap). A `Choose "…"` note auto-ticks the detail boxes.
- `CLAUDE.md` now names this pattern and records the three facts, so the next session
  measures instead of guessing.

### Per-person Department/Division from the roster
Dane hand-set Department + Division for all 261 employees in the HC export.
`import_hc_roster` now copies both into `roster.xlsx` verbatim (no correction); the
builder reads each person's own area. Retired `work_titles.csv` (title-guessing).
The heat-index case (one coaching, people across departments) is now correct at the
source rather than inferred.

### Entry-engine robustness
- **Session guard** (`open_dashboard`): an expired session mid-run was burning a 30s
  click-timeout per row until the circuit breaker stopped the batch (77 → 35 saved).
  Now detects the login screen, pauses for re-login, resumes.
- **`--resume`**: rewrites `encounters.csv` to only the rows the audit log did NOT
  confirm saved, keyed by content so it's idempotent. Used after a partial run.
- `mobile_import.py` was printing employee names raw (no `phi_redact`) — fixed.

### UI overhaul (Dane: "looks like Windows 95")
- Flat `clam`-based theme + palette (white cards, thin borders, accent blue, 11pt
  text). Custom **checkmark** checkbox indicator (was an X).
- Picking people: taller proportional-font rows, green highlight + ☑ on checked names,
  a bold checked-count, a "checked only" review toggle, and a "Check everyone in
  <department>" one-shot.
- Filter: replaced the 30-job-title scroll list with **8 work-AREA (division)
  checkboxes** (Admin/Office back on screen). Prefs store `hidden_areas`.
- Library: rebuilt into scrollable **cards** (full text visible, category tag, Use
  button, category filter + search).
- **Demo mode** (`--demo`): fake names + real EMR structure, so UI work is PHI-free —
  and screenshottable (window-handle capture). This is how the UI was finally
  *verified* instead of guessed.
- Fixed a real launch bug: `main()` used `sys.argv` but never imported `sys` (a
  `NameError` that crashed any launch) + a `pythonw` stdout guard + raise-to-front.

### Add-employee feature — INVESTIGATED then SHELVED (2026-07-21)
The EMR lets you attach extra employees to an encounter before saving. First read
(2026-07-20): adding N → one shared record, finalizing it finalizes for all → collapse a
group into one draft. Built a `--capture-addmore` mode to see the `.add-more` control.
**Then Dane corrected it (2026-07-21): the collapse into one record only happens on
FINAL save. On "Save in progress" — which is exactly what AutoMate does — it creates
individual drafts per attached employee anyway.** So there's no saving in the draft
workflow, and finalizing from AutoMate would break the "nothing finalized without Dane"
model. **Dropped**: removed the `--capture-addmore` code (still in git history), marked
it SHELVED in TODO.md so it isn't re-investigated.

### Now active — Physical Assessments & PA Follow-Ups (requested 2026-07-20)
A separate EMR case type. The "Select Assessment Type" modal has ~8
`assessment-type-container` tiles (Coaching Encounter is one; the assessments are the
rest). Plan: the earlier **"start + first screen only"** approach (PLAN.md Gap B) —
pick the tile, fill the shared first screen, Save in progress, Dane finishes the
assessment-specific screens. Same build pattern: **capture the form → map fields →
wire → prove on one draft.** Open scoping questions for Dane: exact tile labels, the
data source (`pa_follow_ups.csv`? the builder? dictation?), and how much to fill.

### Committed this session (branch `replace-copilot-intake-with-encounter-builder`)
`31b3d8d` Copilot removal + builder · `62bb892`/earlier bug fixes · `fa894b1` per-person
dept/div · `04a09c0` UI overhaul. The `--capture-addmore` tool + these doc updates are
the latest commit.

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
