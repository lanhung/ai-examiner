# Vultr Git Pull 更新命令

假设仓库位于 `/opt/ai-examiner`。第一次从 GitHub 部署：

```bash
cd /opt
git clone https://github.com/lanhung/ai-examiner.git
cd ai-examiner
cp .env.example .env
chmod 600 .env
nano .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 每次更新的推荐完整命令

```bash
cd /opt/ai-examiner

# 1. 保存数据
./deploy/backup.sh

# 2. 停止旧容器
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  down --remove-orphans

# 3. 拉取代码
git fetch --tags origin
git checkout main
git pull --ff-only origin main

# 4. 构建并启动
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --build --remove-orphans

# 5. 查看状态
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  ps

# 6. 健康检查
curl -fsS http://127.0.0.1:8000/health

# 7. 查看日志
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  logs -f --tail=100 ai-examiner
```

## HTTPS/语音版

```bash
cd /opt/ai-examiner
./deploy/backup.sh

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.https.yml \
  down --remove-orphans

git fetch --tags origin
git checkout main
git pull --ff-only origin main

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.https.yml \
  up -d --build --remove-orphans

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.https.yml \
  ps

curl -fsS https://你的域名/health
```

## 强制重新构建

正常升级不需要删除数据卷。遇到缓存问题：

```bash
docker compose build --no-cache ai-examiner worker
docker compose up -d --force-recreate
```

不要执行 `docker compose down -v`，除非明确希望删除 Redis 持久卷。应用的 SQLite 和上传数据位于宿主机 `./data`，仍应先备份。
