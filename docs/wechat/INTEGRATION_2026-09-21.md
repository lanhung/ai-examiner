# 微信小程序与 AutoDL 联调记录

日期：2026-09-21。分支：`feature/wechat-miniapp`。后端仍为 `0.9.0`，客户端为 `0.1.0-preview`。

## 结论

客户端已修复原生编译错误，后端微信接入代码已部署并启动，但**尚不能完成真实微信登录和答辩**。

实测存在两个独立阻断：

1. 微信开发工具拒绝当前服务域名，页面显示“服务域名未获微信允许”。
2. 服务器未配置当前 AppID 的 AppSecret，状态接口返回 `missing_credentials`。

没有用 mock 登录、伪造微信身份或关闭授权校验来绕过问题；没有调用付费模型。

## 已实施

- 用户工程目录：`D:\wechat`。保留导入项目的 AppID `wx6aa6d6dc4dbd9505`，未替换成其他账号。
- API 地址：`https://u35756-7cf6-a3b4cec8.bjb1.seetacloud.com:8443`。
- 修复 `session` 和 `work` 页中 `wx:if` 的 `&amp;&amp;` 表达式，改为合法的 `&&`，解决 `unexpected ';'` 编译失败。
- 移除工作页中一处可选链表达式，兼容导入项目的编译配置。
- 新增登录前服务检查，识别服务关闭、凭据缺失、AppID 不一致和接口未部署。
- 区分域名白名单、TLS 和超时错误；不向页面回显原始网络错误中的敏感信息。
- 将相同修复同步回仓库 `apps/wechat`；仓库示例 API 地址仍留空，避免把服务器地址固化为通用默认值。

## 服务器部署

应用目录：

```text
/root/autodl-tmp/ai-examiner-mvp/ai-examiner-v0.9-staging
```

部署前逐文件检查 SHA-256，备份原始文件后才覆盖；此次无数据库迁移，也未更改论文、组织或模型密钥。

备份目录：

```text
/root/autodl-tmp/ai-examiner-mvp/ai-examiner-v0.9-staging/.wechat-backup-20260921T072138Z
```

其中 `manifest.json` 记录原路径与哈希，数字命名的 `.bak` 保存原文件。部署包含 config、main、authentication、authorization、启动脚本与三个微信模块。没有重写 Git 历史或上传分片。

私有配置文件：

```text
/root/autodl-tmp/ai-examiner-tools/wechat.env
```

权限为 `0600`，现有内容设置微信开关、AppID 和登录限流，AppSecret 留空。API 与 Celery 已按其 PID 和命令核对身份后优雅重启。PostgreSQL、Redis、MinIO、OIDC、OpenTelemetry 与 Ollama 已恢复运行。

## 验证结果

| 检查 | 实测结果 | 边界 |
| --- | --- | --- |
| 微信/OIDC/RBAC/启动脚本回归 | 78 passed | 本地协议测试，微信兑换与模型使用测试替身 |
| 客户端 Node 测试 | 11 passed | 模拟 wx 网络及存储，不是真机 |
| 涉及 Python 模块 Ruff | 通过 | 不替代完整安全审计 |
| 全部客户端 JavaScript 语法 | 通过 | 不代表所有微信 API 真机兼容 |
| 开发工具自带 WXML 编译器 | 四个页面通过 | 已消除实际 WXML 报错 |
| 模拟器登录页 | 可渲染 | 当前显示合法域名失败 |
| 公网 `/api/v1/wechat/status` | HTTP 200，`missing_credentials`，`login_available=false` | AppSecret 尚缺 |
| 本机 `/ready` | 数据库、OIDC、RLS、S3、治理 Redis、OTel 均 ready | 不是微信端到端验收 |
| 未登录 `/api/projects` | HTTP 401 | 未为小程序关闭鉴权 |
| OIDC `/health` | 正常 | 本轮未重新进行网页交互登录 |
| Ollama `/api/tags` | 可访问模型列表 | 本轮未执行模型推理 |

回归命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_wechat.py tests/test_oidc_authentication_v09.py tests/test_authorization_v09.py tests/test_autodl_v09_enterprise_start.py -q -o addopts=
node --test tests/wechat_client.cjs
```

## 需要账号持有人完成的配置

### 1. 微信服务器域名

在当前 AppID 对应的微信管理后台配置 `request` 和 `uploadFile` 合法域名，然后回到开发工具同步配置并重新编译。目标 API 入口为上面的 AutoDL HTTPS 地址；如果该测试账号不支持域名配置，或平台不接受此映射地址，需要使用可管理的小程序账号和被平台接受的 HTTPS 域名。

目前仅证实：此地址可通过普通 HTTPS 请求访问，但被当前微信工程的域名校验拒绝。不能据此承诺它符合真机或发布要求。本次保留 `urlCheck: true`，没有关闭校验。

### 2. AppSecret

确认测试账号是否实际提供对应 AppSecret。若提供，仅在服务器打开以下文件填写 `WECHAT_APP_SECRET`：

```bash
nano /root/autodl-tmp/ai-examiner-tools/wechat.env
chmod 600 /root/autodl-tmp/ai-examiner-tools/wechat.env
```

不要发送到聊天，也不要填写在小程序源码、开发工具或 Git 中。若测试 ID 不提供此能力，需先取得可调用真实登录接口的 AppID/AppSecret；不能凭 AppID 生成 AppSecret。

配置后需重启 API/worker 并验证状态。状态 `ready` 之后仍要由用户完成微信登录，核对真实 code2Session 结果；首次账号是 pending，需要管理员确认身份和组织后明确审批，不能自动获得现有组织数据权限。

### 3. 自动化端口（可选）

开发工具 CLI 报告“服务端口未开启”。若要继续通过官方自动化接口执行操作，由用户在开发工具“设置 → 安全设置 → 服务端口”自行开启。本次未代改安全设置。这不是服务器 6006 端口，也不是小程序 API 地址。

## 后续验收顺序

1. 域名校验通过，登录页服务检查能收到真实状态。
2. AppSecret 配置后完成真实微信登录、pending 审批、组织选择。
3. 上传非敏感测试论文，使用组织允许的真实模型生成蓝图。
4. 完成文本答辩、追问、报告、退出及过期恢复测试。
5. 核对 PostgreSQL RLS、跨组织隔离和实际模型调用记录。
6. Android/iOS 真机测试文件选择、长回答、弱网与切换后台。

语音、证据预览尚不在本原生客户端预览范围。未提交微信审核，未上传体验版或发布正式版本，也未推送 GitHub 或创建 Tag。
