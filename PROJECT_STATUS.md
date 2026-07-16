# AI Examiner v0.5.0.dev0 项目状态

## 发布状态

- 版本：0.5.0.dev0
- 阶段：Adaptive Cognitive Engine - Design and Development
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
- Ollama 模型目录持久化；
- 蓝图生成模型独立选择；
- 文本答辩模型独立选择；
- 14 项自动化测试；
- 86% 总体代码覆盖率；
- Ruff 与 JavaScript syntax check 通过。

## 未在本环境验证

未使用用户真实 API Key 发起付费 Realtime 通话。因此最终公网语音质量、账户模型权限、实际费用和端到端延迟需在用户 Vultr 环境验证。

## 下一步

- 建立知识单元、知识状态事件和自适应决策记录；
- 实现 Knowledge State Updater、Adaptive Question Selector 和 Difficulty Controller；
- 保留 `fixed` 策略作为兼容模式和实验对照组；
- 在 Golden Dataset 上比较固定顺序和自适应策略；
- 为报告增加 Knowledge Map、Weakness Map 和 Improvement Path。
