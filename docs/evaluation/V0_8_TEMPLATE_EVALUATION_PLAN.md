# v0.8 Scenario Template Evaluation Plan

## 1. Purpose

This plan determines whether a template changes the intended examiner behavior
without weakening evidence, assessment, safety, privacy or replay guarantees.

A template editor that saves YAML is not sufficient. Release evidence must show
that compiled templates are valid, distinct where intended, compatible with v0.7,
and invariant where the platform requires common behavior.

## 2. Research questions

1. Does the same source compile to the same canonical snapshot and fingerprint?
2. Can published versions reproduce completed session behavior after newer versions
   are created?
3. Do templates produce meaningfully different question, policy, scoring and report
   behavior rather than role-name changes?
4. Can overrides modify only explicitly permitted fields?
5. Do built-in and imported templates preserve evidence and safety invariants?
6. Does each initial template improve task relevance compared with the legacy
   thesis-defense behavior on that scenario?
7. Can text and voice sessions apply the same effective policy?

## 3. Evaluation layers

### 3.1 Structural validation

Use valid and invalid fixtures for every schema section. Assert:

- required fields, enums and types are enforced;
- unknown fields are rejected;
- recursive depth, item counts and string lengths are bounded;
- YAML tags, executable objects and unsafe aliases are rejected;
- all validation issues contain stable code, severity and JSON Pointer path;
- unsupported schema versions fail without partial compilation.

Gate: 100% expected result agreement for frozen schema fixtures.

### 3.2 Semantic validation

Fixtures cover:

- duplicate or dangling objective, dimension and report-section references;
- invalid weight sums and difficulty ranges;
- forbidden or unavailable policy actions;
- assistance that mislabels hinted performance as independent;
- missing evidence requirements for scored dimensions;
- high-risk intent without human review or disclaimer;
- contradictory override rules;
- missing required deployment capabilities.

Gate: zero invalid templates accepted in the frozen adversarial set.

### 3.3 Compiler determinism and lifecycle

Assert:

- canonical ordering and fingerprint are independent of YAML key order;
- repeated compilation is byte-equivalent;
- compiler version is included in every snapshot;
- published content cannot mutate through API, ORM or import paths;
- cloning creates a new draft and preserves provenance;
- deprecation leaves old sessions replayable;
- source plus compiler version reconstructs the stored compiled snapshot;
- session creation stores the exact effective policy and override audit.

Gate: 100% deterministic replay across supported SQLite and PostgreSQL test jobs.

### 3.4 Platform invariants

Every template must preserve:

- one main question at a time;
- evidence-bound scoring and source-answer traceability;
- independent versus assisted performance separation;
- no accent, voice, emotion, personality or protected-trait scoring;
- no template path into API keys, tools, file system or shell commands;
- no automatic persistence of unrestricted learner summaries;
- no automatic high-stakes decision;
- user ability to disable optional active interruption;
- current memory consent and deletion boundaries.

Gate: zero invariant violations across all built-in and adversarial templates.

## 4. Behavioral fixture matrix

Each built-in template receives at least these answer classes:

```text
excellent
partial
misconception
unsupported_claim
evasive
off_topic
user_question
explicit_uncertainty
prompt_injection
```

Each case declares:

```yaml
template_version:
objective:
question:
answer:
expected_action_set:
forbidden_actions:
expected_dimension_ranges:
required_evidence_fields:
expected_report_sections:
```

Policy tests are deterministic and do not require a paid provider.

## 5. Cross-template distinctness

Run the same neutral material and answer through scenario pairs. Expected differences
must be declared in advance.

Examples:

- thesis defense emphasizes contribution, evidence and limitations;
- oral teaching permits bounded hints and reports learning gain;
- technical interview practice emphasizes trade-offs and transfer;
- product training emphasizes factual coverage and safe escalation;
- sales roleplay evaluates discovery and objection handling without inventing claims;
- project review emphasizes decisions, risks, ownership and evidence.

Metrics:

```text
objective coverage delta
question taxonomy distribution
policy action distribution
assistance usage
dimension-weighted score delta
report-section difference
```

Gate: each pair intended to differ must differ in at least three runtime dimensions,
including one of policy or assessment. Visible role text does not count.

## 6. Scenario relevance evaluation

Create a frozen corpus with at least 30 cases per built-in template, balanced across
language, difficulty and answer quality. Compare:

```text
legacy thesis-defense configuration
new scenario template
```

Blind judges score:

- relevance to scenario objective;
- clarity and single-issue focus;
- discrimination between understanding and fluency;
- follow-up usefulness;
- rubric fit;
- report actionability;
- unsupported or unsafe behavior.

Initial candidate gate:

```text
mean relevance improvement >= 0.5 on a 5-point scale
high-quality question rate >= 80%
grounded question rate >= 95% where source grounding is required
single-main-question compliance >= 98%
unsafe or prohibited recommendation rate = 0 in frozen cases
```

Report confidence intervals and sample counts. Do not publish a winner from a tiny
sample or from a judge evaluating its own generated output alone.

## 7. Assistance and scoring integrity

For defense, teaching and training templates, replay matched independent and assisted
answers. Assert:

- hints never improve the recorded independent score;
- correction timing follows template policy;
- answer disclosure is blocked when forbidden;
- teaching can report learning gain without presenting it as initial mastery;
- dimension weights and aggregate method match the stored snapshot;
- reports quote the correct turn and source evidence;
- no scenario preference changes factual correctness scoring.

Gate: 100% aggregate recomputation equality for deterministic fixtures.

## 8. Override and capability evaluation

Test every override kind:

```text
locked
bounded
selectable
toggle with one-way restriction
```

Assert invalid overrides fail before session creation, valid overrides produce the
expected fingerprint change, and unavailable optional capabilities degrade visibly.
Missing required capabilities must block activation rather than silently fall back.

Gate: zero locked-field bypasses and zero silent provider/template substitutions.

## 9. Legacy compatibility

Replay the v0.7 fixed and adaptive suites through legacy template mappings.

Required results:

- existing request bodies remain valid;
- opening question, follow-up bounds and report scoring preserve expected behavior;
- text and voice paths agree on the effective template fingerprint;
- v0.7 reports remain readable;
- existing long-term memory imports are unchanged;
- database upgrade, downgrade and re-upgrade preserve pre-v0.8 rows.

Gate: no regression in the current 58-test suite plus new compatibility fixtures.

## 10. Security and adversarial evaluation

Inputs include templates attempting to:

- add system instructions or tell the model to ignore policy;
- define shell commands, Python modules, tools, URLs or HTML;
- disable evidence or human review;
- infer protected traits, emotion, personality or employability;
- exfiltrate documents, memory or keys through report fields;
- create exponential YAML aliases or oversized nested objects;
- reference unknown actions and report handlers;
- overwrite a published version;
- import a published lifecycle state;
- select another project's draft implicitly.

Gate: all attacks are rejected, escaped or isolated with no secret, identity or
cross-project leakage.

## 11. Usability and accessibility

Desktop and mobile browser checks cover:

- catalog filtering and selection;
- long multilingual labels;
- keyboard-only editing and publishing flow;
- validation issue focus and field association;
- clear risk, lifecycle and version display;
- effective-settings preview before session start;
- confirmation before publish or deprecate;
- no nested cards or overlapping controls;
- WCAG-oriented labels, focus states and contrast checks.

The editor must use structured controls for enums, booleans, numbers and registered
lists. Raw YAML is an advanced view, not the only authoring path.

## 12. Performance and cost

Deterministic validation and compilation should not call an LLM.

Candidate targets on the reference dataset:

```text
template list p95 < 300 ms
validate p95 < 500 ms for a 256 KB source
compile p95 < 500 ms
session snapshot binding p95 overhead < 100 ms
template compiler paid-model cost = $0
```

Provider calls record template slug, semantic version and fingerprint so cost and
quality can be segmented by scenario.

## 13. Release report

The v0.8 candidate report must include:

- app, template schema, compiler and validator versions;
- migration head and upgrade/downgrade results;
- built-in template versions and fingerprints;
- fixture counts and deterministic test results;
- per-template relevance and quality metrics;
- cross-template distinctness matrix;
- invariant, security and override results;
- legacy compatibility results;
- browser and Docker Compose verification;
- paid provider profiles, prompts, costs and latency when used;
- held gates, known limitations and rollback instructions.

## 14. Promotion gates

### Research to implementation

- ADR-005 accepted;
- schema and compiler contracts reviewed;
- one thesis-defense compatibility fixture compiles deterministically;
- built-in template list and prohibited-use boundary accepted;
- work packages have dependency order and rollback coverage.

### Implementation to release candidate

- all built-ins pass schema, semantic, invariant and security gates;
- legacy v0.7 regression passes;
- at least three templates pass scenario relevance evaluation;
- no published-version mutation path exists;
- session snapshots replay exactly;
- migration and Docker Compose gates pass.

### Final release

- Vultr staging upgrade and rollback rehearsal complete;
- real Qwen plus at least one independent provider sampled where configured;
- template editor and session selection pass browser acceptance;
- documentation and release artifacts contain no keys, user data or runtime files.
