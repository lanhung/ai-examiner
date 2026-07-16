# AI Examiner v0.5.0 RC3

AI Examiner 是一个“主动提问型 AI”平台：围绕论文、PPT、DOCX 和技术材料主动提问、追问、纠偏和评估，并把问题与原始页面证据关联起来。

当前分支是 v0.5 Adaptive Cognitive Engine 的第三个候选版本。生产稳定版本仍是 `v0.4.1`；RC3 修复视觉审查错误响应与单机队列诊断，同时保留 RC2 的自适应认知能力和跨平台修复。

## v0.5 RC3 新增

- `fixed` / `adaptive` 双策略，旧客户端默认保持固定顺序；
- Knowledge Unit、题目映射和不可变 Knowledge Evidence Event；
- 掌握度、置信度、误区状态和跨会话匿名学习者历史；
- 确定性的 Difficulty Controller 与 Adaptive Question Selector；
- 每次选题保存候选分、原因、权重和策略版本；
- Knowledge Map、Weakness Map、Improvement Path 及原始回答证据；
- 固定顺序与自适应策略成对基准 API；
- Alembic 升级/降级与低停机 GitHub 更新脚本；
- 自适应语音会话结束后，仅使用最终转录更新知识状态。

## v0.4 核心功能

- OpenAI Realtime WebRTC speech-to-speech；
- 语义 VAD 自动判断用户是否说完；
- 用户可在 AI 说话时直接插话；
- WebRTC 自动截断未播放内容，保持对话自然；
- 实时用户与 AI 字幕；
- 麦克风回声消除、噪声抑制、自动增益；
- “自然对话”和“按住说话”两种模式；
- 语音会话、转录、首次响应延迟、中断次数和错误记录；
- PDF/PPTX/DOCX 页面证据和视觉分析；
- 多模型 Golden Dataset、Benchmark 和成本看板；
- Redis/Celery 后台任务；
- Caddy 自动 HTTPS 和 Vultr 一键升级脚本。
- 蓝图生成与文本答辩可分别选择 OpenAI、Anthropic、Gemini 或 Ollama 模型；
- AutoDL/Vultr 重启后保留已下载的 Ollama 模型。

## 快速启动

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

普通网页可访问：

```text
http://VULTR_IP:8000
```

但公网浏览器麦克风通常要求 HTTPS。语音测试可使用：

### SSH 隧道

```bash
ssh -L 8000:127.0.0.1:8000 root@VULTR_IP
```

本地打开：

```text
http://127.0.0.1:8000
```

### 域名 + Caddy HTTPS

`.env`：

```env
SITE_ADDRESS=exam.example.com
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
REALTIME_MODEL=gpt-realtime-2.1
REALTIME_VOICE=marin
REALTIME_VAD_EAGERNESS=medium
```

启动：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.https.yml \
  up -d --build
```

访问：

```text
https://exam.example.com
```

## 从 GitHub 升级

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

或：

```bash
USE_HTTPS=false ./deploy/update-from-github.sh
```

HTTPS 部署：

```bash
USE_HTTPS=true ./deploy/update-from-github.sh
```

## API Key

API Key 只放在服务器 `.env`。不要提交 `.env`：

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:14b
```

浏览器不会收到标准 OpenAI API Key。建立语音连接时，浏览器只把 WebRTC SDP 发给本系统后端，后端再访问 OpenAI Realtime API。

Ollama 模型走本机 HTTP API，不需要云端 API Key。先启动 `ollama serve`，并确保目标模型已存在，例如 `qwen2.5:14b`、`qwen2.5:7b` 或 `llama3.2:3b`。

## 开发与测试

```bash
uv sync --extra dev --extra providers
uv run ruff check src tests
uv run pytest --cov=ai_examiner --cov-report=term-missing
node --check src/ai_examiner/static/app.js
```

## 文档

- `docs/AI_EXAMINER_ENGINEERING_ROADMAP.md`
- `docs/VERSION_PLAN.md`
- `docs/architecture/V0_5_ADAPTIVE_COGNITIVE_ENGINE.md`
- `docs/evaluation/V0_5_EVALUATION_PLAN.md`
- `RELEASE_NOTES_v0.4.md`
- `RELEASE_NOTES_v0.4.1.md`
- `CHANGELOG.md`
- `docs/MIGRATION_v0.3_to_v0.4.md`
- `docs/deployment/VULTR_VOICE_HTTPS.md`
- `docs/deployment/VULTR_DOCKER_COMPOSE.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/api/API_REFERENCE.md`

## 当前限制

- 公网语音需要可信 HTTPS；
- 真实延迟取决于用户网络、Vultr 区域与 OpenAI Realtime 服务；
- 尚未提供用户登录和多租户隔离；
- 当前 SQLite 配置适合评估测试，生产多人版本应迁移 PostgreSQL；
- 语音答辩是训练辅助工具，不应作为正式学位或招聘决定的唯一依据。
