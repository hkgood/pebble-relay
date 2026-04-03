# Pebble Relay Server v2.1 — 规格文档

## 1. 概念与目标

**pebble-relay** 是一个轻量级的多用户消息中转服务，专为 OpenClaw 与智能手表（Apple Watch / Pebble）之间的实时通信设计。

- **定位**：消息代理 + 状态广播 + 设备绑定管理
- **运行位置**：用户自己的服务器（Docker 部署）
- **核心职责**：接收 OpenClaw 推送 → 实时广播给绑定的智能手表
- **数据存储**：所有业务数据存储在 PocketBase（用户、实例、手表、状态、消息）

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                   PocketBase (pb.osglab.com)                  │
│  Collections: relay_users | oc_instances | watch_devices       │
│              | relay_status | relay_messages                  │
│  Admin Auth: _superusers (rocky.hk@gmail.com)                 │
└──────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTP API (PB_SUPERUSER credentials)
┌──────────────────────────────────────────────────────────────┐
│                  pebble-relay Server (Docker)                  │
│                        Port 8977                              │
│  relay_users ←→ oc_instances ←→ watch_devices                │
│  Status: upsert (更新现有条目，不新增)                         │
└──────────────────────────────────────────────────────────────┘
         ▲                                    ▲
         │ X-Relay-Token                     │ X-Watch-Token
    OpenClaw                          Pebble Watch
```

---

## 3. PocketBase Collections

### relay_users（用户表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Text (PocketBase) | 自动生成的用户ID |
| name | Text | 用户名称 |
| relay_token | Text | 用户凭证 Token（用于 OpenClaw 注册） |

### oc_instances（OpenClaw实例表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Text | 自动生成的实例ID |
| user_id | Text | 所属用户ID（关联 relay_users.id） |
| name | Text | 实例名称（如"香橙派"、"备用服务器"） |
| instance_token | Text | 实例凭证 Token（bcrypt 哈希存储） |

### watch_devices（手表设备表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Text | 自动生成的设备ID |
| user_id | Text | 所属用户ID |
| name | Text | 设备名称（如"Apple Watch"） |
| watch_token | Text | 手表凭证 Token（bcrypt 哈希存储） |
| current_instance_id | Text | 当前订阅的实例ID |

### relay_status（状态快照表）
| 字段 | 类型 | 说明 |
|------|------|------|
| instance_id | Text | 关联实例ID |
| ok | Number | 运行状态（1=正常，0=异常） |
| thinking | Number | 思考中状态 |
| uptime | Number | 运行时长（秒） |
| channels | Text | 活跃渠道（逗号分隔） |
| memory | Number | 内存使用% |
| cpu | Number | CPU使用% |
| last_message_ago | Number | 最后消息距今秒数 |
| lastUpdate | Number | 最后更新时间戳 |

> ⚠️ relay_status 使用 **upsert 模式**：每次状态更新先查找 `instance_id` 对应的记录，存在则 PATCH，不存在则 POST。

### relay_messages（消息表）
| 字段 | 类型 | 说明 |
|------|------|------|
| instance_id | Text | 来源实例ID |
| type | Text | 消息类型 |
| content | Text | 消息内容（限200字） |
| source | Text | 来源渠道 |
| sender | Text | 发送者 |
| timestamp | Number | 时间戳 |
| read | Number | 是否已读（0/1） |

---

## 4. API 协议

### 4.1 管理员接口

**设置管理员密码（首次）**
```
POST /api/v1/admin/setup
Body: {"password": "your_password"}
Response: {"ok": true}
```

**管理员登录验证**
所有 admin API 需要 Header: `X-Admin-Token: <password_hash>`

**获取服务器信息**
```
GET /api/v1/admin/info
Header: X-Admin-Token: ...
Response: {"user_count": N, "instance_count": N, "watch_count": N}
```

**检查连接**
```
GET /api/v1/admin/check
Header: X-Admin-Token: ...
Response: {"ok": true, "pb_connected": true}
```

**创建用户**
```
POST /api/v1/admin/users
Header: X-Admin-Token: ...
Body: {"name": "用户名"}
Response: {"ok": true, "user_id": "...", "user_token": "..."}
```

**删除用户（级联删除关联实例和手表）**
```
DELETE /api/v1/admin/users/<user_id>
Header: X-Admin-Token: ...
Response: {"ok": true}
```

**获取所有用户（含实例和手表信息）**
```
GET /api/v1/admin/users
Header: X-Admin-Token: ...
Response: {"users": [...], "total": N}
```

### 4.2 OpenClaw 实例

**注册 OpenClaw 实例**
```
POST /api/v1/oc/register
Header: X-User-Token: <relay_token>
Body: {"name": "香橙派"}
Response: {"ok": true, "instance_id": "...", "instance_token": "..."}
```

**推送状态（Upsert 模式）**
```
POST /api/v1/oc/status
Header: X-Instance-Token: <instance_token>
Body: {"ok": true, "uptime": 3600, "channels": ["feishu"], "memory": 45, "cpu": 12}
Response: {"ok": true}
```

**推送思考状态**
```
POST /api/v1/oc/thinking
Header: X-Instance-Token: <instance_token>
Body: {"thinking": true}
Response: {"ok": true}
```

**推送消息**
```
POST /api/v1/oc/message
Header: X-Instance-Token: <instance_token>
Body: {"type": "message", "content": "...", "source": "feishu", "sender": "皇上"}
Response: {"ok": true, "id": "..."}
```

### 4.3 手表设备

**绑定手表**
```
POST /api/v1/watch/bind
Header: X-User-Token: <relay_token>
Body: {"name": "Apple Watch"}
Response: {"ok": true, "watch_id": "...", "watch_token": "..."}
```

**获取可用实例列表**
```
GET /api/v1/watch/instances
Header: X-Watch-Token: <watch_token>
Response: {"instances": [{"id": "...", "name": "香橙派", "subscribed": true}, ...]}
```

**切换订阅实例**
```
POST /api/v1/watch/subscribe
Header: X-Watch-Token: <watch_token>
Body: {"instance_id": "..."}
Response: {"ok": true}
```

**获取当前状态**
```
GET /api/v1/watch/status
Header: X-Watch-Token: <watch_token>
Response: {
  "ok": true, "thinking": false, "uptime": 3600,
  "channels": ["feishu", "telegram"],
  "memory": 45, "cpu": 12, "last_message_ago": 120,
  "recent_messages": [...], "instance_name": "香橙派"
}
```

**获取历史消息**
```
GET /api/v1/watch/messages?limit=20
Header: X-Watch-Token: <watch_token>
Response: {"messages": [...], "count": 20}
```

**SSE 实时事件订阅**
```
GET /api/v1/watch/events
Header: X-Watch-Token: <watch_token>
Response: SSE stream
```

---

## 5. 技术选型

- **语言**：Python 3 + Flask
- **数据库**：PocketBase（relay_users, oc_instances, watch_devices, relay_status, relay_messages）
- **密码哈希**：bcrypt
- **实时推送**：SSE（Server-Sent Events）
- **配置**：YAML 配置文件
- **容器**：Docker + docker-compose
- **端口**：默认 8977

---

## 6. 安全设计

- 所有 Token 均使用 bcrypt 哈希存储（验证时比对 hash）
- 用户间数据完全隔离（通过 user_id 关联）
- relay_token 创建后仅显示一次，无法找回
- 状态更新使用 upsert（按 instance_id 定位，不新增浪费资源）

---

## 7. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PB_URL` | https://pb.osglab.com | PocketBase 服务器地址 |
| `PB_SUPERUSER_EMAIL` | rocky.hk@gmail.com | PocketBase Superuser 邮箱 |
| `PB_SUPERUSER_PASSWORD` | gz203799 | PocketBase Superuser 密码 |
| `CONFIG_PATH` | /data/config.yaml | 配置文件路径 |
| `PORT` | 8977 | 服务端口 |

---

## 8. 部署

```bash
# 克隆仓库
git clone https://github.com/hkgood/pebble-relay.git /opt/pebble-relay
cd /opt/pebble-relay

# 配置环境变量
cat > .env << EOF
PB_URL=https://pb.osglab.com
PB_SUPERUSER_EMAIL=rocky.hk@gmail.com
PB_SUPERUSER_PASSWORD=your_password
EOF

# 启动服务
docker compose up -d

# 初始化管理员密码
curl -X POST http://localhost:8977/api/v1/admin/setup \
  -H "Content-Type: application/json" \
  -d '{"password":"your_admin_password"}'
```

---

## 9. OpenClaw 集成

1. 管理员在 pebble-relay 后台创建用户 → 获得 relay_token
2. 用户将 relay_token 配置到 watch-claw 插件
3. watch-claw 插件自动注册 OpenClaw 实例 → 获得 instance_token
4. watch-claw 定时推送 OpenClaw 状态到 pebble-relay（upsert 模式）
