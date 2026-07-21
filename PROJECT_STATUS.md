# AI Examiner v0.7.0 Development Project Status

## Current development status

- Version: `0.7.0.dev0`
- Branch: `develop/v0.7.0`
- Work package: `WP-01 to WP-03 long-term memory foundation`
- Deployment: development evaluation only; stable/RC lines remain unchanged
- Release tag: not created

This increment adds opaque identity linking, memory controls, canonical concept
mappings and an idempotent evidence ledger without changing the live OpenAI or Qwen
media path. The inherited v0.5/v0.6 details below remain historical context.

## 发布状态

- 版本：`0.5.0rc4`
- 分支：`develop/v0.5.0`
- 候选标签：`v0.5.0-rc.4`
- 稳定生产版本：`v0.4.1`
- 阶段：Adaptive Cognitive Engine feature freeze / staging validation

RC4 不会自动替换生产 `main`。通过真实材料、迁移备份和人工抽样验收后，才合并并发布 `v0.5.0`。

## 已完成

- 6 张认知引擎数据表及 4 个兼容会话字段；
- Alembic 全新建库、v0.4.1 升级、降级和再次升级；
- Knowledge Unit 与 Question Mapping；
- append-only Knowledge Evidence Event；
- 掌握度、置信度、误区状态、辅助惩罚和确定性重建；
- 匿名 Learner Subject 与跨会话知识点聚合；
- Difficulty Controller 与 Adaptive Question Selector；
- 已问题目排除、历史题目新颖度、前置知识和确定性排序；
- 每次决策保存候选分、原因、权重和策略版本；
- `fixed` 模式完整兼容；
- Knowledge Map、Weakness Map、Improvement Path 和原始证据；
- 固定顺序与自适应策略成对基准 API；
- 自适应语音最终转录进入统一认知更新管线；
- 更新脚本先在线构建，再短暂停服迁移与切换。
- DashScope `qwen-plus` 云端文本 Provider；
- DashScope `qwen3-vl-plus` 页面、图表、表格和公式视觉 Provider；
- 文本、视觉与 Realtime 语音三条千问链路共用服务端密钥；
- 独立视觉模型选择器和实际视觉模型审计记录。

## 验证结果

```text
pytest                         29 passed
coverage                       87%
adaptive selector coverage     95%
cognitive service coverage     93%
policy benchmark coverage      98%
ruff                           passed
JavaScript syntax              passed
git diff --check               passed
v0.4 -> v0.5 migration         passed
v0.5 -> base downgrade         passed
base -> v0.5 re-upgrade        passed
```

Dockerfile 和 Compose 已更新。RC4 需要在远程 staging 使用真实 DashScope 配置完成一页视觉审查，再进入最终 v0.5.0 验收。

## RC 限制

- 实时语音中的提问仍由 Realtime 会话执行；RC4 在会后用最终转录形成权威认知状态。实时逐轮策略接管属于 v0.6。
- 内置策略基准是确定性合成评测，不替代 5 篇以上冻结 Golden Dataset 与人工盲评。
- SQLite 适合单机评估；多用户并发仍计划迁移 PostgreSQL。
- Learner Subject 在 RC4 中使用匿名外部键，不是正式账户系统。

## 最终 v0.5.0 发布前

1. 在 staging 从 v0.4.1 数据副本升级并启动 Docker Compose；
2. 使用至少 5 篇冻结数据集运行 fixed/adaptive 成对评测；
3. 抽样检查至少 20 个自适应决策；
4. 验证备份、恢复和固定策略回退；
5. 修复 RC 问题后合并 `main` 并创建不可变 `v0.5.0` 标签。
