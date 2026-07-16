# AI Examiner v0.5.0 RC1 项目状态

## 发布状态

- 版本：`0.5.0rc1`
- 分支：`develop/v0.5.0`
- 候选标签：`v0.5.0-rc.1`
- 稳定生产版本：`v0.4.1`
- 阶段：Adaptive Cognitive Engine feature freeze / staging validation

RC1 不会自动替换生产 `main`。通过真实材料、迁移备份和人工抽样验收后，才合并并发布 `v0.5.0`。

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

## 验证结果

```text
pytest                         27 passed
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

Dockerfile 和 Compose 已更新，但当前测试机 Docker daemon 不可用，RC1 的实际镜像构建与 staging 启动仍是部署验收项。

## RC 限制

- 实时语音中的提问仍由 Realtime 会话执行；RC1 在会后用最终转录形成权威认知状态。实时逐轮策略接管属于 v0.6。
- 内置策略基准是确定性合成评测，不替代 5 篇以上冻结 Golden Dataset 与人工盲评。
- SQLite 适合单机评估；多用户并发仍计划迁移 PostgreSQL。
- Learner Subject 在 RC1 中使用匿名外部键，不是正式账户系统。

## 最终 v0.5.0 发布前

1. 在 staging 从 v0.4.1 数据副本升级并启动 Docker Compose；
2. 使用至少 5 篇冻结数据集运行 fixed/adaptive 成对评测；
3. 抽样检查至少 20 个自适应决策；
4. 验证备份、恢复和固定策略回退；
5. 修复 RC 问题后合并 `main` 并创建不可变 `v0.5.0` 标签。
