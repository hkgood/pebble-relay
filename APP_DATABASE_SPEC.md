# OpenClaw Admin App — 数据库规格文档

## 概述

OpenClaw Admin App 使用 PocketBase 作为后端数据库，与 pebble-relay 共用同一 PocketBase 实例 (`https://pb.osglab.com`)。

---

## PocketBase Collections

### 1. relay_users（用户表）⭐ Auth Collection

**类型**: `auth`（内置 email + password 自动字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Text (自动) | PocketBase 自动生成 |
| email | Email (自动) | 用户邮箱，用于登录 |
| password | Password (自动) | 用户密码（bcrypt 哈希）|
| name | Text | 用户昵称 |
| relay_token | Text | 用户凭证 Token（pebble-relay 兼容）|

**访问规则**:
| 操作 | 规则 |
|------|------|
| List | 所有人 |
| View | 登录用户本人 |
| Create | 所有人（注册）|
| Update | 本人 (`@request.auth.id = id`) |
| Delete | 本人 |

**重要**: 必须是 `auth` 类型才能使用 PocketBase 内置的 `authWithPassword` 和 `requestPasswordReset` 功能。

---

### 2. oc_instances（OpenClaw 实例表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Text (自动) | PocketBase 自动生成 |
| user_id | Text | 关联用户 ID（relay_users.id）|
| name | Text | 实例名称（如"香橙派"）|
| instance_id | Text | 实例唯一标识 |
| instance_token | Text | 实例凭证 Token（bcrypt 哈希）|

**访问规则**:
| 操作 | 规则 |
|------|------|
| List | 本人 (`user_id = @request.auth.id`) |
| View | 本人 |
| Create | 登录用户 |
| Update | 本人 |
| Delete | 本人 |

---

### 3. relay_status（状态快照表）

由 pebble-relay 写入，App 只读。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Text (自动) | PocketBase 自动生成 |
| instance_id | Text | 关联实例 ID |
| ok | Bool | 运行状态（true=正常）|
| thinking | Bool | 思考中状态 |
| uptime | Number | 运行时长（秒）|
| channels | Text | 活跃渠道（逗号分隔）|
| memory | Number | 内存使用% |
| cpu | Number | CPU使用% |
| last_message_ago | Number | 最后消息距今秒数 |
| lastUpdate | Number | 最后更新时间戳 |

**访问规则**: 登录用户可读

---

### 4. watch_devices（手表设备表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Text (自动) | PocketBase 自动生成 |
| user_id | Text | 所属用户 ID |
| name | Text | 设备名称 |
| watch_token | Text | 手表凭证 Token |

---

### 5. relay_messages（消息表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Text (自动) | PocketBase 自动生成 |
| instance_id | Text | 来源实例 ID |
| type | Text | 消息类型 |
| content | Text | 消息内容 |
| source | Text | 来源渠道 |
| sender | Text | 发送者 |
| timestamp | Number | 时间戳 |
| read | Bool | 是否已读 |

---

## App 认证流程

### 登录
```
App → POST /api/collections/relay_users/auth-with-password
Body: {"identity": "email", "password": "password"}
→ 返回 token + user record
```

### 注册
```
App → POST /api/collections/relay_users/records
Body: {"email": "...", "password": "...", "passwordConfirm": "...", "name": "..."}
→ 创建用户并自动登录
```

### 忘记密码
```
App → POST /api/collections/relay_users/request-password-reset
Body: {"email": "..."}
→ PocketBase 发送重置邮件
```

### 验证 Token
```
App → POST /api/collections/relay_users/auth-refresh
Header: Authorization: Bearer <token>
→ 验证 token 是否有效
```

---

## 迁移说明

### relay_users 类型迁移（base → auth）

**背景**: 旧版 `relay_users` 是 `base` 类型集合，无 email/password 字段，无法使用 PocketBase 内置认证。

**迁移步骤**:
1. 备份旧用户数据（id, name, relay_token）
2. 删除旧的 `relay_users`（base）集合
3. 创建新的 `relay_users`（auth）集合
4. 用迁移脚本重新创建用户（分配临时密码）
5. 通知用户通过"忘记密码"重置密码

**迁移用户列表**:
| 旧 ID | name | relay_token | 新 ID |
|-------|------|-------------|-------|
| 0cxmbb1803ypbmd | huangshang | test1 | lz8l0qlnpwsu8vq |
| nzl1trq1eqir6bx | testuser | test2 | sbewf4f1l01fxae |

---

## 环境

- **PocketBase**: https://pb.osglab.com
- **PocketBase Admin**: rocky.hk@gmail.com
- **pebble-relay**: http://115.29.162.18:8977
