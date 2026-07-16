# v0.3 Evaluation Plan

## 1. Engineering regression

- health and Provider registry;
- upload and parsing;
- blueprint/session/report;
- Golden Dataset and export;
- Benchmark and expert calibration;
- Prompt injection resistance.

## 2. Multimodal ingestion

### PDF

- page count;
- page PNG readability;
- text block bbox existence;
- embedded image extraction;
- page map character ranges.

### PPTX

- slide count;
- title/body extraction;
- table extraction;
- image extraction;
- notes extraction;
- normalized shape coordinates.

### DOCX

- heading/paragraph extraction;
- table extraction;
- media extraction;
- logical preview.

## 3. Evidence quality

- page number accuracy;
- source excerpt match;
- evidence_asset_ids coverage;
- preview availability;
- highlighted crop generation.

## 4. Visual Agent

Compare at least two real providers on a fixed set of pages:

- factual observation accuracy;
- supported-claim precision;
- unsupported-claim recall;
- question relevance;
- hallucination rate;
- latency;
- cost.

## 5. Joint analysis

Use paper + PPT + supplement packages with known discrepancies:

- contradiction recall;
- false contradiction rate;
- omission recall;
- actionable-question quality.

## 6. Dataset engineering

- grounded rate;
- annotation completeness;
- unique-question rate;
- type coverage;
- evidence link rate;
- lifecycle correctness;
- diff correctness;
- frozen benchmark reproducibility.

## 7. Analyzer Benchmark

- label accuracy;
- Bootstrap 95% CI;
- coverage MAE;
- misconception detection;
- confusion matrix;
- excellent/partial/misconception/evasive breakdown.

## 8. Operations

- worker consumes queued jobs;
- failed jobs preserve errors;
- restart preserves data;
- backup archive is readable;
- restore starts healthy services;
- log rotation is configured.
