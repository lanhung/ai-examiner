# Changelog

AI Examiner 的重要变更记录在此文件。版本号遵循 Semantic Versioning；开发版本使用 PEP 440 标识，例如 `0.5.0.dev0`。

## [Unreleased]

### Planned for 0.5.0

- Evidence-backed Knowledge State。
- Adaptive Question Selector 与 Difficulty Controller。
- 可审计的 Adaptive Decision 记录。
- `fixed` / `adaptive` 会话策略切换与对照评测。
- Knowledge Map、Weakness Map 和 Improvement Path 报告。

## [0.4.1] - 2026-07-16

### Added

- 蓝图生成可独立选择 OpenAI、Anthropic、Gemini 或 Ollama 模型。
- 文本答辩可独立选择模型，不再与蓝图生成模型绑定。
- AutoDL/Vultr Docker 部署持久化 Ollama 模型目录。

### Changed

- 将当前已部署、已验证的 v0.4 系列快照正式固化为可追溯版本。

## [0.4.0] - 2026-07-10

### Added

- OpenAI Realtime WebRTC 实时语音答辩。
- Semantic VAD、用户插话、实时字幕和按住说话模式。
- PDF/PPTX/DOCX 多模态证据、Golden Dataset 与 Benchmark。
- Redis/Celery 后台任务、Caddy HTTPS 和 Docker Compose 部署。

[Unreleased]: https://github.com/lanhung/ai-examiner/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/lanhung/ai-examiner/compare/9327580...v0.4.1
[0.4.0]: https://github.com/lanhung/ai-examiner/commit/9327580
