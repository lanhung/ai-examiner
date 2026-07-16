# AI Examiner v0.3.0 Release Notes

## Added

- PDF 页面 PNG、文本块 bbox、内嵌图片和图/表/公式上下文证据；
- PPTX 文本、图片、表格、备注和逻辑幻灯片预览；
- DOCX 标题、段落、表格、媒体和逻辑预览；
- EvidenceAsset API、页面文件和高亮裁剪；
- OpenAI/Claude/Gemini 多模态 Provider hook；
- Visual Evidence Agent；
- 多文档 Joint Analysis；
- Prompt Registry 与真正生效的 active Prompt；
- Golden Dataset 证据链接、生命周期和版本 Diff；
- Celery + Redis 后台任务；
- Provider health 和费用看板；
- Benchmark 混淆矩阵、variant 分项与 Bootstrap 95% CI；
- Vultr Docker Compose 三服务部署、日志轮转、备份、升级和回滚脚本；
- 12 项自动化测试。

## Compatibility

v0.2 API 保留。数据库只新增表，未修改旧列。

## Known limitations

- 扫描 PDF 无 OCR；
- PPTX/DOCX 预览不是高保真办公软件渲染；
- 公式仅做上下文识别；
- SQLite 默认单 Worker；
- 真实模型多模态质量和费用需在用户 API Key 下运行评测。
