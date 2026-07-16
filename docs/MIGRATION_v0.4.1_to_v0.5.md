# v0.4.1 升级到 v0.5.0 RC1

## 1. 原则

- 先备份 `.env` 和 `data/`；
- 不执行 `docker compose down -v`；
- RC 部署使用独立目录、端口或 staging 机器；
- 生产 `main` 在最终验收前保持 `v0.4.1`。

## 2. Schema 变化

`exam_sessions` 新增：

```text
learner_subject_id
question_strategy
policy_version
asked_question_ids
```

新增表：

```text
knowledge_units
question_knowledge_units
learner_subjects
knowledge_states
knowledge_evidence_events
adaptive_decisions
```

迁移是 additive。旧会话默认 `fixed`，旧 `mastery_state` 继续保留。

## 3. Staging 部署

```bash
cd /opt
git clone https://github.com/lanhung/ai-examiner.git ai-examiner-v05-rc
cd ai-examiner-v05-rc
git checkout v0.5.0-rc.1
cp /opt/ai-examiner/.env .env
cp -a /opt/ai-examiner/data ./data
chmod 600 .env
```

为 staging 设置不同端口：

```bash
sed -i 's/^APP_PORT=.*/APP_PORT=8010/' .env
docker compose build --pull
docker compose run --rm --no-deps ai-examiner alembic upgrade head
docker compose up -d --remove-orphans
curl -fsS http://127.0.0.1:8010/health
```

## 4. 正式升级命令

最终版本合并到 `main` 后：

```bash
cd /opt/ai-examiner
USE_HTTPS=true DEPLOY_BRANCH=main ./deploy/update-from-github.sh
```

脚本执行：备份、拉取、在线构建、停服、迁移、启动、健康检查和日志摘要。

## 5. 手工升级

```bash
cd /opt/ai-examiner
./deploy/backup.sh
git fetch --tags --prune origin
git checkout main
git pull --ff-only origin main
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml down --remove-orphans
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm --no-deps ai-examiner alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
curl -fsS http://127.0.0.1:${APP_PORT:-8000}/health
```

HTTPS 部署为所有命令追加 `-f docker-compose.https.yml`。

## 6. 验证

```bash
docker compose ps
docker compose logs --tail=100 ai-examiner
docker compose run --rm --no-deps ai-examiner alembic current
curl -fsS http://127.0.0.1:${APP_PORT:-8000}/health
```

在网页创建一个 `fixed` 和一个 `adaptive` 会话，确认旧项目、旧报告、Golden Dataset 和语音记录可读。

## 7. 回退

最快行为回退：继续运行新代码，但使用 `fixed` 策略，不删除任何认知数据。

完整代码/schema 回退：

```bash
./deploy/backup.sh
docker compose down --remove-orphans
docker compose run --rm --no-deps ai-examiner alembic downgrade base
git checkout v0.4.1
docker compose up -d --build --remove-orphans
```

如任何步骤失败，优先恢复升级前备份。降级会删除 v0.5 认知表，必须先导出或备份。
