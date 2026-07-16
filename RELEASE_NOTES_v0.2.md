# v0.2.0 Release Notes

v0.2 converts the original text examiner into a measurable model-development platform.

## Major additions

- AI-generated Golden Dataset with independent candidate models;
- round-robin adversarial critique and consensus repair;
- ideal answers, required points, follow-ups, common errors and rubrics;
- four synthetic answer levels per question;
- deterministic grounding and completeness gates;
- OpenAI, Claude and Gemini provider adapters;
- Planner and Answer Analyzer benchmarks with quality/cost/latency ranking;
- optional expert calibration endpoints;
- JSONL export;
- automatic 1–20 paper corpus builder CLI;
- upgraded web UI for model selection and benchmark results.

## Compatibility

v0.1 SQLite databases can be opened by v0.2; startup creates the new tables. Existing blueprint and session flows remain available.

## Known limitations

Real paid models were not called in the release environment because no user API keys were supplied. The adapters were installed and checked against the current SDK interfaces, while actual model quality, quota behavior and billed cost must be measured under the user's account.
