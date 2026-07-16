# AI Examiner v0.5.0 RC2

发布日期：2026-07-16
候选标签：`v0.5.0-rc.2`

RC2 保留 RC1 的 Adaptive Cognitive Engine 功能，并完成发布一致性与跨平台修复：

- 同步 `uv.lock` 中的 Alembic 依赖和候选版本；
- SQLite 备份源库与快照连接显式关闭，Windows 与 Linux 均可安全清理临时文件；
- JSONL 测试固定使用 UTF-8，不依赖操作系统默认编码；
- 本机 Mock staging 在 `0.5.0rc2` 代码上通过健康检查；
- 完整测试、Ruff、迁移往返和自适应策略冒烟测试保持通过。

RC2 仍仅用于 staging。生产 `main` 和 `v0.4.1` 不变，完成真实材料、Docker Compose、备份恢复与人工决策抽样验收后再发布 `v0.5.0`。
