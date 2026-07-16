# Vultr Docker Compose 部署

## 1. 服务器要求

建议最低：

```text
2 vCPU
4 GB RAM
30 GB disk
Ubuntu 22.04/24.04
Docker Engine + Compose plugin
```

大量 PDF 页面和多模型并行分析建议 8 GB RAM。

## 2. 解压并配置

```bash
unzip ai-examiner-mvp-v0.3.0.zip
cd ai-examiner-mvp-v0.3.0
cp .env.example .env
chmod 600 .env
nano .env
```

不要把 `.env` 提交到 GitHub。

## 3. 启动

```bash
docker compose up -d --build
docker compose ps
```

预期服务：

```text
ai-examiner   healthy
worker        running
redis         healthy
```

检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/provider-health
```

## 4. 外部访问

浏览器：

```text
http://SERVER_IP:8000
```

如果服务器本机 curl 正常、外部打不开，检查：

```bash
sudo ufw allow 8000/tcp
sudo ufw status
```

以及 Vultr Firewall 入站 TCP 8000。

测试期更安全的访问方式：

```bash
ssh -L 8000:127.0.0.1:8000 root@SERVER_IP
```

本地访问 `http://127.0.0.1:8000`。

## 5. 日志

```bash
docker compose logs -f --tail=200 ai-examiner
docker compose logs -f --tail=200 worker
docker compose logs -f --tail=200 redis
```

上传和普通 API 在 `ai-examiner` 日志；Golden/视觉/Benchmark 后台任务在 `worker` 日志。

## 6. 备份

```bash
./deploy/backup.sh
```

备份包含数据库、上传文件、证据图和导出，不包含 `.env`。

## 7. 升级

```bash
./deploy/backup.sh
./deploy/upgrade.sh
```

或：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 8. 恢复

```bash
./deploy/restore.sh data/backups/ai-examiner-YYYYMMDDTHHMMSSZ.tar.gz
```

恢复前会停止 Compose 服务。

## 9. 常见故障

### Web 正常，后台任务一直 queued

```bash
docker compose ps
docker compose logs worker
docker compose exec redis redis-cli ping
```

检查 `.env` 中是否错误覆盖 `REDIS_URL`。

### Worker 报 database locked

默认 Worker concurrency=1。不要自行提高 Celery 并发；需要并行时迁移 PostgreSQL。

### 页面图片占用空间

```bash
du -sh data/evidence
du -sh data/uploads
```

删除项目会清理数据库对象；当前版本建议定期手动清理失去数据库引用的旧证据目录。

### Provider 未配置

```bash
curl http://127.0.0.1:8000/api/provider-health
```

Gemini Key 留空只会显示 `missing_key`，不会阻止 OpenAI/Claude。

### 千问文本与视觉

RC4 起，千问云端文本、视觉和 Realtime 语音共用阿里云百炼密钥：

```env
MODEL_PROVIDER=qwen
DASHSCOPE_API_KEY=your-server-side-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TEXT_MODEL=qwen-plus
QWEN_VISUAL_MODEL=qwen3-vl-plus
QWEN_REQUEST_TIMEOUT_SECONDS=120
VISUAL_DEFAULT_PROFILE=qwen:qwen3-vl-plus
```

应用重建后检查：

```bash
docker compose up -d --build --remove-orphans
curl -fsS http://127.0.0.1:${APP_PORT:-8000}/health
curl -fsS http://127.0.0.1:${APP_PORT:-8000}/api/providers
```

`qwen:qwen-plus` 和 `qwen:qwen3-vl-plus` 均应显示 `ready: true`。不要把 `.env`、API Key、上传材料或运行数据库提交到 Git。
