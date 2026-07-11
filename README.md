# AI Examiner v0.3.0

AI Examiner 是一个可部署的“主动提问型 AI”系统。它不是只回答用户问题，而是围绕论文、PPT、补充材料和技术文档主动提问、追问、纠错、评估，并把问题与原始证据页面关联起来。

v0.3.0 在 v0.2.0 的文本答辩、AI Golden Dataset 和多模型 Benchmark 之上，加入了**多模态证据工程、数据集/Prompt 版本、后台任务和生产级 Docker Compose**。

## v0.3.0 核心能力

### 多模态材料解析

支持：

- PDF：页面渲染、文本块、坐标、图注/表注/公式上下文、内嵌图片；
- PPTX：幻灯片文本、标题、表格、图片、演讲者备注和逻辑预览；
- DOCX：标题、段落、表格、媒体图片和逻辑预览；
- TXT / Markdown：文本与页面预览。

每个证据对象保存：

```text
document_id
page_number
kind
text
bounding_box
source metadata
preview/image path
sha256
```

### 视觉证据 Agent

OpenAI、Claude、Gemini 或 Mock Provider 可读取页面/幻灯片图片，输出：

- 可见内容摘要；
- 该证据支持什么；
- 该证据不能支持什么；
- 潜在图表、表格或论证问题；
- 页面专属答辩问题；
- 置信度。

### 多文档联合审查

同时比较论文、答辩 PPT、补充材料、项目申请书和审稿意见，识别：

- 表述一致性；
- 跨文档矛盾；
- PPT 遗漏的重要证据；
- 论文中没有支持的 PPT claim；
- 高风险答辩问题；
- 推荐修改动作。

### 数据集工程

保留 v0.2 的多模型独立标注、交叉批评、共识合成和四类测试回答，同时新增：

- 每题关联 `evidence_asset_ids` 和页面预览；
- 数据集 `draft / candidate / frozen / deprecated` 生命周期；
- 两个数据集版本的字段级差异；
- Prompt 版本清单进入数据集 provenance；
- Benchmark 混淆矩阵、分回答类型指标和 Bootstrap 95% 置信区间。

### Prompt Registry

Prompt 不再只是代码中的不可见常量。系统保存：

- Prompt 名称；
- 版本；
- Agent 角色；
- 内容；
- Schema；
- 状态；
- 元数据。

激活的新 Prompt 会参与后续 Agent 调用，并在数据集 provenance 中留下版本记录。

### 后台任务

Redis + Celery 支持：

- 多模型 Golden Dataset；
- 多页视觉分析；
- Planner/Analyzer Benchmark；
- 任务状态、进度、错误和结果查询。

为降低 SQLite 并发风险，默认 Worker 并发为 1。正式多人版本再迁移 PostgreSQL。

## 快速启动：Vultr / Docker Compose

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

浏览器访问：

```text
http://VULTR_PUBLIC_IP:8000
```

默认 Compose 启动三个服务：

```text
ai-examiner  FastAPI Web/API
worker       Celery background worker
redis        task broker/result backend
```

查看日志：

```bash
docker compose logs -f ai-examiner
docker compose logs -f worker
```

生产覆盖配置：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

完整步骤见 `docs/deployment/VULTR_DOCKER_COMPOSE.md`。

## API Key 配置

只把 Key 放在服务器 `.env`，不要写入 Git、ZIP、Dockerfile 或聊天记录：

```env
MODEL_PROVIDER=openai

OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini

ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-sonnet-5

GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash

GOLDEN_DEFAULT_PROFILES=openai:gpt-5.4-mini,anthropic:claude-sonnet-5
BENCHMARK_DEFAULT_PROFILES=openai:gpt-5.4-mini,anthropic:claude-sonnet-5
VISUAL_DEFAULT_PROFILE=openai:gpt-5.4-mini
```

Gemini Key 可以留空。系统会把它标记为 `missing_key`，不会阻止其他功能启动。

## 本地开发

```bash
cp .env.example .env
uv sync --extra dev --extra providers
uv run uvicorn ai_examiner.main:app --reload --host 0.0.0.0 --port 8000
```

测试：

```bash
uv run ruff check src tests
uv run pytest --cov=ai_examiner --cov-report=term-missing
node --check src/ai_examiner/static/app.js
```

## 主要 API

### 材料与证据

```text
POST /api/projects/{project_id}/documents
GET  /api/projects/{project_id}/documents
GET  /api/documents/{document_id}/evidence
GET  /api/evidence/{asset_id}/file
GET  /api/evidence/{asset_id}/highlight
POST /api/documents/{document_id}/visual-analyses
GET  /api/documents/{document_id}/visual-analyses
POST /api/projects/{project_id}/joint-analyses
```

### 数据集与 Prompt

```text
POST  /api/projects/{project_id}/golden-datasets
POST  /api/projects/{project_id}/golden-datasets/async
PATCH /api/golden-datasets/{dataset_id}/status
GET   /api/golden-datasets/{left_id}/diff/{right_id}
GET   /api/prompts
POST  /api/prompts
POST  /api/prompts/{prompt_id}/activate
```

### 任务、费用与 Provider

```text
GET /api/jobs/{job_id}
GET /api/projects/{project_id}/jobs
GET /api/provider-health
GET /api/costs
```

启动后访问 `/docs` 查看完整 OpenAPI。

## 升级 v0.2 → v0.3

v0.3 只新增数据表，没有修改 v0.2 的已有列。首次启动时 SQLAlchemy 自动创建新表，原项目、文档、答辩、Golden Dataset 和 Benchmark 会保留。

升级前仍建议备份：

```bash
./deploy/backup.sh
docker compose down
docker compose up -d --build
```

旧文档不会自动生成 v0.3 证据索引。重新上传旧材料，或通过后续 re-index 工具重新处理。

## 重要边界

- 扫描 PDF 暂未 OCR；页面图片会保留，但文字可能无法检索。
- PPTX 预览是基于元素的逻辑预览，不是 Microsoft PowerPoint 的像素级渲染。
- DOCX 分页依赖具体渲染器，因此当前按逻辑文档页处理。
- 公式识别目前是“公式上下文标记”，不是严格 LaTeX 解析或定理证明。
- 视觉模型可能产生误读，重要结论必须回看证据页面。
- SQLite + 单 Worker 适合当前评估；多人和高并发应升级 PostgreSQL/对象存储。
- 系统仍是训练和辅助评估工具，不应成为正式学位或招聘决策的唯一依据。

## 文档导航

- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/deployment/VULTR_DOCKER_COMPOSE.md`
- `docs/api/API_REFERENCE.md`
- `docs/evaluation/MULTIMODAL_EVIDENCE_PROTOCOL.md`
- `docs/evaluation/DATASET_VERSIONING.md`
- `docs/MIGRATION_v0.2_to_v0.3.md`
- `RELEASE_NOTES_v0.3.md`
- `PROJECT_STATUS.md`
