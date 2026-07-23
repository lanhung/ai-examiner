# v0.8 Reviewed Built-in Scenarios

Date: 2026-07-23

Branch: `develop/v0.8.0`

## Catalog

| Slug | Scenario | Mode | Assistance | Aggregate | Disclaimer |
|---|---|---|---|---|---|
| `academic.thesis_defense` | Thesis defense practice | defense | bounded | weighted total | practice only |
| `academic.grant_review` | Grant review practice | defense | bounded, no hints | weighted total | human review |
| `education.course_oral` | Course oral practice | teaching | teaching | weighted total | practice only |
| `engineering.technical_interview` | Technical interview practice | interview | none | weighted total | not employment decision |
| `enterprise.product_knowledge` | Product knowledge training | teaching | teaching | weighted total | human review |
| `enterprise.sales_objection` | Sales objection practice | teaching | bounded | no total | human review |
| `operations.project_review` | Project review facilitation | interview | bounded, no hints | no total | human review |

The thesis-defense identity retains immutable `1.0.0`, `1.1.0` and `1.2.0`
versions. The other six identities begin at `1.0.0`. Startup seeding is
idempotent and published built-in source or fingerprint drift is fatal.

## Behavioral distinction

Every intended-distinct pair is compared over these runtime dimensions:

```text
objectives
question taxonomy
selection and difficulty
assistance and disclosure
conversation actions
assessment weights and aggregate
report sections and disclaimer
presentation role and style
compatibility mode
```

The automated gate requires at least three dimensions to differ for every pair.
This prevents a catalog made from cosmetic role-name changes.

## Safety

All built-ins:

- require human review;
- forbid protected-trait inference;
- forbid personality or emotion scoring;
- avoid named employers, institutions and individuals;
- do not provide medical diagnosis;
- retain answer and rubric evidence for scored dimensions.

Technical interview practice is a high-risk training template. It forbids
automatic employment decisions, provides no hints or corrections during the
assessment and uses a training-only employment disclaimer.

Sales objection and project review are coaching/facilitation scenarios. They
intentionally omit a total score while retaining objective scores, dimension
scores, evidence, strengths, weaknesses and recommendations.

## Verification

```text
Built-in source files             9
Template identities               7
Valid compiled artifacts          9
Invalid artifacts                 0
Pairwise runtime distinction      >= 3 dimensions
Targeted built-in tests           30 passed
Full test suite                    109 passed
```

This catalog is source-controlled and reviewed. Public marketplace installation,
remote executable plugins and automatic high-impact decisions remain outside
v0.8.
