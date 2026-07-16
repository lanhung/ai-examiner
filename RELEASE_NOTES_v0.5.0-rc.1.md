# AI Examiner v0.5.0 RC1

发布日期：2026-07-16
候选标签：`v0.5.0-rc.1`
稳定基线：`v0.4.1`

## 版本目标

把文本和最终语音回答转换为可追溯的知识证据，并根据掌握度、置信度、重要性、误区、难度和新颖度选择下一题。

## 核心变化

### Evidence-backed cognitive state

- 蓝图问题映射到 Knowledge Unit；
- 每次完成的回答生成不可变 Evidence Event；
- aggregate state 可随时从事件重建；
- 辅助、提示和纠正会降低独立证据权重；
- 后续矛盾证据可以降低掌握度；
- 单次优秀回答不能直接形成高置信度“已掌握”结论。

### Adaptive policy

候选问题评分：

```text
0.30 knowledge_gap
+ 0.20 uncertainty
+ 0.20 importance
+ 0.15 misconception_priority
+ 0.10 difficulty_fit
+ 0.05 novelty
```

每个决策保存候选分、选择原因、策略权重和 `adaptive-v1` 版本。固定顺序仍可选，且旧请求默认 `fixed`。

### Cross-session learner state

`learner_subject_key` 是项目内匿名键。相同键的新会话会按知识点代码继承历史证据，降低已掌握内容与历史题目的优先级，并优先复测误区和高重要度薄弱点。

### Voice finalization

自适应语音会话结束后，只有最终用户转录进入 Analyzer、Evaluator 和 Knowledge State。Realtime 模型不能直接修改认知状态。实时逐轮策略接管保留到 v0.6。

### Operations

- 首次引入 Alembic；
- Docker 镜像包含迁移文件；
- GitHub 更新脚本先在线拉取和构建，停服窗口仅用于迁移和启动；
- 迁移支持 v0.4.1 升级、降级和再次升级。

## 验证

- `27 passed`；
- 总覆盖率 `87%`；
- Ruff、JavaScript syntax、compileall 和 `git diff --check` 通过；
- v0.4.1 数据哨兵在升级/降级往返后保留；
- 固定策略回归通过；
- 跨会话不重复优先、矛盾证据降分和语音证据落库均有自动测试。

## RC 验收边界

这是 staging 候选版本，不是正式 `v0.5.0`。真实 Docker 构建、5 篇以上冻结数据集成对评测、20 个决策人工抽样和真实 API/语音体验需要在 staging 完成。

## 回退

行为回退只需创建 `question_strategy=fixed` 会话。代码回退前必须备份；如需完整 schema 回退，执行 `alembic downgrade base`，详见迁移文档。
