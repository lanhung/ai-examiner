# Golden Dataset 与 Prompt 版本管理

## 生命周期

```text
draft → candidate → frozen → deprecated
```

AI 自动质量门禁仍可能先产生：

```text
ready
needs_review
```

建议流程：

1. 自动生成；
2. Benchmark；
3. 少量抽查；
4. 标记 candidate；
5. 回归稳定后 frozen；
6. 新版本替代后 deprecated。

## 可复现记录

每个数据集记录：

- 文档 ID 和页数；
- Annotator/Critic/Consensus profiles；
- Prompt manifest；
- 调用延迟、Token、估算费用；
- 质量门禁；
- 每题证据资产 ID；
- 合成回答。

## Diff

Diff 比较：

- 新增问题；
- 删除问题；
- question；
- ideal_answer；
- required_points；
- followups；
- common_errors；
- 字段相似度。

## 发布规则

正式回归 Benchmark 只能使用 `frozen` 数据集。正在调 Prompt 时使用 `candidate`，避免基准不断漂移。
