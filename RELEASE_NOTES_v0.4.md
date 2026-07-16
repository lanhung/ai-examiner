# AI Examiner v0.4.0 — Realtime Voice Beta

## 重点

- OpenAI Realtime WebRTC speech-to-speech；
- 浏览器到模型的低延迟媒体通道；
- 语义 VAD 自动轮次判断；
- 用户插话时自动取消和截断未播放回答；
- 实时用户/AI 字幕；
- Echo cancellation、noise suppression 和 auto gain control；
- 按住说话备用模式；
- 语音会话、转录、首次响应延迟、中断次数和错误持久化；
- 域名 + Caddy 自动 HTTPS；
- Vultr `git pull` 一键升级脚本。

## 架构

标准 API Key 只保留在 FastAPI 后端。浏览器把 SDP 发给 `/api/voice/sessions/{id}/sdp`，后端调用 OpenAI `/v1/realtime/calls`，返回 SDP answer。建立连接后音频使用 WebRTC 传输，控制事件使用 WebRTC data channel。

## 测试

- 14 项自动化测试；
- 语音配置、会话、SDP 代理、转录事件、指标和完成生命周期；
- v0.1–v0.3 全部回归；
- Ruff 和 JavaScript syntax check。

## 已知限制

- 真实语音体验依赖用户 OpenAI 账户的 Realtime 模型权限和网络质量；
- 公网麦克风需要 HTTPS；
- 当前由 Realtime 模型负责自然追问，详细会后评分仍基于持久化转录；
- 语音会话最长受 Realtime API 会话时长限制；
- 尚未加入用户登录、移动原生 App 和本地离线语音。
