# Pebble Relay Server v2.0 — 规格文档

## 1. 概念与目标

**pebble-relay** 是一个轻量级的多用户消息中转服务，专为 OpenClaw 与智能手表（Apple Watch / Pebble）之间的实时通信设计。

- **定位**：消息代理 + 状态广播 + 设备绑定管理
- **运行位置**：用户自己的服务器（Docker 部署）
- **核心职责**：接收 OpenClaw 推送 → 实时广播给绑定的智能手表

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     pebble-relay Server                       │
│                                                              │
│  ┌────────────┐    ┌────────────┐    ┌──────────────────┐   │
│  │   User A   │    │   User B   │    │     User C       │   │
│  │ ┌────────┐ │    │ ┌────────┐ │    │ ┌────────┐       │   │
│  │ │OpenClaw│ │    │ │OpenClaw│ │    │ │OpenClaw│       │   │
│  │ └────┬───┘ │    │ └────┬───┘ │    │ └────┬───┘       │   │
│  │ ┌────┴───┐ │    │      │     │    │      │            │   │
│  │ │ Watch1  │ │    │      │     │    │      │            │   │
│  │ │ Watch2  │ │    │      │     │    │      │            │   │
│  │ └────────┘ │    │      │     │    │      │            │   │
│  └────────────┘    └────────────┘    └──────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 数据模型

### users（用户表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 用户唯一ID（8字符UUID） |
| user_token_hash | TEXT | bcrypt hash of user_token |
| name | TEXT | 用户自定义名称 |
| created_at | INTEGER | 创建时间戳 |

### oc_instances（OpenClaw实例表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 实例唯一ID |
| user_id | TEXT | 所属用户ID |
| name | TEXT | 实例名称（如"香橙派"、"备用服务器"） |
| instance_token_hash | TEXT | bcrypt hash |
| created_at | INTEGER | 创建时间戳 |

### watch_devices（手表设备表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 设备唯一ID |
| user_id | TEXT | 所属用户ID |
| name | TEXT | 设备名称（如"Apple Watch"） |
| watch_token_hash | TEXT | bcrypt hash |
| current_instance_id | TEXT | 当前订阅的实例ID |
| created_at | INTEGER | 创建时间戳 |

### messages（消息表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 消息ID |
| instance_id | TEXT | 来源实例ID |
| type | TEXT | 消息类型 |
| content | TEXT | 消息内容（限200字） |
| source | TEXT | 来源渠道 |
| sender | TEXT | 发送者 |
| timestamp | INTEGER | 时间戳 |
| read | INTEGER | 是否已读 |

### status（状态快照表）
| 字段 | 类型 | 说明 |
|------|------|------|
| instance_id | TEXT | 关联实例ID |
| ok | INTEGER | 运行状态 |
| thinking | INTEGER | 思考中状态 |
| uptime | INTEGER | 运行时长（秒） |
| channels | TEXT | JSON数组，活跃渠道 |
| memory | INTEGER | 内存使用% |
| cpu | INTEGER | CPU使用% |
| last_message_ago | INTEGER | 最后消息距今秒数 |
| lastUpdate | INTEGER | 最后更新时间 |

---

## 4. API 协议

### 4.1 管理员接口

**检查 PocketBase 连接状态**
```
GET /api/v1/admin/check
Header: Authorization: Bearer <admin_token>
Response: {"pb_url": "...", "pb_api_token_configured": true/false, "write_ok": true/false}
```

**获取服务器信息**
```
GET /api/v1/admin/info
Header: Authorization: Bearer <admin_token>
Response: {"user_count": 2, "instance_count": 3, "watch_count": 4}
```

**管理员直接创建用户**（无需注册码）
```
POST /api/v1/admin/users
Header: Authorization: Bearer <admin_token>
Body: {"name": "我的账户"}
Response: {"ok": true, "user_id": "abc123", "user_token": "..."}
```

**删除用户**
```
DELETE /api/v1/admin/users/<user_id>
Header: Authorization: Bearer <admin_token>
Response: {"ok": true}
```

**获取所有用户（含实例）**
```
GET /api/v1/admin/users
Header: Authorization: Bearer <admin_token>
Response: {"users": [...], "total": N}
```

### 4.2 OpenClaw 实例

**注册 OpenClaw 实例**
```
POST /api/v1/oc/register
Header: X-User-Token: ...
Body: {"name": "香橙派"}
Response: {"ok": true, "instance_id": "inst1", "instance_token": "..."}
```

**推送消息**
```
POST /api/v1/oc/message
Header: X-Instance-Token: ...
Body: {"type": "message", "content": "...", "source": "feishu", "sender": "皇上"}
Response: {"ok": true, "id": "msg1"}
```

**推送状态**
```
POST /api/v1/oc/status
Header: X-Instance-Token: ...
Body: {"ok": true, "uptime": 3600, "channels": ["feishu", "telegram"], "memory": 45, "cpu": 12}
Response: {"ok": true}
```

**推送思考状态**
```
POST /api/v1/oc/thinking
Header: X-Instance-Token: ...
Body: {"thinking": true}
Response: {"ok": true}
```

### 4.3 手表设备

**绑定手表**
```
POST /api/v1/watch/bind
Header: X-User-Token: ...
Body: {"name": "Apple Watch"}
Response: {"ok": true, "watch_id": "w1", "watch_token": "..."}
```

**获取可用实例列表**
```
GET /api/v1/watch/instances
Header: X-Watch-Token: ...
Response: {"instances": [{"id": "inst1", "name": "香橙派", "subscribed": true}, ...]}
```

**切换订阅实例**
```
POST /api/v1/watch/subscribe
Header: X-Watch-Token: ...
Body: {"instance_id": "inst2"}
Response: {"ok": true, "subscribed_instance": "inst2"}
```

**获取当前状态**
```
GET /api/v1/watch/status
Header: X-Watch-Token: ...
Response: {
  "instance_id": "inst1",
  "instance_name": "香橙派",
  "ok": true,
  "thinking": false,
  "uptime": 3600,
  "channels": ["feishu", "telegram"],
  "memory": 45,
  "cpu": 12,
  "last_message_ago": 120,
  "recent_messages": [...]
}
```

**获取历史消息**
```
GET /api/v1/watch/messages?limit=20
Header: X-Watch-Token: ...
Response: {"messages": [...], "count": 20}
```

**SSE 实时事件订阅**
```
GET /api/v1/watch/events
Header: X-Watch-Token: ...
Response: SSE stream
```

---

## 5. 技术选型

- **语言**：Python 3 + Flask
- **数据库**：SQLite（零依赖，持久化）
- **外部认证**：PocketBase（pebble_users, pebble_admins collections）
- **密码哈希**：bcrypt
- **实时推送**：SSE（Server-Sent Events）
- **配置**：YAML 配置文件
- **容器**：Docker + docker-compose
- **端口**：默认 8977

---

## 6. 安全设计

- 所有 Token 均使用 bcrypt 哈希存储
- 用户间数据完全隔离（通过 user_token_hash 关联）
- PocketBase Superuser API Token 用于服务器端管理操作
- user_token 创建后仅显示一次，无法找回

---

## 7. PocketBase Collections

需要在 PocketBase 中手动创建的 Collection：

### pebble_users（普通记录集合）
| 字段 | 类型 |
|------|------|
| name | Text |
| user_token | Text |

### pebble_admins（PocketBase 内置 Auth Collection）
- 使用 PocketBase Admin 面板登录
- 用于管理员认证

### pebble_reg_codes（可选，已废弃）
- 旧版本用于注册码，已不需要

---

## 8. 部署

### 快速部署

```bash
# 克隆仓库
git clone https://github.com/hkgood/pebble-relay.git /opt/pebble-relay
cd /opt/pebble-relay

# 配置环境变量（创建 .env 文件）
cat > .env << EOF
PB_URL=https://pb.osglab.com
PB_ADMIN_EMAIL=your@email.com
PB_ADMIN_PASSWORD=your_password
PB_API_TOKEN=your_pocketbase_superuser_api_token
EOF

# 启动服务
docker compose up -d
```

### 获取 PocketBase Superuser API Token

1. 登录 PocketBase 管理面板
2. 进入 **Settings → Authentication → API Tokens**
3. 创建一个 Superuser API Token（需要 Superuser 权限）
4. 将 Token 填入 `PB_API_TOKEN` 环境变量

> ⚠️ 没有 `PB_API_TOKEN` 将无法创建用户。普通 PocketBase admin 认证权限不足以写入 `pebble_users` 集合。

---

## 9. OpenClaw 集成

在 OpenClaw 端配置：
1. 管理员在 pebble-relay 后台创建用户 → 获得 user_token
2. 用户将 user_token 配置到 watch-claw 插件
3. watch-claw 插件自动注册 OpenClaw 实例 → 获得 instance_token
4. watch-claw 定时推送 OpenClaw 状态到 pebble-relay
