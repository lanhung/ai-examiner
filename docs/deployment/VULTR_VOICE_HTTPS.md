# Vultr 实时语音与 HTTPS 部署

## 为什么公网语音必须使用 HTTPS

浏览器只在安全上下文中允许 `getUserMedia()` 访问麦克风。`localhost` 属于例外，但公网 `http://IP:8000` 通常只能打开网页，无法可靠启用麦克风。因此：

- 本地测试：SSH 隧道后打开 `http://127.0.0.1:8000`；
- 手机和公网电脑：配置域名并使用 Caddy 自动 HTTPS。

## 方案 A：SSH 隧道测试

在本地电脑执行：

```bash
ssh -L 8000:127.0.0.1:8000 root@VULTR_IP
```

浏览器打开：

```text
http://127.0.0.1:8000
```

## 方案 B：域名 + Caddy HTTPS

1. 将域名 A 记录指向 Vultr 公网 IP。
2. 在 Vultr Firewall 和 UFW 开放 TCP 80/443，并开放 UDP 443 以支持 HTTP/3。
3. `.env` 设置：

```env
SITE_ADDRESS=exam.example.com
OPENAI_API_KEY=你的新密钥
REALTIME_MODEL=gpt-realtime-2.1
REALTIME_VOICE=marin
REALTIME_VAD_EAGERNESS=medium
```

4. 启动：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.https.yml \
  up -d --build
```

5. 查看证书日志：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.https.yml logs -f caddy
```

6. 访问：

```text
https://exam.example.com
```

## 防火墙

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw reload
```

当前应用没有完整登录系统。评估阶段建议在 Vultr Firewall 中限制来源 IP，或使用 Cloudflare Access / 基础认证反向代理。

## 语音故障排查

### 网页能打开但麦克风不可用

- 检查地址是否为 HTTPS；
- 检查浏览器站点权限中的麦克风；
- iPhone 使用 Safari，Android 使用 Chrome；
- 关闭占用麦克风的会议软件；
- 查看浏览器 Console 中 `getUserMedia` 错误。

### 连接后没有声音

```bash
docker compose logs --tail=200 ai-examiner
curl -s https://你的域名/api/voice/config | python -m json.tool
```

确认 `ready=true`，并确认 OpenAI 账户可访问配置的 Realtime 模型。

### 嘈杂环境频繁抢话

在页面中：

- 将 VAD 设为“耐心等待”；或
- 切换“按住说话”模式。

按住说话模式关闭自动 VAD，在松开按钮时立即提交音频并触发回应。
