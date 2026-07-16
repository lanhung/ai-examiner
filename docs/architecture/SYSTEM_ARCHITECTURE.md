# AI Examiner v0.3 系统架构

## 1. 设计目标

v0.3 的目标是让问题、追问、评价和数据集案例都能追溯到原始材料中的页面或区域，同时保持 v0.2 API 和数据库兼容。

## 2. 容器架构

```text
Browser
   │ HTTP
   ▼
FastAPI API/Web ─────────────── SQLite + shared data volume
   │                                 │
   │ enqueue                         ├─ uploads
   ▼                                 ├─ evidence previews
Redis broker/result backend          ├─ exports
   │                                 └─ backups
   ▼
Celery worker (concurrency=1)
   ├─ Golden Dataset pipeline
   ├─ Visual evidence pipeline
   └─ Benchmark pipeline
```

## 3. 运行时 Agent

```text
Document Parser
  └─ Evidence Indexer
       ├─ page/slide preview
       ├─ text block + bbox
       ├─ image/table/formula context
       └─ source hash

Visual Evidence Agent
  └─ support / non-support / issue / question

Session Planner
Answer Analyzer
Policy Controller
Evaluator
Interviewer
Grounding Checker
Report Generator

Golden Annotator
Annotation Critic
Consensus Synthesizer
Synthetic Answer Generator

Joint Analysis Agent
  └─ paper ↔ PPT ↔ supplement consistency
```

## 4. 新数据表

### EvidenceAsset

页面、幻灯片、文本块、表格、图片、图注、表注和公式上下文。

### VisualAnalysis

视觉模型对一个页面证据的结构化分析。

### PromptVersion

Agent Prompt 的版本、内容、状态和元数据。

### BackgroundJob

异步任务状态、进度、结果和错误。

### JointAnalysis

多文档一致性审查结果。

v0.2 的表结构不变，因此现有 SQLite 数据可直接继续使用。

## 5. 文档解析

### PDF

PyMuPDF 完成：

- 页面 PNG；
- 文本块；
- PDF 坐标；
- 内嵌图片；
- 页宽页高；
- 图注、表注和公式上下文启发式分类。

### PPTX

python-pptx 完成：

- 文本框、标题；
- 图片；
- 表格；
- 演讲者备注；
- 元素相对坐标；
- 逻辑预览图片。

### DOCX

python-docx 和 OOXML ZIP 完成：

- 段落和标题；
- 表格；
- 媒体图片；
- 逻辑预览。

## 6. 证据链接

Golden Dataset 共识完成后，系统根据：

```text
source_page
source_excerpt
```

链接到：

```text
page EvidenceAsset
matching text EvidenceAsset
```

每个案例新增：

```json
{
  "evidence_asset_ids": ["..."],
  "page_preview_url": "/api/evidence/.../file"
}
```

## 7. Prompt 执行路径

```text
PromptVersion(active)
      ↓
prompt_contents()
      ↓
AgentContext.prompt_overrides
      ↓
BaseAgent._instructions(default + active override)
      ↓
Provider
```

这保证 UI/API 中激活的 Prompt 会影响后续运行，而不仅仅用于展示。

## 8. 后台任务

异步入口：

- `golden_dataset`
- `visual_document`
- `benchmark`

状态：

```text
queued → running → completed
                 ↘ failed
```

当前进度主要是阶段级，不是每个模型 token 的精细进度。

## 9. 安全边界

- 上传文件名规范化；
- 文件只通过数据库中的 EvidenceAsset 路径读取；
- 文档内容始终作为不可信数据；
- API Key 仅由环境变量读取；
- `.env`、证据、备份和上传目录均被 Git 忽略；
- Docker 日志轮转；
- Provider 缺 Key 时不会阻止应用启动。

## 10. 后续演进

v0.4 增加实时语音时，现有 EvidenceAsset、BackgroundJob、PromptVersion 和 Agent 状态机无需推倒重建。语音只新增媒体层与转录证据层。

# v0.4 Realtime Voice Architecture

```text
Browser / Mobile Browser
  ├── microphone MediaStream
  ├── RTCPeerConnection
  ├── remote audio track
  └── oai-events data channel
          │
          │ SDP offer only
          ▼
FastAPI /api/voice/sessions/{id}/sdp
          │ standard API key remains server-side
          ▼
OpenAI /v1/realtime/calls
          │
          └── SDP answer → Browser

After negotiation:
Browser microphone/audio ⇄ OpenAI Realtime over WebRTC
Browser transcript events → FastAPI → VoiceEvent + ExamSession Turn
```

## Latency design

- WebRTC rather than routing audio frames through FastAPI;
- semantic VAD to avoid fixed silence timeouts;
- audio output is played as a remote media track;
- user speech can interrupt model speech;
- short examiner prompt and one-question-at-a-time response policy;
- push-to-talk fallback for noisy environments.

## Trust boundary

- `OPENAI_API_KEY` is only read by FastAPI;
- the browser receives SDP answer, never the standard key;
- blueprint content is delimited as untrusted data inside voice instructions;
- transcripts are posted separately for durable evaluation;
- no recording is stored in v0.4, only text events and metrics.
