# AI Examiner v0.5.0 RC4

发布日期：2026-07-16

RC4 将阿里云百炼千问接入统一模型网关：`qwen-plus` 用于蓝图生成、文本答辩、结构化分析、Golden Dataset 和 Benchmark，`qwen3-vl-plus` 用于 PDF/PPT 页面、图表、表格和公式视觉审查。原有 Qwen3 Omni Realtime 语音继续保留。

## 配置

```env
DASHSCOPE_API_KEY=your-server-side-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TEXT_MODEL=qwen-plus
QWEN_VISUAL_MODEL=qwen3-vl-plus
QWEN_REQUEST_TIMEOUT_SECONDS=120

MODEL_PROVIDER=qwen
VISUAL_DEFAULT_PROFILE=qwen:qwen3-vl-plus
```

同一个 `DASHSCOPE_API_KEY` 可供千问文本、视觉和 Realtime 语音使用。密钥只保存在服务器 `.env`，不会通过 `/api/providers`、视觉任务响应或前端 JavaScript 返回。

## 交互变化

- 文本答辩模型列表新增 `Alibaba Qwen Plus`；
- 页面证据区域新增独立“视觉分析模型”选择器；
- 视觉选择器只显示支持图片输入的模型；
- 使用千问视觉时，分析和费用记录明确标记 `qwen3-vl-plus`。

## 兼容性

没有数据库迁移。已有 `.env` 只需增加上述可选变量；原来的 OpenAI、Anthropic、Gemini、Ollama、Mock 和两种 Realtime 语音路径不受影响。

模型目录中的千问美元价格是按阿里云中国区公开人民币标准价做的近似换算，仅用于早期成本看板；实际账单以阿里云百炼控制台为准。
