"""
Pebble Relay Server
OpenClaw <-> Pebble Time 消息中转服务
"""

import os
import sqlite3
import uuid
import time
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify, Response, stream_with_context
from functools import wraps

app = Flask(__name__)

# 配置
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "pebble-relay-secret-token")
DB_PATH = os.environ.get("DB_PATH", "/data/relay.db")
PORT = int(os.environ.get("PORT", "8977"))

# 内存中的 SSE 客户端列表（线程安全）
sse_clients = []
sse_clients_lock = threading.Lock()

# ============================================================
# 数据库初始化
# ============================================================

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT DEFAULT 'system',
            sender TEXT DEFAULT '',
            timestamp INTEGER NOT NULL,
            read INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS status (
            key TEXT PRIMARY KEY,
            ok INTEGER DEFAULT 1,
            sessions INTEGER DEFAULT 0,
            uptime INTEGER DEFAULT 0,
            channels TEXT DEFAULT '[]',
            lastUpdate INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================
# 工具函数
# ============================================================

def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Token", "")
        if token != WEBHOOK_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def get_timestamp():
    return int(time.time())

def save_message(msg_type, content, source="system", sender=""):
    conn = get_db()
    c = conn.cursor()
    mid = str(uuid.uuid4())[:8]
    ts = get_timestamp()
    # 限制 content 长度
    content = content[:200]
    c.execute(
        "INSERT INTO messages (id, type, content, source, sender, timestamp, read) VALUES (?, ?, ?, ?, ?, ?, 0)",
        (mid, msg_type, content, source, sender, ts)
    )
    conn.commit()
    conn.close()
    return mid

def save_status(ok, sessions, uptime, channels):
    conn = get_db()
    c = conn.cursor()
    ts = get_timestamp()
    channels_json = json.dumps(channels if isinstance(channels, list) else [])
    c.execute("""
        INSERT OR REPLACE INTO status (key, ok, sessions, uptime, channels, lastUpdate)
        VALUES ('main', ?, ?, ?, ?, ?)
    """, (1 if ok else 0, sessions, uptime, channels_json, ts))
    conn.commit()
    conn.close()

def notify_sse_clients(event_data):
    """广播 SSE 事件到所有已连接的 Pebble 客户端"""
    with sse_clients_lock:
        dead = []
        for client in sse_clients:
            try:
                client['queue'].put(event_data)
            except:
                dead.append(client)
        for client in dead:
            sse_clients.remove(client)

# ============================================================
# Webhook 端点（OpenClaw → Relay）
# ============================================================

@app.route("/webhook", methods=["POST"])
# @require_token  # temporarily disabled for testing
def webhook():
    """接收 OpenClaw 事件"""
    try:
        data = request.get_json() or {}
    except:
        return jsonify({"error": "Invalid JSON"}), 400

    msg_type = data.get("type", "message")
    content = data.get("content", "")
    source = data.get("source", "openclaw")
    sender = data.get("sender", "系统")

    if not content:
        return jsonify({"error": "content is required"}), 400

    mid = save_message(msg_type, content, source, sender)

    # 广播给 SSE 客户端
    event = {
        "type": msg_type,
        "content": content,
        "source": source,
        "sender": sender,
        "timestamp": get_timestamp(),
        "id": mid
    }
    notify_sse_clients(json.dumps(event))

    return jsonify({"ok": True, "id": mid}), 200


@app.route("/status", methods=["POST"])
@require_token
def post_status():
    """接收 OpenClaw 状态更新"""
    try:
        data = request.get_json() or {}
    except:
        return jsonify({"error": "Invalid JSON"}), 400

    ok = data.get("ok", True)
    sessions = data.get("sessions", 0)
    uptime = data.get("uptime", 0)
    channels = data.get("channels", [])

    save_status(ok, sessions, uptime, channels)

    # 广播状态变更给 SSE 客户端
    event = {
        "type": "status",
        "ok": ok,
        "sessions": sessions,
        "uptime": uptime,
        "channels": channels,
        "timestamp": get_timestamp()
    }
    notify_sse_clients(json.dumps(event))

    return jsonify({"ok": True}), 200


@app.route("/health", methods=["GET"])
def health():
    """中转服务自身健康检查"""
    return jsonify({"ok": True, "service": "pebble-relay", "time": get_timestamp()}), 200


# ============================================================
# SSE 端点（Pebble → Relay）
# ============================================================

@app.route("/events")
def events():
    """SSE 流，推送所有事件给 Pebble"""
    # 获取自某个时间戳以来的未读消息
    since = request.args.get("since", type=int, default=0)

    def generate():
        queue = []
        client = {"queue": queue}
        with sse_clients_lock:
            sse_clients.append(client)

        try:
            # 先发送一次连接成功事件
            yield "data: {\"type\":\"connected\",\"time\":%d}\n\n" % get_timestamp()

            # 发送未读消息
            if since > 0:
                conn = get_db()
                c = conn.cursor()
                c.execute(
                    "SELECT * FROM messages WHERE timestamp > ? AND read = 0 ORDER BY timestamp ASC",
                    (since,)
                )
                for row in c.fetchall():
                    msg = dict(row)
                    yield "data: %s\n\n" % json.dumps({
                        "type": msg["type"],
                        "content": msg["content"],
                        "source": msg["source"],
                        "sender": msg["sender"],
                        "timestamp": msg["timestamp"],
                        "id": msg["id"]
                    })
                conn.close()

            # 保持连接，持续推送新事件
            while True:
                if queue:
                    while queue:
                        item = queue.pop(0)
                        yield "data: %s\n\n" % item
                else:
                    time.sleep(0.5)

        finally:
            with sse_clients_lock:
                if client in sse_clients:
                    sse_clients.remove(client)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================
# 状态查询端点（Pebble → Relay）
# ============================================================

@app.route("/status", methods=["GET"])
def get_status():
    """返回最新 OpenClaw 状态"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM status WHERE key = 'main'")
    row = c.fetchone()
    conn.close()

    if row:
        return jsonify({
            "ok": bool(row["ok"]),
            "sessions": row["sessions"],
            "uptime": row["uptime"],
            "channels": json.loads(row["channels"]),
            "lastUpdate": row["lastUpdate"]
        }), 200
    else:
        return jsonify({
            "ok": False,
            "sessions": 0,
            "uptime": 0,
            "channels": [],
            "lastUpdate": 0
        }), 200


@app.route("/messages", methods=["GET"])
def get_messages():
    """返回最近消息记录"""
    limit = request.args.get("limit", default=10, type=int)
    limit = min(limit, 50)  # 最多50条

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()

    return jsonify({"messages": rows, "count": len(rows)}), 200


# ============================================================
# 管理端点
# ============================================================

@app.route("/admin/stats", methods=["GET"])
def admin_stats():
    """服务统计"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as total FROM messages")
    total = c.fetchone()["total"]
    c.execute("SELECT COUNT(*) as unread FROM messages WHERE read = 0")
    unread = c.fetchone()["unread"]
    conn.close()

    with sse_clients_lock:
        client_count = len(sse_clients)

    return jsonify({
        "totalMessages": total,
        "unreadMessages": unread,
        "sseClients": client_count,
        "uptime": get_timestamp()
    }), 200


@app.route("/messages", methods=["DELETE"])
@require_token
def delete_messages():
    """清空消息队列"""
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()
    deleted = c.rowcount
    conn.close()
    return jsonify({"deleted": deleted}), 200


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    init_db()
    print(f"[pebble-relay] Starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
