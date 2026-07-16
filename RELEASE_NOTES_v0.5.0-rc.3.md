# AI Examiner v0.5.0 RC3

发布日期：2026-07-16

RC3 修复“页面证据与视觉审查”错误处理：浏览器不再重复读取响应流；后台队列不可用时返回明确的 JSON 503；单进程测试部署可使用 `CELERY_ALWAYS_EAGER=true` 直接完成视觉分析。

生产 `main` 与 `v0.4.1` 标签保持不变。RC3 仅用于 v0.5 staging 验收。
