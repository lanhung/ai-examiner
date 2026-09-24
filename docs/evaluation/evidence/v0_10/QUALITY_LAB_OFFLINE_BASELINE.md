# AI Examiner quality lab report

- Blueprints: 19; sessions: 133; answers: 756
- System model cost: $0.00000; judge cost: $0.00000
- Quality index weights: {'questions': 0.3, 'grading': 0.45, 'followups': 0.15, 'reliability': 0.1}

> **Heuristic judge.** This run used the offline heuristic judge and/or mock models. The numbers prove the pipeline works; they do not rank real models.

## Recommendation

- Highest quality: `mock:heuristic-v2 × mock:heuristic-v2`
- Recommended (cheapest within 0.03 of best): `mock:heuristic-v2 × mock:heuristic-v2`
- Quality given up: 0.000; cost saving: –
- Eligibility: injection_success_rate <= 5% and reliability >= 95%

Pareto frontier among eligible combinations (no other is both cheaper and better):

- `mock:heuristic-v2 × mock:heuristic-v2`

## Combinations

| Combination (planner × analyzer) | Quality | Questions | Grading | Follow-ups | Reliability | Spearman | False pass | Strong fail | Injection | Judge MAE | $/learner session | p95 ms/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `mock:heuristic-v2 × mock:heuristic-v2` | 0.651 | 0.476 | 0.713 | 0.583 | 1.000 | 0.219 | 0.074 | 0.667 | 0.000 | 1.526 | $0.00000 | 33.000 |

### Mean first-answer score by simulated learner

| Combination | bluffer | dont_know | expert | injection | misconception | off_topic | partial |
|---|---|---|---|---|---|---|---|
| `mock:heuristic-v2 × mock:heuristic-v2` | 0.996 | 0.926 | 2.944 | 2.281 | 1.849 | 2.821 | 1.126 |

## By domain (all combinations pooled)

| Domain | Questions rated | Question quality | Leak rate | Factual errors | Grading | Spearman | False pass |
|---|---|---|---|---|---|---|---|
| Earth science | 6 | 0.479 | 0.000 | 0.000 | 0.689 | 0.129 | 0.133 |
| Software engineering | 6 | 0.469 | 0.000 | 0.000 | 0.697 | 0.129 | 0.133 |
| 中国近代史 | 6 | 0.479 | 0.000 | 0.000 | 0.718 | 0.237 | 0.067 |
| 企业产品培训 | 6 | 0.479 | 0.000 | 0.000 | 0.719 | 0.247 | 0.067 |
| 初中数学 | 6 | 0.479 | 0.000 | 0.000 | 0.715 | 0.237 | 0.067 |
| 地理 | 6 | 0.479 | 0.000 | 0.000 | 0.717 | 0.247 | 0.067 |
| 学习科学 | 6 | 0.479 | 0.000 | 0.000 | 0.715 | 0.237 | 0.067 |
| 实验室安全 SOP | 6 | 0.469 | 0.000 | 0.000 | 0.715 | 0.237 | 0.067 |
| 护理培训 | 6 | 0.469 | 0.000 | 0.000 | 0.716 | 0.237 | 0.067 |
| 数据结构 | 6 | 0.479 | 0.000 | 0.000 | 0.716 | 0.247 | 0.067 |
| 机器学习 | 6 | 0.479 | 0.000 | 0.000 | 0.718 | 0.247 | 0.067 |
| 民法 | 6 | 0.479 | 0.000 | 0.000 | 0.716 | 0.247 | 0.067 |
| 科研方法与论文答辩 | 6 | 0.490 | 0.000 | 0.000 | 0.715 | 0.237 | 0.067 |
| 经济学 | 6 | 0.479 | 0.000 | 0.000 | 0.716 | 0.247 | 0.067 |
| 计算机网络 | 6 | 0.458 | 0.000 | 0.000 | 0.719 | 0.247 | 0.067 |
| 金融基础 | 6 | 0.469 | 0.000 | 0.000 | 0.714 | 0.237 | 0.067 |
| 高中化学 | 6 | 0.479 | 0.000 | 0.000 | 0.716 | 0.237 | 0.067 |
| 高中物理 | 6 | 0.469 | 0.000 | 0.000 | 0.714 | 0.237 | 0.067 |
| 高中生物 | 6 | 0.479 | 0.000 | 0.000 | 0.718 | 0.237 | 0.067 |
