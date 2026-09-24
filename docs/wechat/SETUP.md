# 微信小程序接入与验收

更新：2026-09-24。状态：开发预览，未提交微信正式发布；现有网站未被替换。

2026-09-23 已在开发者工具中完成真实 qwen-plus 蓝图、文字答辩、报告及导航恢复。已知评分和交互问题尚未修复，见 [实际界面验收报告](ACCEPTANCE_2026-09-23.md)。代码保存在 `feature/wechat-miniapp` 分支，后端仍为 `0.9.0`，客户端仍为 `0.1.0-preview`；这不是正式发布 Tag。

`D:\wechat` 使用现有 AutoDL 地址；AppID/AppSecret 已配置，真实微信兑换已完成过联调。当前增加独立个人空间免审批模式，不代表 Android/iOS 全流程和正式发布审核已通过。历史记录见 [2026-09-21 联调报告](INTEGRATION_2026-09-21.md)。

## 1. 架构与范围

```text
原生小程序
  wx.login -> POST /api/v1/wechat/login
                         -> 微信 code2Session
                         -> 服务端 Principal
                         -> approval: 管理员明确授权
                            personal: 自动创建独立个人空间
                         -> 随机服务端会话令牌
  wx.request / wx.uploadFile
       -> 原有 API -> RBAC/租户隔离 -> 文档/任务/模型/报告
```

使用原生页面而不是 web-view，避免把桌面界面原封不动压缩进手机。后端仍为模块化单体，不新建重复数据库或模型服务。

新认证默认关闭。网站 OIDC 保持不变，微信身份通过独立 issuer `wechat:miniprogram:<appid>` 区分。不会按昵称或邮件自动合并现有账号。现有 RLS、组织授权、模型治理必须继续启用；不要以 `AUTH_MODE=disabled` 绕过接入。

本次复用 Principal 和 BrowserAuthSession，未新增数据库表或变更旧字段。客户端版本与后端版本独立，不因新页面反复增加后端版本号。

## 2. 必需信息

需要运营方提供/配置：

- 自有微信小程序 AppID，可告知开发者，不是 AppSecret。
- AppSecret 通过服务器安全渠道填写，不放进聊天、Git 或小程序包。
- 正式 HTTPS API 域名及证书；微信后台的合法服务器域名配置。
- 小程序主体、服务类目、备案/审核所需材料和隐私联系人，以管理后台当前要求为准。

目前 AutoDL 的 HTTPS 映射地址不代表天然符合微信发布要求。优先为服务配置自有域名和标准 HTTPS 入口；现有 8443 端口是否可用必须在开发者工具与真机核验，不能仅以浏览器能打开为依据。

官方核对入口（本轮工具未能读取这些页面正文，请在配置时核对最新要求）：

- [登录流程](https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/login.html)
- [code2Session](https://developers.weixin.qq.com/miniprogram/dev/api-backend/open-api/login/auth.code2Session.html)
- [网络能力](https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html)

## 3. 后端配置

在现有、已经正确配置 OIDC 的部署环境中增加：

```dotenv
AUTH_MODE=oidc
WECHAT_ENABLED=true
WECHAT_APP_ID=你的AppID
WECHAT_APP_SECRET=仅在服务器填写
WECHAT_LOGIN_LIMIT_PER_MINUTE=30
WECHAT_REGISTRATION_MODE=personal
OIDC_SESSION_IDLE_MINUTES=120
OIDC_SESSION_MAX_MINUTES=480
```

Redis 必须可达（沿用 `REDIS_URL`）。微信登录采用 Redis 原子计数限流，默认每 AppID 每分钟 30 次；限流服务不可达时返回 503，不降级绕过。它是应用级流量保护，不代替公网入口防滥用/WAF。设置过低可能使共享入口被耗尽，正式上线按并发和风险校准。

`WECHAT_REGISTRATION_MODE` 默认是 `approval`，免审批需要运营方显式设置为 `personal`。启用免审批会允许通过本 AppID 验证的新用户创建个人空间，应保留模型治理、全站预算和限流；不意味着给每个用户无限模型额度。生产多租户部署继续使用非特权 PostgreSQL 运行角色和强制 RLS，不能用 SQLite 回归替代隔离验收。

代码兑换只向固定微信端点发起 HTTPS 请求，不跟随重定向；不会返回 session_key、openid 或 AppSecret。随机访问令牌仅以 SHA-256 摘要存库，支持闲置到期、绝对到期、账号禁用及主动撤销。小程序本地保存会话令牌，不能视为硬件安全存储，应避免开启调试日志或导出用户设备存储。

服务端运行环境必须能够访问微信 API，并按微信控制台提示配置出口 IP 等访问要求。

### 发布方式

先在隔离环境安装本分支代码并运行测试，不要对正在使用的网站直接覆盖未验收分支。使用现有部署方式启动 API、worker、Redis，保持它们使用同一份环境配置与数据存储。Docker 部署必须同时构建/更新 API 和 worker；AutoDL 非 Docker 部署继续用其现有启动脚本。

2026-09-21 已按用户要求部署到现有 AutoDL 服务器并重启 API/worker。微信入口开关已启用，但 AppSecret 未配置时拒绝登录。没有推送 GitHub 或创建 Tag。确认联调完成后再提交发布，沿用标准 `git commit` / `git push`，不使用 Base64 分片。

AutoDL 私有配置文件为 `/root/autodl-tmp/ai-examiner-tools/wechat.env`，权限 `0600`；由 `deploy/autodl-v09-enterprise-start.sh` 读取。只在服务器填入 AppSecret，不应放进 `D:\wechat` 或微信开发工具。修改后需重启 API/worker；启动脚本不会自动重启仍然健康的旧进程。

`GET /api/v1/wechat/status` 可匿名检查开关、AppID、注册模式和凭据是否齐备，返回 `disabled`、`missing_credentials` 或 `ready`。它不返回 AppSecret，且 `ready` 仅表示配置齐备，不证明微信兑换成功或模型可用。

## 4. 开发者工具配置

导入 `apps/wechat`；将 `project.config.json` 中 `appid` 改为实际 AppID。

`apps/wechat/miniprogram/config.js`：

```javascript
module.exports = {
  apiBase: 'https://exam.example.com',
  clientVersion: '0.1.0-preview'
};
```

配置对应 request 和 uploadFile 合法域名。当前客户端不下载证据图片、不建立实时音频 socket；后续加入时分别配置相应域名。保留 `urlCheck: true`；关闭校验得到的开发结果不能算真机上线通过。

不需要 npm install，使用原生 WXML/WXSS/JavaScript。当前项目未包含微信开发者工具安装包或服务端密钥。

## 5. 首次登录与个人空间

### 推荐：每个账号独立空间

当 `WECHAT_REGISTRATION_MODE=personal` 时，服务端在真实 code2Session 验证后自动执行：

1. 查找当前 AppID 对应身份；新身份或无现有授权的 pending 身份进入个人注册。
2. 创建该身份唯一的“我的个人空间”，只授予本人 `examiner` 权限。
3. 同事务写入账号启用、成员关系、审计和登录会话。
4. 客户端自动选择唯一空间，不再需要管理员分配组织。

空间仍使用原有 Organization/RBAC/RLS 实现，不是取消权限控制。不同新账号不共享项目、论文和答辩记录，也不会自动加入“小程序测试”等已有组织。具有相应权限的运维管理员仍按原有管理规则工作。

已有 active 账号保持原组织和权限，不自动迁移或复制旧数据。被 suspended/disabled 的账号不会恢复；被撤销的成员权限不会因重新登录恢复。存在授权冲突的 pending 账号仍需管理员核对。PostgreSQL 行锁串行化同账号注册，确定性空间 ID 防重复创建。

### 可选：保留管理员审批

设置 `WECHAT_REGISTRATION_MODE=approval` 并重启后，继续原有审批流程：

首次登录会创建一个 pending 身份，并显示申请编号（Principal ID）。它不能访问组织或论文。

管理员在服务器确认申请人身份、目标组织和授权范围后，使用同一部署虚拟环境与配置执行：

```bash
python -m ai_examiner.wechat_cli \
  --principal-id 申请编号 \
  --organization-id 目标组织UUID \
  --operator 管理员记录标识 \
  --confirm
```

仅可审批当前 AppID 的 pending 账号，组织必须 active。该命令以服务器运维权限执行，授予 `examiner` 而不是 owner/admin，写入审计记录，并原子提交成员关系和账号启用。`examiner` 可以使用组织范围内的项目，**不是个人私有空间**；用于学生或公众时应先重新设计更细的项目可见性，不要将所有陌生用户加入拥有敏感论文的现有组织。

若运行账号被 PostgreSQL RLS 拒绝，先检查现有迁移/运维角色和组织上下文，不要关闭 RLS 或改为超级用户运行网站。微信流程的 SQLite 回归不能证明 PostgreSQL 部署已验收。

用户重新登录后可选择获准访问的空间。账户启用后没有有效成员关系时，客户端显示暂无空间；不会回退到默认组织，也不会重新授予已撤销权限。

## 6. 小程序测试步骤

1. 未配置 AppID/域名时看到明确错误；不出现可用假登录。
2. 同意数据处理说明后微信登录；personal 模式直接进入独立空间，approval 模式显示申请编号。
3. 用第二个账号登录，核对两个个人空间 ID 不同，项目和材料互不可见；重复登录不产生新空间。
4. 创建“论文答辩演示”项目；选择不含真实个人数据的测试论文。
5. 上传 PDF，核对文件名、页数；再分别测试 PPTX/DOCX/TXT/MD、空文件、损坏文件和超限文件。
6. 选择真实模型，如组织允许的 qwen-plus；核对真实调用记录和费用，禁止把 mock 协议测试当作效果证明。
7. 生成蓝图，检查轮询状态、题目与材料相关性；切到后台后恢复，确认没有重复创建任务。
8. 开始文字答辩，提交正确、部分正确、错误、反问等回答，核对追问和最终报告。
9. 模拟回答提交中断网，确认按钮锁定且不会自动再发；刷新确认完成后恢复。后端未完成时仍需网页处理。
10. 关闭小程序再进入，验证最近任务/会话恢复；切换组织，核对不出现上一组织资料。
11. 退出、过期、暂停成员、禁用账号、关闭 WECHAT_ENABLED 后，检查访问被拒绝；cookie 方式也不能绕过微信开关。
12. Android/iOS 各实测布局、软键盘、长回答、文件选择、后台切换、低网速与系统字体设置。

## 7. 上线前剩余工作

- 真实 AppID/code2Session 已验证过；继续进行公网限流、断网恢复和真机网络验收。
- WXML 原生编译及登录后点击流程已验证；Android/iOS 真机验收尚未完成。
- 已完成一份小 DOCX 的 qwen-plus 完整答辩及用量核对；还需长论文、多格式和多模型测试。客户端列出其他模型不等于它们均可用。
- 运营方隐私政策、联系方式、用户信息处理说明、删除/导出入口及平台隐私要求适配。
- 公众版注册滥用防护、费用上限和账号体验；个人空间之外的共享功能必须另行授权。
- 将同步回答改成可查询、幂等的异步任务，进一步改善弱网恢复。
- 原生录音与流式音频适配、用户插话、设备权限以及微信后台音频中断测试；不可宣称已具备 ChatGPT 同等语音体验。
- 页面证据预览、历史列表、场景模板选择按下一阶段任务增加，当前仍可在网页使用。

## 8. 回滚

只需关闭免审批时，将 `WECHAT_REGISTRATION_MODE=approval` 并重启 API。已经开通的个人空间及有效会话不会被此设置撤销；需要停用时必须显式禁用账号/撤销会话，不应删除空间数据。

首先设置 `WECHAT_ENABLED=false` 并按原部署方式重启 API/worker。微信登录与微信令牌访问被关闭，普通 OIDC 网站流程保持不变。必要时撤销 BrowserAuthSession 中对应账号会话。不要删除数据库、上传文件或组织，不能运行 `docker compose down -v` 作为回滚手段。
