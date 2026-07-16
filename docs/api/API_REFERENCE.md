# v0.3 API Reference

交互式文档：`/docs`。

## Documents

### Upload

```http
POST /api/projects/{project_id}/documents
Content-Type: multipart/form-data
```

响应新增：

```json
{
  "document_kind": "pdf|presentation|document|text",
  "page_count": 8,
  "evidence_count": 93
}
```

### Evidence index

```http
GET /api/documents/{document_id}/evidence?kind=page&page=3
```

### Evidence file / highlight

```http
GET /api/evidence/{asset_id}/file
GET /api/evidence/{asset_id}/highlight
```

## Visual analyses

```http
POST /api/documents/{document_id}/visual-analyses
```

```json
{
  "profile": "openai:gpt-5.4-mini",
  "max_pages": 10,
  "asynchronous": true
}
```

异步响应包含 `job`；查询：

```http
GET /api/jobs/{job_id}
```

## Joint analysis

```http
POST /api/projects/{project_id}/joint-analyses
```

```json
{
  "document_ids": ["paper-id", "slides-id", "supplement-id"],
  "profile": "anthropic:claude-sonnet-5"
}
```

## Dataset lifecycle

```http
PATCH /api/golden-datasets/{dataset_id}/status
```

```json
{"status": "frozen"}
```

差异：

```http
GET /api/golden-datasets/{left_id}/diff/{right_id}
```

## Prompt registry

```http
GET  /api/prompts
POST /api/prompts
POST /api/prompts/{prompt_id}/activate
```

## Provider and cost

```http
GET /api/provider-health
GET /api/costs
GET /api/costs?project_id=...
```

`GET /api/providers` includes `supports_vision`. RC4 adds the profiles below:

```text
qwen:qwen-plus       DashScope text and structured output
qwen:qwen3-vl-plus   DashScope page and chart visual review
```

The browser receives readiness and model metadata only. `DASHSCOPE_API_KEY` remains server-side.

# v0.4 Realtime Voice API

## GET `/api/voice/config`

返回 Realtime 模型、可用声音、默认 VAD 和 HTTPS 要求。不会返回 API Key。

## POST `/api/voice/sessions`

```json
{
  "project_id": "...",
  "blueprint_id": "...",
  "mode": "defense",
  "language": "zh-CN",
  "voice": "marin",
  "vad_eagerness": "medium",
  "question_limit": 6,
  "max_followups": 2
}
```

创建关联的 `ExamSession` 和 `VoiceSession`。返回结果不包含完整系统 instructions。

## POST `/api/voice/sessions/{id}/sdp`

请求体为 `application/sdp`。后端把 SDP 和受保护的会话配置发送到 OpenAI `/v1/realtime/calls`，并把 SDP answer 原样返回浏览器。

标准 OpenAI API Key 永远不返回浏览器。

## POST `/api/voice/sessions/{id}/events`

保存浏览器收到的转录和指标事件：

```json
{
  "event_type": "transcript",
  "role": "user",
  "text": "我的回答……",
  "latency_ms": null,
  "raw": {"item_id": "..."}
}
```

用户和助手 transcript 会同时保存为原 `ExamSession` 的 `Turn(kind=voice_transcript)`。

## GET `/api/voice/sessions/{id}`

返回会话配置摘要、状态、指标和事件时间线。

## POST `/api/voice/sessions/{id}/complete`

```json
{"reason": "user_ended"}
```

结束 VoiceSession 和关联 ExamSession，并记录会话时长。

# v0.5 Adaptive Cognitive API

## POST `/api/sessions`

新增可选字段：

```json
{
  "question_strategy": "adaptive",
  "learner_subject_key": "pseudonymous-learner-001"
}
```

`question_strategy` 可为 `fixed` 或 `adaptive`。为保持兼容，API 默认 `fixed`。`learner_subject_key` 仅在同一项目内唯一，不应写入姓名、邮箱或其他直接身份信息。

## GET `/api/sessions/{id}/knowledge-state`

返回知识单元、题目映射、掌握度、置信度、误区、算法版本和每个知识点对应的 Evidence Event、原始回答片段及辅助等级。

## POST `/api/sessions/{id}/knowledge-state/rebuild`

从 append-only Evidence Event 确定性重建 aggregate state。该接口用于评测和修复；未来多用户版本必须限制为管理权限。

## GET `/api/sessions/{id}/adaptive-decisions`

返回每次策略动作、目标难度、候选分、选择原因、策略权重、策略版本和关联 Turn。

## GET `/api/subjects/{id}/knowledge-state`

按 Knowledge Unit code 聚合同一匿名学习者的跨会话状态。

## GET `/api/subjects/{id}/learning-history`

返回最多 500 个历史 Evidence Event，包括会话、问题、观察值、证据权重、辅助等级、误区和来源类型。

## POST `/api/blueprints/{id}/policy-benchmark`

```json
{"question_limit": 2}
```

对同一蓝图运行固定顺序和 `adaptive-v1` 的确定性成对合成基准，返回 important-gap discovery、waste rate、misconception response、策略权重和逐 profile 题目序列。

## v0.5 Voice fields

创建语音会话可增加：

```json
{
  "question_strategy": "adaptive",
  "learner_subject_key": "pseudonymous-learner-001",
  "analysis_profile": "openai:gpt-5.4-mini"
}
```

`analysis_profile` 指定会后处理最终转录的文本模型。自适应语音完成时，最终用户转录会进入统一 Analyzer/Evaluator/Knowledge State 管线。部分转录和 Realtime 模型自身判断不会直接更新认知状态。
