# Dialogue Agent

负责 Planner、Analyzer、Policy、Evaluator、Interviewer、Grounding 和 Reporter 的行为。每个模型输出必须有 schema、边界、失败处理和行为评测。关键状态迁移优先使用确定性代码，不把全部控制权放进一个长 Prompt。
