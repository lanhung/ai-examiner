# 小程序千问实时语音

## 当前状态：暂缓提供（2026-10-22）

按用户要求，当前小程序已移除实时语音入口及共享组件中的实时控制器初始化。
个人答辩、学生答卷、教师试答仅保留按轮“语音回答”和“朗读题目”，仍需手动确认提交答案。
以下为实现与历史验收记录，不代表当前页面已开放实时语音。

本次开发工具实测 WSS 返回 `url not in domain list`，页面同时提示“此空间尚未启用实时语音”；
后端实时开关仍为关闭。恢复入口前需要完成域名校验、受权连接、模型收音、双向回复与真机验收。
实时实现代码保留；未修改网页端、模型配置、权限、预算或版本号。

日期：2026-10-21。后端版本保持 0.9.0，无数据库迁移。

## 功能与边界

个人答辩、学生答卷和教师试答页新增“实时语音答辩”。原有“朗读题目 / 语音回答”继续提供，
不是静默降级。实时模式固定使用服务端 `QWEN_REALTIME_MODEL`，默认是用户指定的
`qwen3-omni-flash-realtime`，Cherry 音色。不调用 Mock，不将模型 Key 下发微信。

链路：RecorderManager 原生 PCM → 自家 WSS → 千问 realtime → PCM 流 → WebAudio。
输入 16 kHz、单声道、16-bit little endian；输出 24 kHz。小程序不是网页 WebRTC，
不能直接照搬浏览器 AudioContext/getUserMedia。此实现不承诺 ChatGPT Voice 等同体验。

- 主动点击后确认数据用途，再申请隐私和录音权限；不自动启动麦克风。
- 首先朗读当前题目，可重述题意并围绕回答追问；不改变考试题库、分数或题目进度。
- 用户插话停止本地播报；“停止播报”可手动停止。佩戴耳机减少扬声器回声。
- 用户转写追加到可编辑草稿，结束语音后仍需点击原有的确认提交按钮。
- 结束时补短静音供 VAD 完成检测，等待最多 4 秒收取转写；请核对草稿是否完整。
- 切题、切后台、离页、网络错误时释放音频和连接，丢弃晚到数据；不自动重连/续录。
- 默认每次最长 180 秒、最多 8 次模型回复；一个长答案可分多次语音追加草稿。
- 不写录音到应用存储或成绩库；微信录音临时文件在停止时清理，异常退出由微信清理。
  供应商保存政策以账户协议为准；不能承诺供应商零保留。

提示词约束不能证明模型绝对不泄露答案；服务端只给当前问题，不给参考答案、Rubric 或其他题目。
正式考试是否允许实时追问应由出题方决定，并安排题目行为验收。

## 配置与发布

```dotenv
WECHAT_REALTIME_ENABLED=false
WECHAT_REALTIME_ORGANIZATIONS=<逗号分隔的已批准组织UUID>
WECHAT_REALTIME_MAX_SECONDS=180
WECHAT_REALTIME_BUDGET_USD=0.5
QWEN_REALTIME_MODEL=qwen3-omni-flash-realtime
QWEN_REALTIME_VOICE=Cherry
QWEN_REALTIME_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/realtime
```

沿用服务器的 `DASHSCOPE_API_KEY`。空组织名单拒绝所有空间；开启全局开关不会绕过名单。
必须同时通过已有的组织 voice 模型许可、资料密级、预算和限流。学生考试使用出题组织的配额，
记录调用学生的身份。该开关与按轮 ASR/TTS 的 `WECHAT_SPEECH_ENABLED` 独立。

`0.5` 是每次连接的保守记账估算，不是阿里云报价、实际费用或费用上限保证。
连接存续期间保留并发租约，结束后结算；失败仍按原治理规则保留估算。记录供应商实际返回的 Token。
时长上限还受并发租约长度减 30 秒约束；租约不足 60 秒拒绝启用。
未完成实际账单对账，不应把估算视为精确计费。

微信后台需添加服务器的 **socket 合法域名（wss）**，同时保留 request/uploadFile 域名。
例如当前测试服务对应 `wss://u35756-7cf6-a3b4cec8.bjb1.seetacloud.com:8443`；
实际是否接受这个域名/端口须在微信后台验证。正式发布应使用自己的备案 HTTPS/WSS 域名。
反向代理必须支持 WebSocket Upgrade，空闲超时应超过会话上限。
不把 DashScope 加入小程序域名表，也不让客户端直接带 Key 访问供应商。

更新 `D:\wechat\miniprogram` 时保留真实 AppID、config.js 和开发者私有配置。
重新编译，首次建议用真机调试及耳机；开发者工具/PC 对 RecorderManager 采样率的支持有限。
未收到 PCM 帧会停止并提示改用真机或按轮录音，不伪造成功。

## 接口与安全

`GET /api/v1/wechat/voice/{kind}/{id}/context` 增加 realtime 配置。
`WS /api/v1/wechat/voice/{kind}/{id}/realtime` 要求原生微信登录 Bearer 令牌，
不接受仅靠 Cookie、前端 principal ID 或 URL token 登录。

首条消息只能为 `{"type":"start","question_key":"<context返回的指纹>"}`。
之后只允许受限 PCM append、interrupt、finish 和 stop；客户端不能覆盖 session.update、
模型、提示词、任意文本或自行触发 response.create。服务器过滤输出，不转发供应商内部配置和原始报错。
音频大小、速率、消息速率、响应数和输出总量均受限；每 5 秒重新核查登录、资源和题目。

未授权、非本人答卷、非本人教师试答、题目变化及组织未启用均拒绝；没有成绩写入接口。
语音录制期间客户端禁用提交，切题后清空考官显示并丢弃旧连接事件。

## 本轮验证状态

自动化验证与供应商实测分开记录，不能相互替代：

本地最终回归：后端 119 项通过，客户端 55 项通过，Ruff 通过。
`D:\wechat` 已同步 4 个相关客户端文件并通过微信工具 WXML 编译，AppID 和 config.js 未改。
服务器 `/tmp` 隔离副本同样 119 项通过。相关后端代码已备份并部署，API 已重启：
公网 `/health` 返回版本 0.9.0，本机 `/ready` 为 200，匿名访问新 WSS 路由返回 403。
`WECHAT_REALTIME_ENABLED=false`，原有 `WECHAT_SPEECH_ENABLED=true` 保持不变。
仅预设已批准教师空间的实时组织名单，没有更改数据库模型规则、成员、考试或成绩。

- 本地协议/权限/客户端状态测试已建立，覆盖令牌、资源归属、模型规则、题目指纹、
  配置注入、结束补静音、播放取消、重复转写去重、生命周期和缺失 PCM 帧。
- 真实北京区 WebSocket 能收到 `session.created`，但发送 session.update 后持续关闭，
  close code 1007，reason `Model not exist.`。简化配置和有/无显式 ASR 配置均未通过。
- 服务端自报的该模型默认转写器是 `gummy-realtime-v1`，不能照搬新版文档中的
  `qwen3-asr-flash-realtime`。模型握手与这个默认字段不能证明推理可用。
- 相同密钥调用官方兼容模型目录成功（HTTP 200）：列有
  `qwen3-omni-flash-realtime-2025-09-15`，没有未带日期的请求别名。
  这是诊断线索，不是快照版本已通过音频测试的证明。
- 没有静默替换请求的模型，没有完成真机麦克风、扬声器、回声或端到端延迟验收。
- 在确认可用模型和接入地址前，不应把实时开关开启作为上线完成。原有文字与按轮语音保留。

```bash
python -m pytest -o addopts= -q tests/test_wechat_realtime.py tests/test_wechat_speech.py \
  tests/test_school_exams.py tests/test_wechat.py tests/test_model_governance_v09.py \
  tests/test_authorization_v09.py
node --test tests/wechat_client.cjs tests/wechat_speech.cjs tests/wechat_realtime.cjs
```

后续真机门禁：iOS/Android 各完成连续对话；插话与停止播报；结尾转写；中文术语；
耳机/外放回声；弱网；来电/锁屏/返回；退出登录和撤销权限；限额拒绝；提交确认；
教师试答不混入正式成绩。分别记录首音、回答后首音和打断停止的端到端延迟。

## 指定模型的接入与权限复核

2026-10-21 15:29（北京时间）在现有 AutoDL 服务器复核。用户要求保持
`qwen3-omni-flash-realtime`，本轮没有调用其他模型，也没有更换配置、重启应用或修改授权。
只查询模型目录并创建最小会话；没有发送 `response.create`、音频、论文或答卷。
这不是音频功能验收，也没有据此声称实际费用为零。

| 检查 | 实测结果 | 结论边界 |
| --- | --- | --- |
| 生效密钥 | 来自项目根 `.env`，进程环境没有覆盖；不存在首尾空白 | 只比较存在性和相等性，不输出密钥或片段 |
| 接入地址 | `wss://dashscope.aliyuncs.com/api-ws/v1/realtime`，无重复查询参数 | 模型作为 URL 的 `model` 参数传入，名称精确匹配 |
| 带密钥 GET `/compatible-mode/v1/models` | HTTP 200；178 个条目；`has_more=false` | 此密钥通过该目录接口的认证，不代表拥有指定模型的推理权限 |
| 不带认证的相同目录请求 | HTTP 401 | 区别于匿名可访问目录，支持上述认证结论 |
| 目录中精确模型名 | 未列出无日期别名；列有 `qwen3-omni-flash-realtime-2025-09-15` | 没有测试快照；目录不是完整授权证明，不能仅据此断言模型已下线 |
| `session.update` 的 `session={}` | 握手后关闭，1007 / `Model not exist.` | 不涉及自定义音色、ASR 或 PCM 参数 |
| `session.update` 的 `session={"modalities":["text"]}` | 同样关闭，1007 / `Model not exist.` | 未进入音频处理；小程序和反向代理均不在这次直连路径内 |
| 应用存活 | `/health` HTTP 200、版本 0.9.0；`/ready` HTTP 200 | 实时开关仍关闭，按轮语音开关仍开启；未重做按轮推理验收 |

结论：失败已在服务器直连百炼的最小请求上复现，不依赖小程序的录音或播放实现。
仍须区分供应商的模型别名可用性、模型服务开通状态和业务空间授权，不能武断归因于密钥失效。
[官方错误说明](https://help.aliyun.com/zh/model-studio/error-code)也要求分别核查模型 ID 与模型服务开通情况。

[官方 SDK 接入说明](https://help.aliyun.com/en/model-studio/omni-realtime-java-sdk)
允许旧型号沿用原域名，因此不能因为出现了新的专属域名，就认定北京旧地址必然错误。
[地域说明](https://help.aliyun.com/zh/model-studio/regions)要求密钥和地域匹配；本轮未将现有密钥发往其他地域。

### 待补充信息与下一步

服务器现有相关配置没有百炼 WorkspaceId。该 ID 与本项目的组织 UUID、微信 AppID 不同，不能替代使用或猜测。
需要由账号所有者提供当前 Key 所属业务空间的 ID、地域，以及指定模型的授权状态；无需发送密钥。
可在百炼控制台的业务空间详情查看 ID，并提供遮住密钥的模型权限页面截图。
[业务空间权限说明](https://help.aliyun.com/zh/model-studio/permission-management-overview)
解释了空间授权与控制台用户权限的区别。

收到真实 WorkspaceId 后，先使用服务器现有 Key 做只读核查：

1. 按[查询模型授权接口](https://help.aliyun.com/zh/model-studio/list-model-permissions)，
   在该空间的北京专属域名调用 `GET /api/v1/models/permissions`，
   使用 `model=qwen3-omni-flash-realtime` 精确过滤；分别检查可授权条目和已授权推理条目。
2. 核对响应的 `success`、权限明细、错误码和请求 ID；空列表或 HTTP 403 均不能直接等同于模型下线。
3. 若空间归属正确，临时用 `wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime`
   复测同一个模型，不先修改生产地址。若仍失败，整理时间、模型、地址、错误码交给百炼支持确认别名状态。
4. 只有最小会话通过，才继续合成内容的音频验收及真机测试；在此之前保持实时开关关闭。

本轮没有扩大模型白名单、调整额度、替换其他模型、调用授权更新接口或修改学生成绩。

### 网页千问成功记录与当前差异（2026-10-22）

用户确认曾在网页选择千问并正常对话，不能用当前直连失败否定这段使用经历。
本地历史数据库的只读查询找到 2026-07-22 的网页千问会话，模型为
`qwen3-omni-flash-realtime`、音色 Cherry，记录了 1 条非空考官回复。
[v0.7 音频验收报告](../evaluation/V0_7_REAL_AUDIO_ACCEPTANCE.md)也记录了当时千问转录和 PCM 音频流通过。
历史元数据仅证明曾有成功输出，不能替代当前模型可用性及完整双向真人对话验收。

本轮使用服务器网页的 `qwen_realtime_session_config` 函数生成配置，包含
`smooth_output=true`，并清除诊断进程的残留环境、加载应用生效配置，再用同一指定模型直连复核。
结果仍是握手后关闭，1007 / `Model not exist.`，收到音频字节数为 0。
没有调用其他模型，也没有改动线上模型、密钥、组织权限或开关。

另一个独立缺陷：网页 `qwen_voice_websocket` 创建 `SessionLocal()` 后未设置租户上下文，
直接按 ID 查找 `VoiceSession`。在当前 PostgreSQL/RLS 环境的只读复核中，
同一条已存在的会话不带租户上下文时查找失败，带正确组织上下文时查找成功。
当前数据库 2026-10-22 14:00 至 14:03 的三条千问会话也没有开始时间或转录事件；
日志的 WebSocket accepted 只说明本地连接被接受，不能证明上游模型已开始工作。
这些记录不能用来反推用户历史使用时发生了什么。

### 网页连接修复与部署（2026-10-22）

上述租户上下文缺陷已修复并部署到当前 AutoDL 6006 服务，版本仍为 0.9.0。

- 浏览器 WebSocket URL 传递当前组织 ID，不传访问令牌；组织 ID 只是选择参数，不是授权证明。
- 复用 HTTP 登录与工作台权限逻辑，验证 Cookie/令牌、账号状态、组织成员状态、
  `session.conduct` 和 Origin，然后绑定租户上下文并查找语音会话。
- 连接期间每五秒复查登录、权限与会话状态；会话初始化和数据库更新也使用相同租户上下文。
- 不关闭 RLS，不使用超级用户应用连接，不放宽匿名访问。
- 只有上游返回 `session.updated` 才标记模型就绪并结算连接账本；握手成功不再等于模型可用。
- 初始化失败、断线时关闭录音和播放，保留错误提示，避免清理流程覆盖失败原因。

验证记录：

| 检查 | 结果与边界 |
| --- | --- |
| 网页语音、OIDC、权限回归 | 87 项通过；供应商替身用于验证行为，不代表真实模型验收 |
| 小程序实时/按轮语音回归 | 32 项通过 |
| 前端 JavaScript 生命周期测试 | 组织参数、等待模型就绪、初始化失败、断线清理、错误保留通过 |
| Ruff 与 JavaScript 语法 | 通过 |
| 真实 PostgreSQL FORCE RLS | 唯一临时库，仅克隆表结构；非超级用户/非 BYPASSRLS；登录、事务提交后查找/更新、跨组织拒绝、撤销成员权限通过；临时库已删除 |
| 已部署服务 | `/health`、`/ready` 均 HTTP 200；匿名 WebSocket 被 HTTP 403 拒绝 |
| 浏览器和真人音频验收 | 未完成；浏览器工具初始化失败，不以单元测试代替页面点击或真实麦克风测试 |

这次仅替换五个运行文件，无数据库迁移、业务材料/成绩修改、API Key 修改或 GitHub 推送；
真实探测通过原模型治理记录失败调用账本。
服务器源码备份：`.qwen-web-backup-6dg6aa6r`；部署后的 API PID：230576（仅为当次记录）。
可重复 RLS 验证脚本为 `deploy/verify-qwen-web-rls.py`，只允许
`aiex_qwen_web_<32位随机十六进制>_test` 临时库。禁止对正在服务的数据库运行测试或删除表。

### 用户提供的业务空间实测（2026-10-22）

收到业务空间 `llm-w78miqrz2h76f1ba`，北京 API Host 为
`llm-w78miqrz2h76f1ba.cn-beijing.maas.aliyuncs.com`。
使用服务器现有 Key，仅做只读权限查询与一次受预算约束的原模型短语音探测。

| 项目 | 结果 |
| --- | --- |
| 精确查询 `qwen3-omni-flash-realtime`，AUTHORIZABLE | HTTP 200、success=true、total=0 |
| 精确查询同模型，AUTHORIZED | HTTP 200、success=true、total=0 |
| 同系列 `name=qwen3-omni`，AUTHORIZABLE | 列出 `qwen3-omni-flash` 与 `qwen3-omni-flash-realtime-2025-09-15`，两者 `permissions.inference=false` |
| 同系列 AUTHORIZED | HTTP 200、success=true、total=0 |
| 专属域名下原模型语音探测 | 收到 `session.created`，未收到 `session.updated`；连接异常关闭，音频 0 字节、回复 0 次；不把此次关闭等同于先前旧域名明确返回的 1007 |

专属域名探测上游会话 ID：`sess_DfcKKx2Ou9l8BoPViIiS4`，失败账本
`437c726f-8f81-4558-bbd5-e508020892c3`。同系列查询请求 ID：
`ba47c5e7-4ec9-990a-a80a-d472108a5597`（可授权）、
`7719a86f-3f79-9e81-b8d9-d0e0d303484b`（已授权）。

结论边界：Key 能访问当前空间权限接口，不等于拥有实时模型推理权限。
该空间当前没有列出原无日期模型；可授权的日期快照也尚未获得推理授权。
不能据此断言原模型在所有账号/地域都已下线，也不能声称换域名就能解决。

下一步需用户决定：

1. 若继续坚持无日期名称，由百炼支持确认该空间是否仍可开通此 ID；提供上述请求 ID。
2. 若允许使用日期快照，先明确批准模型变更和推理授权，再开通、核对项目模型治理规则、
   使用该空间专属地址验证输出和语音输入。当前没有调用或自动替换为这个快照。
3. 只有真实模型链路通过后，才继续小程序真机录音、播放、插话验收和实时开关启用。

线上模型、接入地址、白名单、预算与实时开关保持原样；按轮语音和文本功能未改。

### 日期快照的授权与真实探测（2026-10-22，后续记录）

用户同意继续测试后，按[单模型授权接口](https://help.aliyun.com/zh/model-studio/update-model-permissions)
仅为上述北京业务空间授权 `qwen3-omni-flash-realtime-2025-09-15` 的推理能力。
请求使用 `access_all_entities=KEEP`，未开启全模型授权，未请求微调或部署授权。
更新请求 `43204fe2-2006-9901-859a-738f40b406fb` 成功；回查
`a9080346-b83d-9276-a646-f149b8484059` 为 `inference=true`。
因此前文“快照未授权”是此前的检查结果，不再是本轮结束时的状态。

测试范围：只使用合成内容和该日期快照，不用 Mock 代替真实模型；另外单独运行离线回归。
项目内临时精确白名单只作用于已批准的教师组织，每次探测后恢复原规则。
策略版本和审计记录正常递增，预算、成员、其他组织、材料和考试成绩均未修改。
百炼侧的单模型推理授权保留；正式运行的模型别名、接入地址和实时开关没有切换。

| 实测 | 结果 | 验收边界 |
| --- | --- | --- |
| 专属域名短语音输出 | `session.updated`、1 次完整回复、80,640 字节 PCM；初始化 107ms、首音频 468ms | 输出链路通过；首音频为服务器直连测量，不含手机网络与播放缓冲 |
| 输出音频重采样后回传，自动 VAD | 2 次探测均无语音起止、无输入转录、无自动第二轮回复 | 加事件 ID、前后静音后仍未通过，不能据此单独认定真实麦克风也失败 |
| 手动提交回传音频 | 收到 `input_audio_buffer.committed` 和第二次音频回复，但无输入转录 | 不是完整双向验收；第二次回复本身不能证明听懂了输入 |
| 独立合成人声，专属域名 | 343,680 字节完整上传，RMS=3380、峰值=19169；无转录/VAD/第二轮回复 | 排除只回放考官自身输出的测试偏差，仍需定位供应商或协议兼容问题 |
| 相同独立人声，北京原域名 | 同样未收到转录/VAD/第二轮回复 | 单纯换北京接入域名不能解决当前输入问题 |
| 先输入人声，不主动生成开场；改用官方当前转录参数 | `qwen3-asr-flash-realtime` 被 `session.updated` 接受，但仍无转录或回复 | 只改变实时会话内转录参数，未调用其他对话模型；也未写入正式配置 |
| 相同先输入配置，关闭 WebSocket 压缩 | 343,680 字节完整上传；只收到 `session.updated`，超时结束 | 禁用 `permessage-deflate` 未改善；正式客户端未据此改参数 |
| 对照官方 SDK 的 legacy 格式 `pcm16` | 输入输出格式均获确认，首音频 538ms；独立人声完整上传，但无 VAD/转录/第二轮 | 格式差异不是已证实根因；未将该诊断参数替换到正式代码 |
| 本地后端回归 | 60 项通过，独立 SQLite 测试库 | 网页访问控制、小程序实时/按轮语音；使用供应商替身，不是音质验收 |
| 前端生命周期回归 | 网页脚本通过；小程序 6 项通过 | 不等于开发工具点击或手机真机录音验收 |
| 服务与安全复核 | `/health`、`/ready` 均 200；匿名语音 WebSocket 为 403 | 最后一轮测试后教师策略版本 20，精确测试规则已恢复；原预算与并发值保留，按轮语音开启、实时语音关闭 |

独立测试音频由本地系统语音合成生成，16kHz、单声道、16-bit PCM，内容为：

> My experiment compares two methods on the same data set. I used three random seeds and measured the average error.

没有发送真实用户声音、论文、姓名或成绩。音频按实时速度分帧发送，增加前置 1 秒、尾部 2 秒静音；
检测窗口有上限，不无限重试。已观察到的首音频约 468–538ms，不构成稳定性或 P95 性能承诺。
每次真实请求经过项目配额预留与使用账本，预留/保守估算不等于百炼最终账单。

可供百炼排查的会话和账本：

| 场景 | 上游会话 ID | 本地账本 ID |
| --- | --- | --- |
| 短输出成功 | `sess_Gp54IYbCsu5KdW2i6bk4Z` | `2632565e-3e50-4320-bfc3-89697a9805c7` |
| 手动提交，无转录 | `sess_RjEeiAfGUa6VTBORvC2KN` | `a23fdb2c-b87f-46ec-8df4-447b9d3e2416` |
| 专属域名，独立人声 | `sess_Ua3YyKcjvqqM5sABCMafa` | `8600372f-c2f4-4059-b1df-90bfd426946f` |
| 原域名，独立人声 | `sess_Mf8UmLNpYJpAT3Tkme56m` | `29294a06-19cc-4aad-bfd7-064e6bb194a32` |
| 先输入，当前转录参数 | `sess_QUGPLSC2Zf1bc2jOWgsKy` | `54076f48-290b-4f93-99f8-a85a98d95fd3` |
| 先输入，关闭压缩 | `sess_QAw38NFfmQbxcoV7z6CPa` | `fbd13b97-f4b3-4d96-8d51-d8f0aef0b299` |
| SDK legacy 格式 `pcm16` | `sess_VPdrlKsdVBs4IdPejSyil` | `32c73b67-8baa-4793-b3e2-08bbdcebceb7` |

当前不得将“权限已开通”“模型能发声”表述为“自然语音对话已修复”。
仍需输入转录、自动多轮、插话/取消与真机录放音通过，才启用小程序实时功能。
自动测试结果与真实模型结果分开记录，不能用离线通过率掩盖上述未通过项。
没有将本轮诊断脚本的临时参数写入生产客户端；版本仍为 0.9.0，未推送 GitHub。

下一步应使用上述会话 ID 请百炼核对输入音频接收、VAD/ASR 子链路和该快照的兼容性，
并用官方 SDK 对相同合成 WAV 做可复现对照。现有证据不足以断言唯一根因在供应商；
同样也不能继续把问题归为原来的“模型不存在”，因为日期快照已能产生真实音频。
已对照[官方 SDK 源码](https://github.com/dashscope/dashscope-sdk-python/blob/main/dashscope/audio/qwen_omni/omni_realtime.py)
发现 legacy 会话使用 `pcm16`，并做了协议字段复测，但没有安装、运行完整官方 SDK；
不得把字段对照表述为“官方 SDK 实测也失败”。真实手机输入仍未验收。

### 小程序结束流程修复及官方 SDK 对照（2026-10-22，最新记录）

本节更新此前“尚未运行完整官方 SDK”的状态，不改动历史探测记录。

已在服务器的独立临时目录安装并运行官方 `dashscope==2.0.1`，没有升级应用虚拟环境。
使用同一份非敏感合成 WAV、已批准的日期快照、北京专属域名与业务空间请求头，
直接调用 `OmniRealtimeConversation.connect/update_session/append_audio`，不经过小程序或项目语音中继。
SDK 默认 VAD 阈值 0.2、前缀 300ms、尾静音 800ms；PCM 按实时速度发送。

- 343,680 字节发送完成，收到 `session.created` 和 `session.updated`。
- 35 秒内没有 VAD、输入转写或自动回复，验收未通过。
- 会话：`sess_IawdmMrPRLATjFisGPiwv`；账本：`b72840f6-d2a2-4737-af06-5e6028fad90e`。
- 临时精确白名单恢复，教师组织策略版本 22；原预算、成员、成绩均未改变。
- 这说明问题不只在小程序客户端，但还不能排除样本兼容、账号配置或服务端因素。
  不据此宣称模型全面不可用，也不静默替换其他对话模型。

本轮同时以失败用例复现并修复以下客户端问题：

| 问题 | 修复和边界 |
| --- | --- |
| 旧连接的迟到发送失败会关闭新连接 | 所有发送回调绑定连接代次，过期回调不修改当前状态 |
| 点击结束即开始 4 秒倒计时，排队音频与慢转写可能被截断 | 先停止录音、排空上传队列，再发送 `finish`；等待服务器结束确认，客户端兜底上限 12 秒 |
| 排队音频发送卡住，没有独立提示 | 结束时设置 8 秒上传上限，提示核对草稿，禁止自动重试或自动提交 |
| 结束后迟到的 `response_started` 会恢复播放 | finishing 状态持续静音，不因迟到的模型事件重新播放 |
| 空帧、奇数字节、过大或无效音频帧没有本地校验 | 忽略空帧，其他非法帧停止；有效帧复制后排队，避免缓冲复用 |
| 设备没有触发录音启动回调，界面长期等待 | 5 秒启动超时；已开始录音但没有帧的检测保留，结束时不误报 |

服务端结束协议：

1. `finish` 仍只能由客户端发起，不允许客户端指定模型配置或答案。
2. 追加 1 秒尾静音，跟踪 VAD/提交的 item 与转写状态。
3. 只有实际转写已转发给客户端，且无已知待处理项、经过 800ms 安静窗口，才提前确认结束。
4. 最多等待 10 秒；缺少确认时明确提示核对和补充，不宣称草稿完整。
5. `ready.seconds` 预留最后上传与转写的时间，避免总时限抢先断开。
6. 转写失败事件不再被忽略，返回不包含供应商内部信息的提示；草稿和正式成绩依然分离。

这些是有界的容错措施，不能替代上游输入链路恢复。
如果用户的最后一句在点击结束前就已完成转写，服务端仍可能保守地返回“最后一句尚未确认”；
这不是丢失已收到的文字，用户可以核对现有草稿后提交。

回归命令使用独立本地 SQLite 数据库，不在服务器业务库运行 pytest：

```powershell
$env:AI_EXAMINER_TEST_DATABASE_URL='sqlite:///./data/test_mini_voice_exam_regression.db'
.venv\Scripts\python.exe -m pytest -o addopts='' -q tests/test_wechat_realtime.py tests/test_wechat_speech.py tests/test_qwen_websocket_access.py tests/test_realtime_voice_v04.py tests/test_school_exams.py tests/test_wechat.py
node --test tests/wechat_realtime.cjs tests/wechat_speech.cjs tests/wechat_client.cjs tests/qwen_browser_voice.cjs
```

离线测试使用隔离的供应商替身来验证协议与权限，不代表真实模型质量。
本轮没有进行微信开发工具点击验收或手机真机音质、回声和插话验收。
正式模型别名与实时开关继续保持原状；待真实输入、转写和自动回复通过后再开放实时入口。

本轮最终验证与同步：

- 后端 106 项通过（51.21 秒）；前端 61 项通过；Ruff 检查通过。
  后端有现存 Starlette/httpx 与 Alembic 弃用告警，不是测试失败。
- `D:\wechat\miniprogram\lib\realtime.js` 已同步，AppID 和开发工具配置未修改。
  SHA-256：`dfd069ee855d2d651e5d473cef74c0bd162807fda3ff7a3c5a853ad1c9f91f7c`。
- AutoDL 只部署 `src/ai_examiner/wechat_realtime.py`，平滑重启后 `/health` 和 `/ready` 均为 200。
  备份目录 `.mini-finish-backup-6xrhjv0i`；部署文件 SHA-256：
  `7bec4409b6e527c9f597fc97f6dff813c33fc69c0da5d885716c8b2376ac6255`。
- 未改动环境变量、数据库结构、预算或成绩；版本仍为 0.9.0，本轮未推送 GitHub。

## 协议参考

- [微信官方 API 类型定义](https://github.com/wechat-miniprogram/api-typings)
- [阿里云 Realtime 客户端事件](https://help.aliyun.com/en/model-studio/client-events)
- [阿里云 WebSocket 接入](https://help.aliyun.com/en/model-studio/realtime-websocket-overview)

文档描述与账号实际可用能力可能不同；以上实测发现已经单独保留，不能用文档列表覆盖测试失败。
