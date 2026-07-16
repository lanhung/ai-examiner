# AI Examiner v0.4.0 项目状态

## 发布状态

- 版本：0.4.0
- 阶段：Realtime Voice Beta
- 部署：Vultr + Docker Compose
- 主要运行模式：文本、多模态证据、实时语音

## 已完成

- WebRTC 实时双向语音；
- OpenAI Realtime 后端 SDP 代理；
- 标准 API Key 不进入浏览器；
- semantic VAD；
- WebRTC barge-in；
- 实时字幕；
- 按住说话备用模式；
- VoiceSession / VoiceEvent 数据表；
- 语音转录同步到原 ExamSession Turn；
- 首次响应延迟、中断、错误和会话时长指标；
- Caddy HTTPS Compose；
- Vultr GitHub 更新脚本；
- 14 项自动化测试；
- 86% 总体代码覆盖率；
- Ruff 与 JavaScript syntax check 通过。

## 未在本环境验证

未使用用户真实 API Key 发起付费 Realtime 通话。因此最终公网语音质量、账户模型权限、实际费用和端到端延迟需在用户 Vultr 环境验证。

## 下一步

- 根据真实会话测量 VAD 误判率、首次语音延迟和插话成功率；
- 将完整语音转录交给 Analyzer/Evaluator 生成会后评分；
- 增加会话录音可选项和明确同意机制；
- v0.5 引入跨会话知识状态和自适应选题。
