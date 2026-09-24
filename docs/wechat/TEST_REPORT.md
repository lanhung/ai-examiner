# 微信小程序预览版验证记录

日期：2026-09-10。分支：`feature/wechat-miniapp`。

## 本轮结果

| 检查 | 结果 |
| --- | --- |
| 新增微信登录与原有 OIDC、RBAC 回归 | 75 passed |
| 原生客户端逻辑 Node 测试 | 8 passed |
| 涉及 Python 模块 Ruff 检查 | 通过 |
| 小程序所有 JavaScript 文件 `node --check` | 通过 |

运行命令：

```bash
python -m pytest tests/test_wechat.py tests/test_oidc_authentication_v09.py tests/test_authorization_v09.py -q -o addopts=
node --test tests/wechat_client.cjs
```

覆盖新账号默认拒绝、明确审批与审计、令牌哈希、闲置/绝对到期、禁用与撤销、AppID 隔离、关闭微信后 cookie 不可绕过、拒绝伪造 openid、无组织权限访问拒绝、Redis 登录限流的失败关闭逻辑。

API 协议测试完整经过登录、审批、项目、上传、异步蓝图、自适应答辩到报告；使用模拟微信兑换及确定性模型。客户端测试模拟 wx 网络和存储，覆盖固定域名、非 HTTPS/跨域拒绝、组织头、错误响应、401 清理、上传 JSON 解析、超时不重发及按账号/组织隔离的进度 ID。

测试中发现并修复：新路由与现有启动权限清单不兼容、审批审计枚举不符合数据库约束，以及微信令牌经浏览器 cookie 进入时未检查微信开关的问题。

现有依赖警告涉及 Starlette/httpx 弃用、Alembic path_separator 以及旧安全测试用短 HMAC 密钥；未在本功能范围内升级这些依赖。

## 未验证，不能宣称通过

- 微信开发者工具编译和 Android/iOS 真机操作、视觉布局。
- 真实 AppID/code2Session 兑换、微信合法域名与当前 AutoDL 映射地址兼容性。
- 微信入口连接实际 Redis/PostgreSQL RLS/S3 的部署集成。
- 千问/OpenAI/Ollama 真实模型质量、费用、长论文响应时长。
- 原生麦克风、扬声器和实时音频；本预览版尚未实现。
- 微信平台正式审核、隐私资料及公网对抗测试。

本轮没有产生付费模型调用，没有修改远程服务，没有上传 GitHub，也没有增加发布 Tag。
