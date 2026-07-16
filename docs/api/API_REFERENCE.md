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
