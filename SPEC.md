# Pebble Relay Server — 规格文档

## 1. 概念与目标

一个小型的 Docker 服务，作为 OpenClaw 与 Pebble Time 之间的消息中转站。

- **定位**：消息代理 + 状态广播服务
- **运行位置**：皇上自己的服务器（固定 IP + Docker）
- **核心职责**：接收 OpenClaw 推送，广播给 Pebble 手表

## 2. 系统架构

```
OpenClaw (香橙派)  --POST /webhook-->  Pebble Relay (Docker)  <--SSE--  Pebble Time
                                           │
                                           └── SQLite (消息持久化)
```

## 3. 功能清单

### 3.1 Webhook 接收端（OpenClaw → Relay）
- `POST /webhook` — 接收 OpenClaw 事件通知
  - 消息类型：`message`, `status`, `alert`
  - payload: `{"type": "message", "content": "...", "source": "feishu", "sender": "皇上", "timestamp": 123456}`
- `POST /status` — 接收 OpenClaw 状态更新
  - payload: `{"ok": true, "sessions": 3, "uptime": 3600, "channels": ["feishu","telegram"]}`
- `GET /health` — 中转服务自身健康检查（供 OpenClaw 探测）

### 3.2 SSE 广播端（Relay → Pebble）
- `GET /events` — SSE 流，推送所有事件给 Pebble
  - 事件格式：`data: {"type":"message","content":"...","source":"feishu","timestamp":...}`
  - 支持 `?since=<timestamp>` 参数，只拉取该时间戳之后的未读事件

### 3.3 状态查询端（Pebble → Relay）
- `GET /status` — 返回最新 OpenClaw 状态（JSON）
- `GET /messages?limit=10` — 返回最近 N 条消息记录

### 3.4 管理接口
- `GET /admin/stats` — 服务统计（消息计数、连接数、最后事件时间）
- `DELETE /messages` — 清空消息队列（可选）

## 4. 数据模型

### Message（消息记录）
```json
{
  "id": "uuid",
  "type": "message|status|alert",
  "content": "消息内容摘要（限制100字）",
  "source": "feishu|telegram|system",
  "sender": "发送者名称",
  "timestamp": 1234567890,
  "read": false
}
```

### Status（状态快照）
```json
{
  "ok": true,
  "sessions": 3,
  "uptime": 3600,
  "channels": ["feishu", "telegram"],
  "lastUpdate": 1234567890
}
```

## 5. 技术选型

- **语言**：Python 3 + Flask
- **数据库**：SQLite（零依赖，持久化）
- **实时推送**：SSE（Server-Sent Events），Pebble 原生支持
- **容器**：Docker + docker-compose
- **端口**：默认 `8977`

## 6. 安全考量

- Webhook 端点需简单的 token 验证（防止恶意推送）
- SSE 端点不过滤（手表 WiFi 网络可控）
- 所有数据内网传输，不暴露到公网（除非皇上主动端口映射）

## 7. Docker 部署

```yaml
# docker-compose.yml
services:
  pebble-relay:
    image: pebble-relay
    ports:
      - "8977:8977"
    environment:
      - WEBHOOK_TOKEN=your-secret-token
    restart: unless-stopped
```

## 8. OpenClaw 配置

OpenClaw 通过 `automation` 或 webhook 插件调用：
```
POST http://your-server:8977/webhook
Header: X-Token: your-secret-token
Body: {"type": "message", "content": "...", "source": "feishu", "sender": "皇上"}
```
