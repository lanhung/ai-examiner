# v0.3 → v0.4 升级

v0.4 新增 `voice_sessions` 和 `voice_events` 两张表，不修改 v0.3 现有表列。SQLite 首次启动会自动创建新表。

## 推荐升级

```bash
cd /opt/ai-examiner
./deploy/backup.sh

docker compose down --remove-orphans
git fetch --tags origin
git checkout main
git pull --ff-only origin main

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

使用 HTTPS：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.https.yml \
  up -d --build --remove-orphans
```

## 一键升级

普通 HTTP/SSH 隧道：

```bash
USE_HTTPS=false ./deploy/update-from-github.sh
```

域名 HTTPS：

```bash
USE_HTTPS=true ./deploy/update-from-github.sh
```

## 回滚

```bash
docker compose down --remove-orphans
git checkout v0.3.0
docker compose up -d --build
```

v0.4 新表留在 SQLite 中不会影响 v0.3 读取旧表；严格回滚时可恢复升级前备份。
