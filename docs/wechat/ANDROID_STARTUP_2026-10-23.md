# 安卓开发预览版启动白屏排查

日期：2026-10-23。后端 0.9.0、客户端 0.1.0-preview 均不变。

## 现象和证据

- 用户安卓手机可以看到 AI Examiner 导航栏和右上角菜单，正文全白。
- 同一代码在微信开发工具模拟器可显示考试大厅、工作台和答辩页。
- 官方 CLI 生成的新预览包仍白屏，排除“只打开了旧开发包”这一解释。
- 首轮增加启动错误提示和延后跳转后，用户反馈手机仍白屏。这些防护不是本次页面注册错误的修复证明。
- 随后读取用户已连接的真机调试日志，获得实际错误：

```text
[wxapplib]] [addView] rootCompPath=pages/login/index not found
MiniProgramError
Component is not found in path "wx://not-found".
```

真机 WXML 树为 `<body is="wx://not-found">`。这属于页面创建阶段，不能归因于
千问调用、登录服务延迟或上传文件格式。

## 修复

1. `app.json` 声明了 7 个页面，但原来只有 session 和 exam-answer 有页面 JSON。
   为 login、school、work、exam、report 补齐 `index.json`，内容为：

   ```json
   { "usingComponents": {} }
   ```

2. 保留 `lazyCodeLoading: requiredComponents`，不通过关闭按需注入规避问题。
   语音组件仍只注册在两个答题页，不设置页面 `component: true`。
3. 登录页先渲染，再在 `onReady` 检查登录状态和跳转。入口脚本使用基础语法，
   延后加载 API 模块；模块、存储、跳转失败可显示固定错误码及重试按钮。
   跳转回调缺失时 5 秒解除等待。页面卸载后忽略迟到结果。
4. 只显示构建标识和固定启动错误码，不记录或展示 Token、手机号、论文、回答。
   不清除用户存储，不自动重新提交答案或调用付费模型。

## 检查和限制

```bash
node --test tests/wechat_client.cjs tests/wechat_startup.cjs tests/wechat_speech.cjs tests/wechat_realtime.cjs
```

- 102 passed。新增启动故障、导航时序、授权同意、Token 校验和卸载竞态覆盖。
- 修正原测试漏洞：名为“all page routes and JSON configs exist”的测试，原先实际
  只检查 `.js` 与 `.wxml`；现在检查全部页面 `.json` 内容及 `usingComponents`。
- 在补齐配置前，新检查确实失败于 `pages/login/index.json`；补齐后通过。
- 已备份并同步登录 JS/WXML 和 5 个新 JSON 到 `D:\wechat`。AppID、服务地址未修改。
- 官方 CLI 修复预览包构建通过，包大小 74,517 字节；这不是安卓验收结果。
- 用户在安卓手机重新扫描修复预览后确认“页面已正常显示”，本次启动白屏修复已获真机反馈。
  这不是本轮所有业务页面点击、录音、答题、评分的验收；iOS 未测。
- 尚未替换微信后台已经上传的开发版，也没有发布正式版或推送 GitHub。

## 复测步骤

1. 在开发工具重新编译，生成新的预览二维码。旧预览、已上传开发包不会因修改本机文件自动更新。
2. 安卓微信重新扫码，确认登录页或考试大厅正文出现；未登录时可核对构建标识
   `20261023-startup1`。无需清除微信全部数据或撤销麦克风权限。
3. 检查学生端、教师端切换，以及考试详情、个人工作台、已有答卷和报告页面。
   检查展示即可，不提交答案、不改动成绩。
4. 真机调试确认新一轮启动不再出现 `rootCompPath ... not found` 和 `wx://not-found`。
   不把调试器里保留的历史报错误认为新包报错。
5. 通过后再上传更新微信开发版；不要以模拟器显示正常或 Node 测试通过替代真机验收。
