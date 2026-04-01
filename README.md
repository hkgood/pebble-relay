# Pebble Relay Server

OpenClaw 与 Pebble Time 之间的消息中转服务。

## 快速部署

### 1. 上传代码到服务器

```bash
scp -r pebble-relay user@your-server:/opt/pebble-relay/
```

### 2. 配置环境变量

创建 `.env` 文件（可选，默认 token 是 `pebble-relay-secret-token`）：

```bash
cd /opt/pebble-relay
echo "WEBHOOK_TOKEN=你的安全密码" > .env
```

### 3. 启动服务

```bash
docker compose up -d
docker compose logs -f
```

### 4. 验证服务

```bash
curl http://localhost:8977/health
# 应返回: {"ok": true, "service": "pebble-relay", "time": ...}
```

---

## API 文档

### OpenClaw → Relay（Webhook 推送）

**发送消息**
```bash
curl -X POST http://your-server:8977/webhook \
  -H "Content-Type: application/json" \
  -H "X-Token: 你的WEBHOOK_TOKEN" \
  -d '{
    "type": "message",
    "content": "皇上，有新消息！",
    "source": "feishu",
    "sender": "中书省"
  }'
```

**更新状态**
```bash
curl -X POST http://your-server:8977/status \
  -H "Content-Type: application/json" \
  -H "X-Token: 你的WEBHOOK_TOKEN" \
  -d '{
    "ok": true,
    "sessions": 3,
    "uptime": 3600,
    "channels": ["feishu", "telegram"]
  }'
```

### Pebble → Relay（SSE 订阅）

**订阅实时事件**
```bash
curl -N http://your-server:8977/events
# 返回 SSE 流，每个事件格式: data: {...}\n\n
```

**查询状态**
```bash
curl http://your-server:8977/status
# 返回: {"ok": true, "sessions": 3, "uptime": 3600, "channels": ["feishu"], "lastUpdate": ...}
```

**查询历史消息**
```bash
curl http://your-server:8977/messages?limit=5
```

---

## OpenClaw 自动化配置

在 OpenClaw 中创建 automation 或 script，调用 webhook：

```
POST http://你的服务器IP:8977/webhook
Header: X-Token: 你的WEBHOOK_TOKEN
Body: {"type": "message", "content": "{{trigger.messagePreview}}", "source": "{{trigger.channel}}", "sender": "{{trigger.senderName}}"}
```

---

## 服务统计

```bash
curl http://your-server:8977/admin/stats
# 返回: {"totalMessages": 100, "unreadMessages": 5, "sseClients": 1}
```

---

## 目录结构

```
pebble-relay/
├── server.py          # 主程序（Flask）
├── Dockerfile         # Docker 构建文件
├── docker-compose.yml # docker-compose 配置
├── SPEC.md           # 规格文档
└── README.md         # 本文件
```

---

## 注意事项

- 默认端口 `8977`，确保服务器防火墙开放
- `WEBHOOK_TOKEN` 必须与 OpenClaw 配置中的一致
- SQLite 数据库存储在 Docker volume 中，重启不丢数据
- SSE 连接数无限制，但建议 Pebble 保持一个长连接
