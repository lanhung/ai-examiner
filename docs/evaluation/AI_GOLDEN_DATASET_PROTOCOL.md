# AI-Curated Golden Dataset Protocol v0.3

## Pipeline

```text
Document + Evidence Index
  ├─ Annotator A
  ├─ Annotator B
  └─ Annotator C
        ↓
Cross-model adversarial critique
        ↓
Consensus synthesis
        ↓
Evidence linking
        ↓
Excellent / Partial / Misconception / Evasive answers
        ↓
Quality gates
        ↓
Candidate → Frozen dataset
```

## Required case fields

- question and type;
- difficulty and rationale;
- ideal answer;
- required points;
- follow-ups;
- common errors;
- three-level rubric;
- source excerpt and page;
- evidence asset IDs;
- page preview URL;
- source models and consensus reason;
- panel quality scores;
- four synthetic answer variants.

## Source policy

A case may be retained only when its source excerpt is present in extracted document text. v0.3 also tries to associate a page and matching region asset. A missing region link does not prove fabrication, but it lowers inspectability and should be reviewed before freezing.

## Independence policy

When possible, use different models for:

- candidate generation;
- critique;
- final consensus;
- benchmark judging.

Do not let one model's self-evaluation be the only quality signal.

## Lifecycle

- `ready`: automated gates passed;
- `needs_review`: automated gates failed;
- `candidate`: selected for controlled testing;
- `frozen`: stable regression reference;
- `deprecated`: retained for history but no longer current.

## Human calibration

Human experts do not need to write all labels. Sample 10–20% of cases for blind calibration and inspect cases where models strongly agree but experts disagree.
