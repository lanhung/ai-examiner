# 开发 Agent 团队

这些文件是可直接交给 Codex、Claude Code 或其他代码 Agent 的角色约束。建议只并行运行 2–3 个开发 Agent，每个任务使用独立 Git worktree/branch，由 QA Agent 独立验收。

标准流程：

```text
Product Agent 写验收标准
→ Architect Agent 审核接口与边界
→ Backend / Frontend / Dialogue Agent 实现
→ QA Agent 运行测试和攻击案例
→ Evaluation Agent 运行行为评测
→ DevOps Agent 检查部署
→ Orchestrator 决定合并
```
