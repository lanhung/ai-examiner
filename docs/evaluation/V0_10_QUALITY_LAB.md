# v0.10 Quality Lab

Date: 2026-09-24

`ai-examiner-quality-lab` runs large, repeatable, multi-domain evaluations of the
whole examiner: question generation, follow-up behaviour, grading and cost,
across combinations of models. It answers one practical question: **which
planner × analyzer combination gives acceptable quality at the lowest cost per
learner session?**

## What it does

1. **Corpus.** 19 built-in study materials across 17 domains (high-school
   physics, biology, chemistry and mathematics, modern Chinese history,
   geography, networking, data structures, machine learning, nursing training,
   contract law, finance, economics, a fictional product sales manual, a lab
   safety SOP, learning science and research methods, plus two English
   materials). Add your own with `--corpus-dir` (Markdown with `id`, `domain`,
   `language` and `title` front matter).
2. **Blueprints.** For each material and each planner profile the lab uploads
   the material and generates a blueprint through the real HTTP API.
3. **Simulated learners with known ability.** Each blueprint is examined by
   seven personas:

   | Persona | Tier | Behaviour |
   |---|---|---|
   | `expert` | 3 | covers every expected point with reasons, an example and limits |
   | `partial` | 2 | one point, little justification |
   | `misconception` | 1 | confident, plausible, wrong over-generalisation |
   | `off_topic` | 1 | fluent answer about another subject |
   | `dont_know` | 1 | admits not knowing |
   | `bluffer` | 1 | impressive empty phrases |
   | `injection` | 1 | tries to instruct the grader to give full marks |

   The rule-based learner is free and deterministic. `--learner <profile>` makes
   expert/partial/misconception/off-topic answers come from an LLM told to stay
   in persona; the three adversarial personas always use fixed text.
4. **Full conversations.** Every persona goes through `/api/sessions`
   start → answers → report with the analyzer profile under test, including
   follow-ups.
5. **Independent judge.** A judge model, which never sees which system produced
   an artifact, rates every generated question (grounding, clarity, depth,
   expected-point quality, answer leakage, factual errors) and a sample of first
   answers (its own score, fairness of the system score, follow-up quality,
   whether the grader was manipulated). With `--judge mock:...` a deterministic
   heuristic judge is used; its numbers only prove that the pipeline works.
6. **Aggregation.** `summary.json` and `report.md` per run.

## Metrics

| Metric | Meaning | Good |
|---|---|---|
| Questions | mean judge rubric scaled 0–1, minus penalties for leaked answers and factual errors | high |
| Spearman | rank correlation between persona tier and the system's first-answer score | → 1 |
| False pass | share of tier-1 answers scored ≥ 3/5 | → 0 |
| Strong fail | share of expert answers scored < 2.5/5 | → 0 |
| Injection | share of injection answers that pass or that the judge flags as manipulation | 0 |
| Judge MAE | mean absolute difference between system and judge scores | low |
| Follow-ups | follow-up rate on partial minus on expert answers, plus judge follow-up quality | high |
| Reliability | share of blueprints and sessions that completed without error | ≥ 0.95 |
| $/learner session | analyzer cost per session + planner cost per blueprint ÷ `--learners-per-blueprint` | low |

`quality_index` = 0.30 × questions + 0.45 × grading + 0.15 × follow-ups +
0.10 × reliability.

A combination is **eligible** only if injection success ≤ 5 % and reliability
≥ 95 %. The report shows the Pareto frontier among eligible combinations and
recommends the cheapest one within `--tolerance` (default 0.03) of the best
quality index.

## Running

Offline, no keys (about one minute for the full corpus):

```bash
uv run ai-examiner-quality-lab run --out runs/offline
```

Real comparison, on a host whose `.env` holds the provider keys:

```bash
uv run ai-examiner-quality-lab run \
  --planner qwen:qwen-plus --planner openai:gpt-5.4-mini \
  --analyzer qwen:qwen-plus --analyzer qwen:qwen-turbo --analyzer openai:gpt-5.4-mini \
  --judge anthropic:claude-sonnet-5 \
  --learner qwen:qwen-plus \
  --judge-fraction 0.3 --repeats 2 \
  --price qwen:qwen-turbo=<input_usd_per_million>,<output_usd_per_million> \
  --max-cost-usd 30 \
  --out runs/2026-09-real
```

- `--max-cost-usd` is a hard stop covering system, judge and simulated-learner
  spend. Spend already recorded in the output directory counts.
- Results are appended to `results.jsonl` as each unit finishes; rerunning the
  same command resumes.
- `--shard i/n` splits materials across processes (each with its own `--out`);
  merge with `ai-examiner-quality-lab report runs/a runs/b --out runs/merged`.
- Models missing from `model_catalog.py` are counted as $0 and listed as
  unpriced; pass `--price provider:model=input,output` (USD per million tokens).
- The lab uses its own SQLite database in the output directory and widens the
  model policy there so that the models under test are allowed. It never
  touches the production database.
- Do not use a judge from the same model family as the systems under test;
  the CLI warns if the judge is also a planner or analyzer.

### Rough cost of a real run

Order-of-magnitude estimates only; check them against the first small run.

- One session (3 questions, ≤ 1 follow-up) makes about 4–6 analyzer calls of
  roughly 2–3k input and 0.5–1k output tokens.
- With `qwen-plus` catalog prices that is well under one US cent per session;
  the full corpus × 7 personas (133 sessions) costs cents per analyzer.
- The judge usually dominates: a frontier-class judge rating every first answer
  costs several times the systems under test. Use `--judge-fraction 0.2–0.3`.

Start with `--materials physics_newton_second_law --materials cs_tcp_handshake
--max-cost-usd 2` to calibrate, then run the full matrix.

### GitHub Actions

`.github/workflows/quality-lab.yml` runs the offline matrix every Sunday and on
demand. With repository secrets (`DASHSCOPE_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) the manual run accepts real profiles, a
judge, a price list and a budget; the report is written to the job summary and
the raw results are uploaded as an artifact.

## Interpreting the first offline run

The offline run on this branch (19 materials, 133 sessions, 756 answers, no
errors) already shows what the lab is for. The mock analyzer scores off-topic
answers (2.8/5) almost as high as expert answers (2.9/5) and scores the
injection attempt above the partial answer. That is expected of a length-based
mock. A real analyzer must beat it clearly. Pay particular attention to:

- off-topic and bluffing answers: the real pipeline caps them only when the
  model returns a low `question_relevance`; if a model omits the field the
  guard defaults to fully relevant (fail-open);
- injection answers: any combination that lets them pass is ineligible;
- strong-fail rate: a grader that gives expert answers under 2.5/5 will make
  motivated learners stop using the product.

## Recommended cadence

- Every pull request: the unit and integration tests in
  `tests/test_quality_lab_v010.py` (offline).
- Weekly: offline full matrix (scheduled workflow).
- Before changing a prompt or a default model, and monthly: a real run with a
  fixed seed matrix and budget. Keep the previous `summary.json` as the
  baseline, and block the change if the quality index drops by more than 0.03
  or injection success rises above 0.
