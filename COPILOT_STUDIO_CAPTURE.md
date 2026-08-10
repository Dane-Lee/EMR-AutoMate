# Floor Capture — Copilot Studio agent → builder → EMR

Dictate an encounter on the floor, on your phone, in the moment. It lands as a reviewed
row in the builder instead of living in your head until you're back at the PC.

Status: **design only**, nothing built. Written 2026-08-07.

## What this is and isn't

This is **capture**, not formatting. It solves the problem the builder genuinely can't:
holding fifteen encounters in your head across a shift, and the bespoke one-off encounter
that has no library template.

It is **not** the 2026-07-16 dictation intake. That one failed for two reasons that had
nothing to do with privacy: the round-trip was miserable, and the model guessed at
controlled values. The design rule below is what makes this different.

## The one architectural rule

**The model never emits a controlled value.**

Not coaching type, not detail checkboxes, not department, division, category, or shift.
It does exactly two things: extract the free-text description, and identify who you're
talking about. Everything else is either a deterministic lookup or your tap.

This matters because of *how* the agent gets roster data:

- **Knowledge source (WRONG).** Upload the roster as a file the agent grounds on. That's
  model retrieval — it reads, paraphrases, and can hallucinate a department. Same failure
  class that wrote `Choose "Other" | Job-Specific Coaching | EIS asked...` into 77 records.
- **Connector action (RIGHT).** The agent calls a Power Automate flow that runs an actual
  query against a roster table and returns that person's row. That's a database join. It
  cannot invent a shift.

Every EMR-controlled value comes from the matched roster row or from a button you press.
The model's output is confined to free text, which is the one thing it's actually good at.

## Components

**1. Roster table — Dataverse.**
Mirror of `roster.xlsx`: name, identifier, title, shift, work area, department, division.
Dataverse over SharePoint list because it gives real querying, row-level security, and
audit logging — all of which you want on a table of employee records.

**2. The agent — Copilot Studio, published to Teams.**
Teams mobile is the practical channel: dictation already works there and you're already
signed in on the floor. One topic, deliberately constrained — not free generative
orchestration, because determinism is the entire point.

Flow per utterance:
- extract person name(s) + description text (+ date if spoken, else today)
- call the roster lookup action for each name
- return an Adaptive Card to confirm
- on confirm, write rows to the pending table

**3. Name matching — mirrors `name_match.py`.**
The lookup returns 0, 1, or N matches. The agent does **not** fuzzy-match on its own.
- 1 match → proceed
- 0 matches → ask you, offer the nearest few from the table
- N matches → ask you to pick

Ambiguity is a question, never a guess. That's already the rule in `name_match.py` and it
should not get weaker just because the input is spoken.

**4. The confirmation card.**
Shows the matched person (name, title, shift — so a wrong match is obvious at a glance),
the description as transcribed and editable, and coaching type as a choice set with the
model's suggestion preselected but **not** committed. Detail checkboxes stay empty here;
they're picked in the builder where the valid-per-type list already exists.

Multiple people, one description → N rows, one card. That's the group case and it's the
common one.

**5. Pending table — Dataverse.**
Columns match the `encounters.csv` schema, plus `status`
(captured → confirmed → exported → drafted). Status is what stops double-entry.

**6. The bridge — Power Automate → CSV in OneDrive.**
A scheduled or button-triggered flow writes confirmed rows to a CSV in the OneDrive folder
that already syncs to your PC, then flips them to `exported`.

Chosen over a direct Dataverse API pull from local Python: no app registration, no client
secret to rotate, no auth failing mid-shift. The sync already exists and already works.
Revisit if the file round-trip proves flaky.

**7. Import into the builder — local Python.**
The builder reads the CSV and opens with those people pre-checked and their descriptions
filled. You review, adjust, and export `encounters.csv` exactly as you do now.

This is the load-bearing part: **captured rows re-enter the existing pipeline at the
builder, not at the EMR.** Every controlled value still passes through the same tables the
validator and the EMR driver use. Nothing captured on the floor reaches a medical record
without going through the checks that are already there.

## Division of work

**Yours (Copilot Studio / Power Platform):** Dataverse tables, the agent and its topic,
the two flows, Teams publish, whatever DLP policy IT requires.

**Mine (local Python):** the CSV import path in `encounter_builder.py`, schema validation
on the way in, dedup against `encounter_log.csv` so a re-import can't draft anyone twice.

`mobile_import.py` is the natural home for the import side — it was built as exactly this
bridge. Its raw-name printing was fixed in `31b3d8d`, so that prerequisite is met; what
it still needs is dedup and a non-destructive write (it overwrote `encounters.csv`
outright until 2026-08-10).

The split means I can build my half without ever seeing a record. The CSV is gitignored,
and I read it only through aggregate probes and redacted output, same as everything else.

## Open decisions

- **Roster sync.** How does Dataverse stay current with `roster.xlsx`? Manual re-import on
  roster changes is fine at first; a scheduled flow later. A stale roster means wrong
  departments, silently.
- **Date handling.** Is a captured encounter always dated today, or do you dictate encounters
  from earlier in the shift? Affects whether the agent needs to parse spoken dates.
- **Where descriptions come from.** Dictated verbatim, or does the agent try to match an
  existing library template? Start with verbatim — template matching is a guess.

**Settled, don't reopen:** PHI in Copilot is cleared. Dane confirmed with ATI IT before this
design existed (2026-08-07). The agent may hold real employee names and encounter text.
Claude's own PHI boundary is unchanged and unrelated — see `CLAUDE.md`.

## Phase 1 thin slice

Prove the risky part first, which is the roster lookup being deterministic:

1. Dataverse roster table, loaded once by hand.
2. Agent with the lookup action only — you say a name, it returns title/shift/department.
   No extraction, no writing, no card. Just: does it return the right row, every time,
   including for a nickname and for a duplicated surname?
3. Only if that holds, add extraction + the card + the pending table.
4. Then the bridge and the builder import.

Do not build the whole chain and then discover the lookup paraphrases.
