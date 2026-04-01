# pebble-relay ⌚

**OpenClaw 与智能手表之间的实时消息中转服务**

支持多用户、多 OpenClaw 实例、多手表设备绑定。

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

## 功能特性

- 🔄 **实时消息推送** — OpenClaw 收到消息立即推送到手表
- ⏳ **思考状态** — 手表显示 OpenClaw 是否正在处理
- 📊 **运行状态** — CPU、内存、运行时长、活跃渠道
- 👥 **多用户支持** — 一个服务器支持多个用户，数据完全隔离
- ⌚ **多设备绑定** — 一个用户可绑定多个手表，手表可切换查看不同 OpenClaw 实例
- 🔒 **安全认证** — 所有 Token 使用 bcrypt 哈希存储

---

## 快速开始

### 1. 部署服务

```bash
git clone https://github.com/hkgood/pebble-relay.git /opt/pebble-relay
cd /opt/pebble-relay
docker compose up -d
```

### 2. 设置管理员密码

```bash
curl -X POST http://localhost:8977/api/v1/admin/setup \
  -H "Content-Type: application/json" \
  -d '{"password": "your-admin-password"}'
```

### 3. 获取注册码

```bash
curl http://localhost:8977/api/v1/admin/info \
  -H "X-Admin-Password: your-admin-password"
# 返回: {"registration_code": "abc123...", ...}
```

### 4. 注册用户

```bash
curl -X POST http://localhost:8977/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{"registration_code": "abc123...", "name": "我的账户"}'
# 返回: {"user_id": "xyz789", "user_token": "..."}
```

### 5. 注册 OpenClaw 实例

```bash
curl -X POST http://localhost:8977/api/v1/oc/register \
  -H "Content-Type: application/json" \
  -H "X-User-Token: your-user-token" \
  -d '{"name": "香橙派"}'
# 返回: {"instance_id": "inst1", "instance_token": "..."}
```

### 6. 绑定手表设备

```bash
curl -X POST http://localhost:8977/api/v1/watch/bind \
  -H "Content-Type: application/json" \
  -H "X-User-Token: your-user-token" \
  -d '{"name": "Apple Watch"}'
# 返回: {"watch_id": "w1", "watch_token": "..."}
```

---

## API 文档

### 管理员接口

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/admin/setup` | 设置管理员密码（首次） |
| GET | `/api/v1/admin/info` | 获取服务器信息 |
| POST | `/api/v1/admin/registration-code` | 重新生成注册码 |

### 用户接口

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/register` | 注册新用户 |

### OpenClaw 接口

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/oc/register` | 注册 OpenClaw 实例 |
| POST | `/api/v1/oc/message` | 推送消息 |
| POST | `/api/v1/oc/status` | 推送运行状态 |
| POST | `/api/v1/oc/thinking` | 推送思考状态 |

### 手表接口

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/watch/bind` | 绑定手表设备 |
| GET | `/api/v1/watch/instances` | 获取可用实例列表 |
| POST | `/api/v1/watch/subscribe` | 切换订阅实例 |
| GET | `/api/v1/watch/status` | 获取当前状态 |
| GET | `/api/v1/watch/messages` | 获取历史消息 |
| GET | `/api/v1/watch/events` | SSE 实时事件流 |

---

## OpenClaw 集成

在 OpenClaw 端，配置 instance_token 后即可推送消息：

```bash
# 推送消息
curl -X POST http://your-server:8977/api/v1/oc/message \
  -H "Content-Type: application/json" \
  -H "X-Instance-Token: your-instance-token" \
  -d '{"type":"message","content":"皇上，有新消息！","source":"feishu","sender":"皇上"}'

# 推送思考状态
curl -X POST http://your-server:8977/api/v1/oc/thinking \
  -H "Content-Type: application/json" \
  -H "X-Instance-Token: your-instance-token" \
  -d '{"thinking": true}'
```

---

## 数据持久化

- 消息自动保留 7 天（最多 200 条/实例）
- 所有 Token 使用 bcrypt 加密存储
- SQLite 数据库存储在 Docker volume 中

---

## 项目结构

```
pebble-relay/
├── server.py          # 主服务
├── config.yaml        # 配置文件（首次自动生成）
├── Dockerfile         # Docker 构建
├── docker-compose.yml  # 一键部署
├── SPEC.md           # 规格文档
└── README.md         # 本文件
```

---

## License

MIT
