# Physical Assessment templates

Reusable PA / PA Follow-Up templates, written to be used for many people and therefore
about no one. **No PHI belongs in this file** — no names, dates of birth, badge IDs, or
anything tied to an individual. If a template needs a person-specific detail, that detail
is a `[ bracket slot ]` Dane fills at entry time, not text saved here.

Built alongside the 2026-08-24 backlog. **Open questions and what is still needed from
Dane are at the bottom of this file.**

## Voice

Same as `EMR Easy Enter Worksheets.xlsx`: third person, `EIS` / `EE`, past tense,
they/their.

**Plain language, not clinical.** Dane's call, 2026-08-24: *"I'm not a doctor and I'm not
trying to sound like one. Think low level athletic trainer at best."* So:

| Don't write | Write |
|---|---|
| inversion-type mechanism | rolled their ankle inward |
| antalgic gait | walking with a limp / favoring the leg |
| ecchymosis | bruising |
| ATFL, proximal fibula, base of 5th metatarsal | outside of the ankle, [ specific spot ] |
| active ROM limited at end range | sore when moving it as far as it goes |
| relative rest | taking it easy on it |
| denied any work-related mechanism | said it did not happen at work |

**The second sentence is usually the one to cut.** Measured across the 2026-08-24 session:
the sentence Dane deletes is almost always an explainer of the form *"EIS reviewed how X
helps Y"* — restating the value of what the first sentence already said he did. State what
was covered and stop. If a second sentence adds a new fact (what the EE said, what
happened as a result), keep it; if it explains why the first sentence mattered, cut it.

**Keep it short — the limit is detail, not sentence count.** Multiple sentences are fine;
piling on explanation is what makes one too long.

**Keep it short.** Dane, 2026-08-24: a five-sentence wellness description was *"enormous
compared to what I need."* No sentence limit was given on purpose — match the workbook,
where real entries run one to three sentences. Offer a short version and a longer one
rather than one long one.

Name a body part in ordinary words. If a specific structure genuinely matters, Dane can
say so at entry — it does not get baked into a template.

## The 6 pages

| # | Page | Notes |
|---|---|---|
| 1 | Encounter Details | Identical to a coaching encounter's first screen — Date, Encounter Type, Department, Division, Category, Shift. Captured: `debug/20260810_115220_ASSESS_01_step1_form.html` |
| 2 | Symptom Details | Field order below. Templates here. |

**PA Follow-Ups use these same 6 pages** (Dane, 2026-08-24: *"nearly identical format as
the initial PA"*), so a template written for an initial assessment carries over.
| 3 | Root Cause Analysis | **Field names known** from Dane's intake template, 2026-08-24: Work Factors · ADL's · Postures · Faulty Behaviors · Suboptimal Human Movement Patterns. Types/options still unknown. |
| 4 | Red Flag Triage | **Field names known**: Red Flag Signs? · Red Flag Mechanism of Injury? · Red Flag Symptoms?. Still needs the source doc that defines the criteria. |
| 5 | Corrective Actions | **Mapped** from Dane's screenshots, 2026-08-24. Same page for PAs and follow-ups. Structure below. |
| 6 | Plan | _fields not yet supplied_ |

### Page 2 — Symptom Details, field order

1. **Incident Details** — free text
2. **Primary Complaint** — CONTROLLED
3. **Categorize Mechanism** — CONTROLLED
4. **Palpation Comments** — free text, exam findings
5. **Observation Comments** — free text, exam findings

### The voice rule is per field — Dane's samples, 2026-08-24

Plain language governs **Incident Details**, where Dane relays what the EE told him.
It does **not** govern the exam fields. Those are his own findings and they read like an
athletic trainer's notes: named muscles, ROM terminology, sentence fragments, no
`EIS checked…` preamble.

His own text, verbatim:

> **palpation** — Trigger points present in forearms extensors, brachioradialis, and
> bicep brachii muscles. Limited passive ROM in wrist extension.
>
> **observation** — EE experienced mild pain while trying to lift 15 lb. kettlebell when
> testing the capacity of the affected region.

Two things to take from that:

1. **Palpation is terse and anatomical.** Name the muscle or structure. State the finding
   as a fragment. Passive/active ROM limits belong here.
2. **Observation is functional capacity testing, not visual inspection.** What did the EE
   do, under what load, and what happened. Writing "no visible swelling, EE walked
   normally" misreads the field — that was the error before this was supplied.

### Page 5 — Corrective Actions

Mapped from screenshots Dane supplied 2026-08-24. **This page is identical for initial PAs
and follow-ups.** Unlike page 2, it is almost entirely a **Yes/No checklist**, not prose —
so "templating" it means recording Dane's usual answers, not writing text.

Every field marked ● below is **required** (red asterisk in the UI). An unanswered one
blocks the page.

#### Action Taken

| ● | Field | Type |
|---|---|---|
| ● | Ergonomic work station adjustments | Yes / No |
| ● | Job coaching specific to behaviors, postures noted above | Yes / No |
| ● | ADL coaching specific to risks listed above | Yes / No |
| ● | Reminded the employee of preventative job-specific mobility program | Yes / No |
| ● | Reminded the employee of preventative job-specific conditioning activities | Yes / No |
| ● | Educated employee on total health and wellness | Yes / No |
| ● | The employee is capable of performing all essential job tasks | Yes / No |

#### First Aid

| ● | Field | Type |
|---|---|---|
| ● | First Aid provided | Yes / No |
|  | Further Notes/Instruction to Employee | two checkboxes (below) |

The two checkboxes, verbatim:

- ☐ *Employee was advised to seek medical treatment immediately for any of the following:
  worsening or new symptoms, increased swelling or symptoms such as numbness or tingling*
- ☐ *Employee refused medical / MD / occupational center referral*

#### Conditional: protective recommendations

`The employee is capable of performing all essential job tasks` = **Yes** reveals a second
question:

> **Does the employee require any protective recommendations to perform their job tasks?**
> — Yes / No

**Yes** reveals a **free-text field** describing what those recommendations are. That is
the only free text found so far on page 5.

---

## 🚨 PROTECTIVE RECOMMENDATIONS ARE NOT RESTRICTIONS

Dane, 2026-08-24: *"ATI is quite insistent that we get this distinction crystal
f***ing clear and not mess it up so that we don't have OSHA work-restriction issues."*

A **restriction** is a limit on what an employee may do; it carries OSHA recordability and
work-restriction consequences. A **protective recommendation** is a suggestion the employee
may adopt. Writing one as the other creates a compliance problem for ATI and for the
employee. **This is the highest-stakes text in the whole assessment.**

### The pattern, derived from Dane's approved tab

Every entry in the workbook's `Protective Recommendations` tab uses a permissive verb plus
a feasibility softener:

| Verb | Softener |
|---|---|
| Encourage | as workflow allows |
| Promote | when feasible |
| Allow | during natural pauses in the work process |
| Consider | brief / periodic / as able |

His approved text, verbatim, for reference:

> Encourage attention to body mechanics to minimize stress on the knees.
> Encourage periodic position changes as workflow allows to reduce knee strain.
> Promote use of supportive footwear and anti-fatigue measures during standing tasks.
> Allow brief movement or stretch opportunities during natural pauses in the work process.
> Consider strategies to vary tasks when feasible to support joint comfort.

### Never write these

Anything that **directs, limits, or sets a threshold** reads as a restriction:

- ❌ no lifting over / maximum of / not to exceed — any numeric limit
- ❌ restricted to / limited to / may not / must not / cannot / shall not
- ❌ required to / needs to / is to avoid — directives
- ❌ light duty, modified duty, work restriction — the terms themselves
- ❌ "unable to" anything — that is a capability finding, not a recommendation

The verb tells you which side of the line you're on. `Encourage` cannot be a restriction.
`Avoid` can be read as one. When unsure, don't write it — flag it for Dane.

### The tab is a grid, and it is mostly empty

Row 3 is a body-region header row: **Knees · Feet · Hips · Low Back · Upper Back · Neck ·
Face/Head · Shoulder · Elbow · Wrist · Hand**. Only the **Knees** column has content — the
other ten regions are blank.

#### ⚠️ Where does other narrative go?

**No free-text field is visible on this page.** "Further Notes/Instruction to Employee"
labels a box containing only those two checkboxes in the screenshot. Either the free-text
field sits outside the captured area, or this page genuinely takes no prose.

This matters for text like write-up `#4`'s gauze padding and prewrap intervention, which
was drafted for "Corrective Actions" and currently has nowhere to live. Unresolved — see
"Still needed from Dane". Do not assume a text field exists.

### Bracket slots are deliberate

`[ … ]` marks something only Dane can supply: a side, a measured finding, a spot that was
or wasn't sore. Palpation and observation are what he found on exam — never pre-filled
with plausible-sounding findings, because a guessed finding in a medical record is worse
than a blank one.

## Controlled vocabularies

Supplied by Dane 2026-08-24. **Pick only from these lists.**

### Primary Complaint

```
musculoskeletal acute            burn              fracture        general medical
musculoskeletal subacute         contusion         head injury     other
musculoskeletal chronic          dislocation       heat illness    none
abrasions/lacerations/punctures  foreign body
```

### Categorize Mechanism

```
caught on/in/between      fall from height          other                        slip/trip/fall
contact with sharp object foreign body              over exertion                struck against
exposure/thermal          insidious/unknown onset   prolonged position/posture   struck by
                                                    repetitive
```

#### Acute / subacute / chronic — Dane's rule, 2026-08-24

| Pick | When |
|---|---|
| `musculoskeletal acute` | Abrupt or sudden onset **and** within the last couple of days at most |
| `musculoskeletal subacute` | Less than 90 days **and/or** a less sudden onset |
| `musculoskeletal chronic` | Long duration — more than 90 days |

It is a timeline call, not a severity one: how long the EE has had it, not how bad it is.
Note that onset *character* matters alongside duration — a gradual ache that started
yesterday is subacute, not acute, because it wasn't sudden.

---

# Templates

## NWC-Initial — Rolled ankle, off-the-job recreation

**Incident Details**

> EE said they hurt their [ left / right ] ankle [ the night before / over the weekend /
> on {timeframe} ] while [ playing pickleball / recreational activity ]. EE said they
> were [ changing direction / stepping to the side ] when their ankle rolled inward and
> started hurting [ right away / later that evening ]. EE said it did not happen at work
> and was not related to their job. EE said they [ were / were not ] able to walk on it
> afterward.

**Primary Complaint** — `musculoskeletal acute`

**Categorize Mechanism** — `slip/trip/fall`

> Closest fit for a rolled ankle. If the EE planted and rolled it without stumbling or
> going down, `other` is the more honest pick — ask how it happened before choosing.

**Palpation Comments**

> Tenderness present over [ lateral malleolus / lateral ligaments ]. [ Mild / moderate ]
> swelling noted laterally. No tenderness over [ medial ankle / proximal fibula / base
> of 5th metatarsal ]. Limited [ active / passive ] ROM in [ inversion / eversion /
> dorsiflexion ].

**Observation Comments**

> EE experienced [ mild / moderate ] pain with [ weight-bearing / single-leg stance /
> walking ] when testing the capacity of the affected region. [ Bruising present /
> absent ]. Gait [ normal / favoring the involved side ].

## Follow-Up — Near-fainting / lightheaded episode, general medical

Bucket (`PWC` vs `NWC`) is **not preset**: PWC if the original episode tied to heat or
exertion at work, NWC if it is being worked up as a personal medical issue.

**Incident Details**

> EIS followed up with EE regarding the episode [ the week before / on {timeframe} ]
> where EE felt lightheaded and close to fainting. EE said they were feeling
> [ fine / … ] and had [ not had any further episodes / … ]. EE said they had spoken
> with their doctor and were [ scheduled to go in for further testing / … ]. EE said
> they would let someone know if it started happening again.

**Primary Complaint** — `general medical`

**Categorize Mechanism** — `insidious/unknown onset`

**Palpation Comments**

> [ N/A — no palpation performed ]

**Observation Comments**

> EE appeared [ alert and in no distress ]. EE was [ working their normal tasks / on
> light duty ] and reported no lightheadedness, dizziness, or other symptoms during the
> shift.

**Note:** a near-faint is exactly what page 4 Red Flag Triage screens for. That page
cannot be templated until the source doc is supplied.

## Follow-Up — General medical event, EE seen or seeing their own doctor

Covers the recurring shape: a non-musculoskeletal event (near-faint, low blood sugar,
dizziness), EIS checks back, EE is fine, has involved their own physician, no recurrence.
Bucket is **NWC** when it is being worked up as a personal medical issue, **PWC** if the
event tied to work conditions such as heat or exertion.

**Incident Details**

> EIS followed up with EE regarding the [ event ] [ the day before / the week before /
> on {timeframe} ] to see how they were feeling. EE said they were feeling
> [ fine / … ] and had not had another incident since. EE said they had spoken with
> their doctor [ timeframe ] and were [ going in for a physician assessment as soon as
> possible / scheduled for further testing / … ]. [ EE said they would let someone know
> if it started happening again. ]

**Primary Complaint** — `general medical`

**Categorize Mechanism** — `insidious/unknown onset`

**Palpation Comments**

> [ N/A — no palpation performed ]

**Observation Comments**

> EE appeared [ alert and in no distress ]. EE was [ working their normal tasks / on
> light duty ] and reported no [ symptoms / lightheadedness / dizziness ] during the
> shift.

## Page 5 — reusable Corrective Actions text

These back the required Yes/No items on the Corrective Actions page. They recur on nearly
every assessment, so they are written generic with a `[ slot ]` for the affected region.

Plain language applies here — this is narrative about what was covered, not exam findings.
Permissive phrasing is kept anyway given how close this page sits to the
protective-recommendation line.

### Educated employee on total health and wellness — ❌ REJECTED, needs rework

Dane, 2026-08-24: *"your total health and wellness info is terrible. we'll work on fixing
that later though."* **Do not reuse the drafts below.** They are kept only so the rework
starts from what was wrong rather than from nothing.

<details>
<summary>Rejected drafts</summary>

> EIS educated EE on total health and wellness, including the role of sleep, hydration,
> and nutrition in recovery and readiness for work tasks. EIS reviewed how staying
> consistent with activity and conditioning outside of work supports overall joint health.

> EIS educated EE on total health and wellness, including the role of sleep, hydration,
> and nutrition in tissue recovery. EIS reviewed how consistent conditioning supports
> recovery from minor injuries and reduces the chance of reinjury during activities at
> home and at work.

</details>

Rework with Dane when the backlog is clear — likely by having him describe what he
actually covers, rather than by guessing at wellness topics.

### Ergonomic work station adjustments

> EIS educated EE on ergonomic adjustments at their work station to reduce stress on
> [ the affected region ], including work height, reach distance, and tool and material
> positioning.

Hand / grip variant — **this is the version Dane used**, 2026-08-24:

> EIS educated EE on ergonomic adjustments to reduce stress on [ the hand and thumb ],
> including tool positioning, grip changes, and work height.

He kept the first sentence and dropped the trailing *"EIS reviewed how varying grip and
hand position through the shift helps reduce strain."* See the note on second sentences
in the voice section.

### Protective recommendations — hand / thumb

> Encourage attention to hand and thumb positioning to minimize stress on the thumb during
> gripping tasks. Encourage periodic changes in grip and hand position as workflow allows
> to reduce thumb strain. Promote use of supportive taping or padding during gripping tasks
> as tolerated. Allow brief movement or stretch opportunities during natural pauses in the
> work process. Consider strategies to vary tasks when feasible to support joint comfort.

### Protective recommendations — elbow / forearm

> Encourage attention to body mechanics to minimize stress on the elbow and forearm.
> Encourage periodic position changes as workflow allows to reduce forearm strain. Allow
> brief movement or stretch opportunities during natural pauses in the work process.
> Consider strategies to vary grip and hand position when feasible to support joint
> comfort.

## Page 4 — Red Flag Triage

Source: **`Red Flag Reference Sheet.pdf`**, supplied by Dane 2026-08-24. That document is
the authority; what follows is a transcription for quick matching, not a substitute.

### The decision rule, verbatim

> Observe for the following Red Flag historical and physical findings. **The presence of
> two or more of these signs and symptoms can indicate the need for outside care referral
> or immediate transfer for urgent or emergent care.**

### 🚫 What Claude does and does not do here

**Claude does not clear anyone.** Red-flag triage is a clinical screening decision with
transfer-and-referral consequences, made by the person who did the exam.

- ✅ **Surface matches.** When a scenario contains something that appears on these lists,
  say so and name the list item.
- ✅ **Count.** Note when two or more appear, since that is the referral threshold.
- ❌ **Never write "no red flags"** or fill these three fields as negative. An absence
  found by text-matching a description is not an absence found by examining a person.
- ❌ **Never infer.** Nothing here is derived from mechanism or diagnosis.

The three intake columns map one-to-one onto the three lists below: `Red Flag Signs?` →
Signs and Physical Findings · `Red Flag Mechanism of Injury?` → Mechanism of Injury ·
`Red Flag Symptoms?` → Symptoms.

### Red Flag Conditions

Cardiovascular and cerebrovascular disease (acute coronary syndrome, stroke) · Fractures
and high-grade tendon/muscle sprains/strains (significant partial and complete tears) ·
Nerve impingement and damage (peripheral, spinal) · DVT and pulmonary embolism ·
Infections (soft tissue, bone, spine, urinary tract, kidney, other) · Concussion and
traumatic brain injury · Compartment syndrome · Cancer · Other diseases

### Red Flag Signs and Physical Findings → column R

- Marked edema, ecchymosis, hematoma, joint effusions
- Soft tissue or bony deformities observed and/or palpated
- Point bony tenderness, especially on the spine, with other signs of possible fracture
- Guarded / loss of ROM
- Inability to bear weight, move, or use the affected body part
- Sensory loss, motor deficits, muscle atrophy
- Decreased, asymmetrical deep tendon reflexes
- Decreased and/or asymmetrical pulses, temperature, and color changes in extremity
  (vascular compromise and/or autonomic involvement)
- Tense, painful upper or lower extremity compartment, painful with movement
- Signs of infection: erythema, edema, calor, lymphangitis (red streaks)
- Red, swollen, and/or warm joints
- Symptom magnification

### Red Flag Symptoms → column T

- Chest pain, shortness of breath, dyspnea on exertion, chest pain radiating to jaw or
  shoulder/arm/upper back, nausea and vomiting, pallor, diaphoresis
- Loss of function and significant restrictions in range of motion
- Severe pain · worsening pain · intractable pain · chronic pain
- Increased/severe pain with movement or weight-bearing
- Loss of sensation, numbness, tingling, weakness, progressive neurological symptoms,
  loss of or changes in bowel/bladder function, loss of or changes in consciousness,
  mental status changes
- Calf pain, temperature/color changes in extremities
- Generalized weakness, malaise, pallor, nausea and vomiting, unexplained weight loss,
  fevers/chills/night sweats, loss of appetite — may suggest infection, cancer, or another
  serious condition
- Worsening symptoms unresponsive to first aid

### Red Flag Mechanism of Injury → column S

Fall from heights · High velocity/impact struck-by or struck-against trauma · Head
injuries · Whiplash type injuries · Falling on outstretched hand · Puncture or penetrating
wounds · Eye trauma · **Lacerations** · High pressure injection injury

### Consider potential PMH red flags as indicated

Heart disease · CVD · cancer · osteoporosis · hypertension · diabetes · blood
clots/bleeding disorders · anticoagulant Rx

### ⚠️ Matches in write-ups already drafted

Surfaced for Dane, not decided:

- **`#1` near-fainting** — *changes in consciousness* and, if present, *pallor* / *nausea*
  are on the Symptoms list; acute coronary syndrome and stroke head the Conditions list.
- **Wrist lacerations** (undated) — **`Lacerations` is named outright** on the Mechanism of
  Injury list. This one is a direct hit and warrants a deliberate page-4 pass.
- **`#4` forearm/palm burning pain** — *nerve impingement and damage* is a Red Flag
  Condition, and pain elicited by very light pressure sits near *symptom magnification*.
  Both are Dane's read, not a conclusion drawn here.

---

# Open questions — Dane's call

- [ ] **How is a rolled ankle coded when nobody fell?** `slip/trip/fall` is the closest
      fit, but an EE who planted and rolled it standing up did not slip, trip, or fall.
      `other` may be more honest. Once Dane rules, apply it to every rolled-ankle case
      instead of re-raising it. Same question will recur for any twist-without-fall.
- [x] ~~Acute vs. subacute cutoff~~ — **answered 2026-08-24.** Recorded in the
      Controlled vocabularies section above. Both existing write-ups were re-checked
      against it and were already correct.
- [ ] **Companion file for coaching descriptions?** The PA library exists because the
      workbook can't hold 5-field records. Ordinary coaching descriptions *do* fit
      `EMR Easy Enter Worksheets.xlsx` — but nothing is currently capturing the ones
      written in chat, so they're lost when the session ends. Offered 2026-08-24, not
      yet answered.

# Still needed from Dane

Templates for pages 3–6 can't be written without these. Page 2 is complete.

- [~] **Root Cause Analysis (page 3)** — five field names known from the intake template
      (Work Factors, ADL's, Postures, Faulty Behaviors, Suboptimal Human Movement
      Patterns). **Still needed:** are they free text or dropdowns, and the options if
      dropdowns. A screenshot settles it, the way Corrective Actions was settled.
- [x] ~~Red Flag Triage (page 4)~~ — **source doc supplied 2026-08-24**
      (`Red Flag Reference Sheet.pdf`), transcribed above with the two-or-more referral
      rule. Claude surfaces and counts matches; it never clears anyone and never writes
      these fields as negative.
- [x] ~~Corrective Actions (page 5)~~ — **mapped 2026-08-24** from screenshots.
- [x] ~~Does page 5 have a free-text field?~~ — **yes, but only one**, behind
      `capable of all essential job tasks` = Yes → `requires protective recommendations`
      = Yes. It takes protective-recommendation text only.
- [ ] **Where does other narrative go** — e.g. `#4`'s gauze padding and prewrap? Not page
      5. Page 6 Plan, or the **Notes** panel on the right edge of the screen.
- [ ] **Fill the other ten body regions** in the workbook's `Protective Recommendations`
      tab. Only Knees is written. Offered 2026-08-24.
- [ ] **Dane's usual Yes/No defaults for the 7 Action Taken items.** They're required on
      every PA, so a default set would make these near-automatic; only the exceptions
      would need thought.
- [ ] **Plan (page 6)** — field labels + any controlled lists. The closing/education
      paragraph drafted on 2026-08-24 was parked because it isn't known which page or
      field it belongs to.
- [x] ~~PA Follow-Up page shape~~ — **answered 2026-08-24: "a follow-up assessment
      follows a nearly identical format as the initial PA."** Follow-ups use the same
      6 pages and the same page-2 fields, so initial templates carry over.
- [ ] **What the "nearly" covers.** Dane said *nearly* identical, so something differs.
      Until it's named, follow-up templates are written to the initial shape and that
      difference is unaccounted for.

## What NOT to ask for

The scenarios themselves are fine to describe in chat — injury, body part, mechanism,
what was found, what was done. What never comes across: names, dates of birth, badge or
identifier numbers, or a date tied to a specific person. See `CLAUDE.md`.
