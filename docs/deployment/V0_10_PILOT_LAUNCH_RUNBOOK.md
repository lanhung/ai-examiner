# v0.10 课堂试点上线手册

适用版本：v0.10.0 起
部署形态：一台服务器，Docker Compose 部署，包含 Caddy（HTTPS 与老师密码）、应用、后台任务和 Redis，数据库用 SQLite。

安全边界如下：

| 访问者 | 能打开的页面 | 验证方式 |
|---|---|---|
| 学生 | 仅考试页（`/x/入口码`、`/exam`）及其接口 | 不用注册，凭入口码和本次作答令牌 |
| 老师 | 工作台、企业控制台、所有接口和文档 | 老师密码（在 Caddy 这一层验证） |

---

## 0. 需要你准备的东西（我无法代办）

| 项目 | 要求 | 说明 |
|---|---|---|
| 服务器 | 2 核 4 GB 内存以上，Ubuntu 22.04 或 24.04，40 GB 磁盘 | 一个班 40 人的压测在单进程下通过，瓶颈是模型并发，不是服务器 |
| Docker | Docker 24 以上，Docker Compose **2.24 以上** | 试点的 Compose 文件用到了 `!override`，旧版本不支持 |
| 域名 | 一个子域名，例如 `exam.你的域名`，A 记录指向服务器 IP | Caddy 会自动申请 HTTPS 证书，80 和 443 端口必须开放 |
| 备案 | 服务器在中国大陆：域名必须完成 ICP 备案，否则 80/443 会被拦截 | 海外服务器不需要备案，但国内访问可能较慢；微信内打开时也可能提示「非官方网页」。上线前请用微信实际打开测试 |
| 模型 API | 阿里云百炼（DashScope）API Key，并确认账号的**每分钟请求数**和**并发**额度 | 一个班 40 人同时作答，大约需要 16 路并发 |
| 老师密码 | 至少 16 位的随机密码 | 这是老师端唯一的保护，务必足够长 |

---

## 1. 首次安装（约 20 分钟）

```bash
# 1) 获取代码
sudo mkdir -p /opt && cd /opt
sudo git clone https://github.com/lanhung/ai-examiner.git
cd ai-examiner
sudo git checkout v0.10.0

# 2) 生成配置
sudo cp .env.pilot.example .env
docker run --rm caddy:2-alpine caddy hash-password --plaintext '你的老师密码'   # 复制输出
openssl rand -hex 32   # 运行两次，分别用于 AUDIT_IP_HASH_KEY 和 MEMORY_IDENTITY_SECRET
sudo nano .env
```

`.env` 里必须填写以下几项：

- `SITE_ADDRESS`：你的域名，例如 `exam.example.com`。
- `TEACHER_USERNAME`，以及 `TEACHER_PASSWORD_HASH='上一步输出的哈希'`。**哈希两边必须保留单引号**，因为哈希里含有 `$` 符号。
- `DASHSCOPE_API_KEY`。
- `AUDIT_IP_HASH_KEY`、`MEMORY_IDENTITY_SECRET`：分别填上一步生成的两个随机串。

```bash
# 3) 启动
export USE_PILOT=true
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.pilot.yml up -d --build

# 4) 设置模型并发和预算（只需做一次）
#    允许的并发 ≈ 班级人数 ÷ 2.5；月预算按需填写
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.pilot.yml \
  run --rm ai-examiner ai-examiner-set-model-limits \
  --max-concurrent-calls 16 \
  --organization-requests-per-minute 1200 \
  --principal-requests-per-minute 1200 \
  --monthly-budget-usd 100

# 5) 冒烟测试（--full 会真实调用一次模型，花费几分钱）
uv run python scripts/smoke_pilot.py --base-url https://exam.example.com \
  --teacher-user teacher --teacher-password '你的老师密码' --full
```

服务器上没有 `uv` 时，可以在自己的电脑上运行冒烟测试，效果相同。结果必须显示 **ALL CHECKS PASSED** 才算上线成功。

---

## 2. 第一次上课前（建议提前一天）

1. **老师自己完整走一遍**：
   1. 打开 `https://域名/`，输入老师密码。
   2. 创建项目 → 上传本课材料 → 生成蓝图 → 在「发布给学生」里发布（模式先选「练习」）。
   3. 用手机微信打开生成的链接，完整答完一次。
   4. 回到工作台「已发布的考试」→「查看作答」，确认能看到这条记录和对话内容。
2. **小规模真实压测**：确认模型额度够用，大约花费几毛钱。

   ```bash
   uv run python scripts/load_test_exam_window.py --base-url https://exam.example.com \
     --join-code 入口码 --students 10 --i-understand-this-costs-money
   ```

   要求 `finished` 等于学生人数，`p95` 小于 20 秒。如果达不到：
   - 出现很多 `examiner_busy`：调高 `--max-concurrent-calls` 和 `.env` 里的 `LEARNER_MODEL_CONCURRENCY`（两个值保持一致），然后重启；
   - 出现模型报错：到百炼控制台检查额度。
3. **关闭测试用的考试**：「已发布的考试」→「关闭」。

---

## 3. 上课当天检查清单

- [ ] `curl https://域名/health` 返回 `"status":"ok"`，并且 `provider_ready` 为 true。
- [ ] 发布本次考试。考试模式下，学生提交后只看到「已提交」。
- [ ] 把链接（或入口码）发到班级群，请学生用手机打开。
- [ ] 需要统计成绩时，勾选「要求学生填写学号 / 考号」，并把「每人可作答次数」设为 1。
- [ ] 课后在「已发布的考试」里：「关闭」→「查看作答」→「导出 CSV」→ 需要时点「公布结果」。

学生侧的常见问题：

| 学生看到 | 原因 | 处理 |
|---|---|---|
| 「现在作答的同学很多，考官正在排队处理」 | 同时作答的人数超过模型并发 | 回答不会丢，过几秒再提交；课后调高并发 |
| 「提交太频繁」 | 同一次作答每分钟提交超过 10 次 | 稍等再交 |
| 「作答次数已用完」 | 已达到每人次数上限 | 老师调高次数，或核对学号 |
| 「本场考试已结束 / 已关闭」 | 已过截止时间，或老师已关闭 | 老师重新开放或延长截止时间 |
| 关掉微信后重新打开 | 进度保存在手机浏览器里 | 用**同一部手机、同一个链接**打开会自动接着答 |

---

## 4. 日常运维

**备份**（每天自动做一次，并定期拷到服务器之外）：

```bash
sudo crontab -e
# 每天 03:00 备份，保留 14 天
0 3 * * * cd /opt/ai-examiner && ./deploy/backup.sh && find data/backups -name '*.tar.gz' -mtime +14 -delete
```

`backup.sh` 用 SQLite 的在线备份接口，学生正在作答时备份也是一致的，已在演练中验证完整性。备份和数据在同一块磁盘上，服务器坏了会一起丢，请每周把 `data/backups/` 拷到对象存储或本机。

**查看状态和日志**：

```bash
cd /opt/ai-examiner
C="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.pilot.yml"
$C ps
$C logs --tail=100 ai-examiner
df -h /opt
```

**费用**：
- 百炼控制台可以设置费用告警；
- 应用内的月预算由 `--monthly-budget-usd` 控制，超出后会拒绝模型调用；
- 每日预算由 `.env` 里的 `DAILY_MODEL_BUDGET_USD` 控制。

---

## 5. 升级

```bash
cd /opt/ai-examiner
sudo USE_PILOT=true ./deploy/update-from-github.sh
```

脚本会依次执行：先备份 → 拉取 `main` → 构建镜像 → 执行数据库迁移 → 重启 → 健康检查。**升级后请再跑一次冒烟测试。**

## 6. 回滚

数据库迁移只能向前，所以回滚到旧版本时，必须同时恢复升级前的备份：

```bash
ls data/backups/          # 找到升级前的那个备份
sudo USE_PILOT=true ./deploy/rollback.sh v0.10.0 data/backups/ai-examiner-<时间>.tar.gz
```

回滚前的当前数据会被保留在 `data-before-rollback-<时间>/` 目录下。

---

## 7. 容量（演练实测）

演练环境：单进程应用、SQLite、经过 Caddy，模拟模型每次调用耗时 2–3 秒。

| 场景 | 结果 |
|---|---|
| 40 人同时作答，并发 3（默认值） | 40/40 完成，0 错误，但单次回答中位数约 78 秒（排队） |
| 40 人同时作答，并发 16 | 40/40 完成，0 错误，中位数约 8–12 秒，p95 约 11–17 秒 |
| 80 人同时作答，并发 16 | 80/80 完成，0 错误，中位数约 29 秒（排队）；80 人建议并发 32 |

真实模型的单次调用通常比模拟的更慢，请以第 2 节的小规模真实压测为准。

---

## 8. 安全与隐私说明

已做的防护：
- 老师端所有页面和接口都需要老师密码；来自其他网站的写请求会被拒绝，防止跨站请求伪造；
- 应用本身只监听本机端口，外部只能经过 Caddy 访问；
- 学生只能看到自己的作答，别人的作答一律返回「找不到」；作答令牌在服务器上只保存哈希值；
- 考试模式下全程没有提示，老师公布前学生看不到分数；
- 对入口码查询、创建作答、提交回答都做了限流，单次回答最多 4000 字。

已知的剩余风险：
- **入口码可能被猜中**：入口码约有 10 亿种组合，单个 IP 每分钟最多查询 300 次，因此很难猜中，但不能保证绝对不会。重要考试请勾选「要求学号」，考完及时「关闭」。
- **共用手机**：作答进度保存在手机浏览器里，别人拿到同一部手机就能接着答。如果在机房等共用设备上考试，请提醒学生答完后关闭页面并清除浏览记录。
- **试点只有一个老师账号**：所有老师共用这一个密码。需要多个老师分别登录、各自管理时，请改用企业版（OIDC）部署。

隐私方面：
- 系统会保存学生填写的姓名、学号和全部回答内容。请事先告知学生，只填写必要信息。
- 学期结束后可以删除整个项目，该项目下的材料、考试和全部作答记录会一并删除，且无法恢复。工作台暂时没有删除按钮，请用命令操作（删除前先做一次备份）：

  ```bash
  # 列出项目，找到要删的 id
  curl -u teacher:'你的老师密码' https://exam.example.com/api/projects
  # 删除
  curl -u teacher:'你的老师密码' -X DELETE https://exam.example.com/api/projects/<项目id>
  ```
