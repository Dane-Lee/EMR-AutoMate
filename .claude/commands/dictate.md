---
description: Take a dictated batch of encounters — organize it, write the descriptions, hand it to the builder
---

Dane is about to dictate a day's encounters. He talks; you sort, write what he asks you to
write, and hand back a batch he attaches names to in the builder.

Anything he passed after the command is the first item, or the shape of the batch: $ARGUMENTS

## What this is, and what it is not

**It is not the 2026-07-16 dictation intake.** That one took a transcript and let a model
choose controlled values out of prose, unreviewed, straight into records. Here:

- **He dictates.** There is no transcript, no audio, no third-party service. He is the
  source and he is in the room.
- **He sets the controlled values he has always set** — department, division and shift come
  off the roster, which you cannot see; date, encounter type, category and prompted-by are
  his, in the builder.
- **He reads every description before a browser opens.** The builder shows the batch in
  Review, and nothing is entered without him.

What you add is organizing and writing. Nothing else moved.

## What never crosses

Same boundary as everywhere else in this project, and dictation makes it easier to break
because he is talking fast:

- **No names.** Not first, not last, not a nickname, not "the new guy on second".
- **No location.** Not department, division, shift, or station-as-identifier. The builder
  fills those from the roster; you never need them and must not ask.
- **No dates of birth, badge numbers, or identifiers.**
- **No date tied to a person.** The batch's date is a batch fact he sets once.

If a name or a location lands in the dictation anyway, **do not repeat it back, do not
write it into the file, and do not build the ref around it.** Keep going with the ref
number. Say nothing about it — he wrote the rule, and stopping the batch to recite it back
costs him the thing this command exists to save.

## Refs are the whole mapping

**Every item gets a ref — 1, 2, 3 — assigned in the order he dictates it.** The ref is the
only link between what you wrote and who it belongs to, and the mapping lives on his side.
Never renumber a ref mid-batch, never sort the batch into a different order, and never
merge two items because they sound alike. If he corrects item 3, it stays item 3.

## Resolving each description: use it, adapt it, write it

**In that order, every time.** Most encounters are ordinary and the library already covers
them; a fresh near-duplicate fragments the library and costs him a pick later.

1. **Use it.** Search `load_library()` — the workbook plus `library_additions.json` — for
   an entry that already says it. If one fits, the answer is that entry, named.
2. **Adapt it.** A library entry plus the specifics he just gave. Keep the entry's shape;
   change what he changed.
3. **Write it.** Only when nothing fits. Voice per `pa_templates.md` and
   `.claude/commands/write.md`: third person, `EIS` / `EE`, past tense, plain language,
   one to three sentences, each carrying a new fact.

**Anything adapted or written goes into the library** — `append_library_addition({tab,
label, text, hint?, from?})` in `encounter_builder.py`. An adapted entry carries `from`
naming what it came out of. That is what puts it in the builder's Library dialog under its
tab, so he can find it himself next time instead of asking for it again. Dane asked for
this on 2026-09-16.

## Controlled values

- **Coaching type** — propose it from the list in `COACHING_TYPE_UUIDS`. Never invent one;
  an off-list value is refused by the builder anyway.
- **Detail checkboxes** — Dane widened this rule on 2026-09-16: you may fill them from what
  he dictated, because he reads them on screen before entry. Only real options for that
  type (`ace.CHECKBOX_UUID_MAP`), never a label you made up.
- **Department, division, shift** — never. The roster has them and you do not.
- **Date, encounter type, category, prompted by** — his, in the builder.

## While he is dictating

Confirm each item in **one line**: `ref · coaching type · the description (or the library
entry's name)`. That is what lets him correct it in the moment, which is where every voice
rule in `pa_templates.md` came from.

Do not summarize the batch back to him as you go. Do not ask for the next item. Do not
explain what you did with the last one.

If he says "need a description, something about X", X is a note — write the description.
If he dictates the description himself, use his words as given.

## When he says "that's the batch"

Write `dictated_batch.json` in the project root:

```json
{"written": "YYYY-MM-DD",
 "rows": [{"ref": 1,
           "coaching_type": "Health/Wellness Coaching",
           "details": ["Hydration"],
           "description": "EIS and EE discussed ...",
           "library": "the entry it came from, or null"}]}
```

Then tell him, in one line, how many rows are waiting. In the builder, the bottom bar's
**From dictation (N)** button walks him through them one at a time: he picks the person for
each ref, the row lands as its own group with `[dictated #N]` in its label, and the file is
renamed once they're in so the same batch can't go in twice. Department, division and shift
come off the roster; date, encounter type and category come off the form.

**Assessments are not in this yet.** The entry engine only clicks the Coaching Encounter
tile; a dictated PA or HMA has nowhere to go until the assessment path is built. If he
dictates one, write the text with `/pa` and keep it out of the batch file.
