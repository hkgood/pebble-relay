"""
pebble-relay v2.0
Multi-user relay server for OpenClaw <-> Smartwatch
Supports: multiple OpenClaw instances, multiple watch devices, user isolation
"""

import os
import sqlite3
import uuid
import time
import json
import secrets
import threading
import hashlib
import bcrypt
from datetime import datetime
from pathlib import Path
from functools import wraps
from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory
import yaml

app = Flask(__name__)

# ============================================================
# Configuration
# ============================================================

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/data/config.yaml")
DB_PATH = os.environ.get("DB_PATH", "/data/relay.db")
PORT = int(os.environ.get("PORT", "8977"))

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    return {
        "server": {
            "port": PORT,
            "debug": False
        },
        "admin": {
            "password_hash": "",  # Set on first run
            "registration_code": secrets.token_hex(8)  # Auto-generated
        },
        "limits": {
            "message_retention_days": 7,
            "max_messages_per_instance": 200
        }
    }

config = load_config()

# In-memory SSE clients: {watch_token: {"queue": [], "instance_id": None}}
sse_clients = {}
sse_clients_lock = threading.Lock()

# ============================================================
# Database
# ============================================================

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            user_token_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            created_at INTEGER NOT NULL
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS oc_instances (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            instance_token_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS watch_devices (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            watch_token_hash TEXT NOT NULL,
            current_instance_id TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (current_instance_id) REFERENCES oc_instances(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT DEFAULT '',
            sender TEXT DEFAULT '',
            timestamp INTEGER NOT NULL,
            read INTEGER DEFAULT 0,
            FOREIGN KEY (instance_id) REFERENCES oc_instances(id)
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS status (
            instance_id TEXT PRIMARY KEY,
            ok INTEGER DEFAULT 1,
            thinking INTEGER DEFAULT 0,
            uptime INTEGER DEFAULT 0,
            channels TEXT DEFAULT '[]',
            memory INTEGER DEFAULT 0,
            cpu INTEGER DEFAULT 0,
            last_message_ago INTEGER DEFAULT 0,
            lastUpdate INTEGER NOT NULL,
            FOREIGN KEY (instance_id) REFERENCES oc_instances(id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_token(token: str) -> str:
    return bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()

def verify_token(token: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(token.encode(), hashed.encode())
    except:
        return False

def get_instance_by_token(instance_token: str) -> dict | None:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM oc_instances")
    for row in c.fetchall():
        if verify_token(instance_token, row['instance_token_hash']):
            return dict(row)
    conn.close()
    return None

def get_user_by_token(user_token: str) -> dict | None:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    for row in c.fetchall():
        if verify_token(user_token, row['user_token_hash']):
            return dict(row)
    conn.close()
    return None

def get_watch_by_token(watch_token: str) -> dict | None:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM watch_devices")
    for row in c.fetchall():
        if verify_token(watch_token, row['watch_token_hash']):
            return dict(row)
    conn.close()
    return None

# ============================================================
# Auth decorators
# ============================================================

def require_instance_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get token from header
        token = request.headers.get("X-Instance-Token", "")
        if not token:
            return jsonify({"error": "Missing X-Instance-Token"}), 401
        
        instance = get_instance_by_token(token)
        if not instance:
            return jsonify({"error": "Invalid instance token"}), 401
        
        request.instance = instance
        return f(*args, **kwargs)
    return decorated

def require_user_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-User-Token", "")
        if not token:
            return jsonify({"error": "Missing X-User-Token"}), 401
        
        user = get_user_by_token(token)
        if not user:
            return jsonify({"error": "Invalid user token"}), 401
        
        request.user = user
        return f(*args, **kwargs)
    return decorated

def require_watch_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Watch-Token", "")
        if not token:
            return jsonify({"error": "Missing X-Watch-Token"}), 401
        
        watch = get_watch_by_token(token)
        if not watch:
            return jsonify({"error": "Invalid watch token"}), 401
        
        request.watch = watch
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        password = request.headers.get("X-Admin-Password", "")
        if not password:
            return jsonify({"error": "Missing X-Admin-Password"}), 401
        
        stored_hash = config.get("admin", {}).get("password_hash", "")
        if not stored_hash:
            return jsonify({"error": "Admin not configured"}), 401
        
        if not bcrypt.checkpw(password.encode(), stored_hash.encode()):
            return jsonify({"error": "Invalid admin password"}), 401
        
        return f(*args, **kwargs)
    return decorated

# ============================================================
# Helpers
# ============================================================

def get_timestamp():
    return int(time.time())

def cleanup_old_messages(instance_id: str):
    """Auto-cleanup old messages per instance"""
    limits = config.get("limits", {})
    max_days = limits.get("message_retention_days", 7)
    max_msgs = limits.get("max_messages_per_instance", 200)
    
    conn = get_db()
    c = conn.cursor()
    cutoff = get_timestamp() - (max_days * 86400)
    
    # Delete old messages
    c.execute("DELETE FROM messages WHERE instance_id = ? AND timestamp < ?", (instance_id, cutoff))
    
    # Keep only last N messages
    c.execute("""
        DELETE FROM messages WHERE instance_id = ? AND id NOT IN (
            SELECT id FROM messages WHERE instance_id = ? ORDER BY timestamp DESC LIMIT ?
        )
    """, (instance_id, instance_id, max_msgs))
    
    conn.commit()
    conn.close()

def notify_watch_sse(instance_id: str, event_data: dict):
    """Broadcast event to all watches subscribed to this instance"""
    with sse_clients_lock:
        for watch_token, client in list(sse_clients.items()):
            try:
                if client.get("instance_id") == instance_id:
                    client["queue"].put(json.dumps(event_data))
            except:
                pass

def notify_all_watches_of_user(user_id: str, event_data: dict):
    """Broadcast to all watches belonging to a user"""
    with sse_clients_lock:
        for watch_token, client in list(sse_clients.items()):
            try:
                # Check if this watch belongs to the user
                watch = get_watch_by_token(watch_token)
                if watch and watch["user_id"] == user_id:
                    client["queue"].put(json.dumps(event_data))
            except:
                pass

# ============================================================
# Health & Admin
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "pebble-relay", "version": "2.0.0", "time": get_timestamp()}), 200

@app.route("/api/v1/admin/setup", methods=["POST"])
def admin_setup():
    """First-time admin password setup"""
    data = request.get_json() or {}
    password = data.get("password", "")
    
    stored_hash = config.get("admin", {}).get("password_hash", "")
    if stored_hash:
        return jsonify({"error": "Admin already configured"}), 400
    
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    
    config["admin"]["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    # Save config
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config, f)
    
    return jsonify({"ok": True, "message": "Admin password set"}), 200

@app.route("/api/v1/admin/info", methods=["GET"])
@require_admin
def admin_info():
    """Get server info (no instance details for security)"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) as cnt FROM users")
    user_count = c.fetchone()["cnt"]
    
    c.execute("SELECT COUNT(*) as cnt FROM oc_instances")
    instance_count = c.fetchone()["cnt"]
    
    c.execute("SELECT COUNT(*) as cnt FROM watch_devices")
    watch_count = c.fetchone()["cnt"]
    
    conn.close()
    
    return jsonify({
        "user_count": user_count,
        "instance_count": instance_count,
        "watch_count": watch_count,
        "registration_code": config.get("admin", {}).get("registration_code", ""),
        "uptime": get_timestamp()
    }), 200

@app.route("/api/v1/admin/registration-code", methods=["POST"])
@require_admin
def regenerate_registration_code():
    """Regenerate registration code"""
    new_code = secrets.token_hex(8)
    config["admin"]["registration_code"] = new_code
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config, f)
    return jsonify({"registration_code": new_code}), 200

# ============================================================
# User Registration
# ============================================================

@app.route("/api/v1/register", methods=["POST"])
def register_user():
    """Register a new user (requires valid registration code)"""
    data = request.get_json() or {}
    code = data.get("registration_code", "")
    name = data.get("name", "")
    
    if code != config.get("admin", {}).get("registration_code", ""):
        return jsonify({"error": "Invalid registration code"}), 401
    
    user_token = secrets.token_urlsafe(32)
    user_id = str(uuid.uuid4())[:8]
    
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (id, user_token_hash, name, created_at) VALUES (?, ?, ?, ?)",
        (user_id, hash_token(user_token), name, get_timestamp())
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        "ok": True,
        "user_id": user_id,
        "user_token": user_token,
        "message": "Save this token securely - it cannot be recovered"
    }), 201

# ============================================================
# OpenClaw Instance Management
# ============================================================

@app.route("/api/v1/oc/register", methods=["POST"])
@require_user_token
def register_instance():
    """Register a new OpenClaw instance under this user"""
    data = request.get_json() or {}
    name = data.get("name", "OpenClaw")
    
    instance_token = secrets.token_urlsafe(32)
    instance_id = str(uuid.uuid4())[:8]
    
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO oc_instances (id, user_id, name, instance_token_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (instance_id, request.user["id"], name, hash_token(instance_token), get_timestamp())
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        "ok": True,
        "instance_id": instance_id,
        "instance_token": instance_token,
        "message": "Save this token securely"
    }), 201

@app.route("/api/v1/oc/<instance_id>/instances", methods=["GET"])
@require_user_token
def list_instances(instance_id):
    """List all instances for this user"""
    if instance_id != request.user["id"]:
        return jsonify({"error": "Access denied"}), 403
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, created_at FROM oc_instances WHERE user_id = ?", (instance_id,))
    instances = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({"instances": instances}), 200

# ============================================================
# OpenClaw Message/Status Push
# ============================================================

@app.route("/api/v1/oc/message", methods=["POST"])
@require_instance_token
def push_message():
    """Receive message from OpenClaw instance"""
    instance = request.instance
    data = request.get_json() or {}
    
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "content is required"}), 400
    
    msg_type = data.get("type", "message")
    source = data.get("source", "openclaw")
    sender = data.get("sender", "System")
    
    # Save message
    msg_id = str(uuid.uuid4())[:8]
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (id, instance_id, type, content, source, sender, timestamp, read) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (msg_id, instance["id"], msg_type, content[:200], source, sender, get_timestamp())
    )
    conn.commit()
    conn.close()
    
    # Cleanup old messages
    cleanup_old_messages(instance["id"])
    
    # Update status - reset last_message_ago
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE status SET last_message_ago = 0, lastUpdate = ? WHERE instance_id = ?",
              (get_timestamp(), instance["id"]))
    conn.commit()
    conn.close()
    
    # Broadcast to watching watches
    event = {
        "type": "message",
        "instance_id": instance["id"],
        "content": content[:200],
        "source": source,
        "sender": sender,
        "timestamp": get_timestamp(),
        "id": msg_id
    }
    notify_watch_sse(instance["id"], event)
    
    return jsonify({"ok": True, "id": msg_id}), 200

@app.route("/api/v1/oc/status", methods=["POST"])
@require_instance_token
def push_status():
    """Receive status update from OpenClaw instance"""
    instance = request.instance
    data = request.get_json() or {}
    
    ok = data.get("ok", True)
    uptime = data.get("uptime", 0)
    channels = data.get("channels", [])
    memory = data.get("memory", 0)
    cpu = data.get("cpu", 0)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO status 
        (instance_id, ok, uptime, channels, memory, cpu, last_message_ago, lastUpdate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (instance["id"], 1 if ok else 0, uptime, json.dumps(channels), 
           memory, cpu, data.get("last_message_ago", 0), get_timestamp()))
    conn.commit()
    conn.close()
    
    return jsonify({"ok": True}), 200

@app.route("/api/v1/oc/thinking", methods=["POST"])
@require_instance_token
def push_thinking():
    """Receive thinking status update from OpenClaw instance"""
    instance = request.instance
    data = request.get_json() or {}
    
    thinking = data.get("thinking", False)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE status SET thinking = ?, lastUpdate = ? WHERE instance_id = ?",
              (1 if thinking else 0, get_timestamp(), instance["id"]))
    conn.commit()
    conn.close()
    
    # Broadcast to watching watches
    event = {
        "type": "thinking",
        "instance_id": instance["id"],
        "thinking": thinking,
        "timestamp": get_timestamp()
    }
    notify_watch_sse(instance["id"], event)
    
    return jsonify({"ok": True}), 200

# ============================================================
# Watch Device Management
# ============================================================

@app.route("/api/v1/watch/bind", methods=["POST"])
@require_user_token
def bind_watch():
    """Bind a new watch device to this user's account"""
    data = request.get_json() or {}
    name = data.get("name", "Watch")
    
    watch_token = secrets.token_urlsafe(32)
    watch_id = str(uuid.uuid4())[:8]
    
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO watch_devices (id, user_id, name, watch_token_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (watch_id, request.user["id"], name, hash_token(watch_token), get_timestamp())
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        "ok": True,
        "watch_id": watch_id,
        "watch_token": watch_token,
        "message": "Save this token securely"
    }), 201

@app.route("/api/v1/watch/instances", methods=["GET"])
@require_watch_token
def get_watch_instances():
    """Get all OpenClaw instances available to this watch"""
    watch = request.watch
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT oci.id, oci.name, oci.created_at,
               wd.current_instance_id IS NOT NULL AND wd.current_instance_id = oci.id as subscribed
        FROM oc_instances oci
        JOIN watch_devices wd ON wd.user_id = oci.user_id
        WHERE wd.id = ?
    """, (watch["id"],))
    instances = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({"instances": instances}), 200

@app.route("/api/v1/watch/subscribe", methods=["POST"])
@require_watch_token
def subscribe_instance():
    """Switch the watch to subscribe to a different OpenClaw instance"""
    watch = request.watch
    data = request.get_json() or {}
    instance_id = data.get("instance_id", "")
    
    if instance_id:
        # Verify instance belongs to same user
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM oc_instances WHERE id = ? AND user_id = ?",
                  (instance_id, watch["user_id"]))
        if not c.fetchone():
            conn.close()
            return jsonify({"error": "Instance not found or access denied"}), 403
        conn.close()
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE watch_devices SET current_instance_id = ? WHERE id = ?",
              (instance_id, watch["id"]))
    conn.commit()
    conn.close()
    
    # Update SSE client subscription
    with sse_clients_lock:
        if watch["watch_token"] in sse_clients:
            sse_clients[watch["watch_token"]]["instance_id"] = instance_id
    
    return jsonify({"ok": True, "subscribed_instance": instance_id}), 200

@app.route("/api/v1/watch/status", methods=["GET"])
@require_watch_token
def get_watch_status():
    """Get current status for the watch's subscribed instance"""
    watch = request.watch
    
    instance_id = watch.get("current_instance_id")
    if not instance_id:
        return jsonify({"error": "No instance subscribed"}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    # Get instance info
    c.execute("SELECT * FROM oc_instances WHERE id = ?", (instance_id,))
    instance_row = c.fetchone()
    if not instance_row:
        conn.close()
        return jsonify({"error": "Instance not found"}), 404
    
    # Get status
    c.execute("SELECT * FROM status WHERE instance_id = ?", (instance_id,))
    status_row = c.fetchone()
    
    # Get recent messages
    c.execute("""
        SELECT * FROM messages WHERE instance_id = ? 
        ORDER BY timestamp DESC LIMIT 5
    """, (instance_id,))
    messages = [dict(row) for row in c.fetchall()]
    
    conn.close()
    
    status = {
        "instance_id": instance_id,
        "instance_name": instance_row["name"],
        "ok": bool(status_row["ok"]) if status_row else False,
        "thinking": bool(status_row["thinking"]) if status_row else False,
        "uptime": status_row["uptime"] if status_row else 0,
        "channels": json.loads(status_row["channels"]) if status_row and status_row["channels"] else [],
        "memory": status_row["memory"] if status_row else 0,
        "cpu": status_row["cpu"] if status_row else 0,
        "last_message_ago": status_row["last_message_ago"] if status_row else 0,
        "lastUpdate": status_row["lastUpdate"] if status_row else 0,
        "recent_messages": messages
    }
    
    return jsonify(status), 200

@app.route("/api/v1/watch/messages", methods=["GET"])
@require_watch_token
def get_watch_messages():
    """Get recent messages for the watch's subscribed instance"""
    watch = request.watch
    limit = min(request.args.get("limit", default=20, type=int), 50)
    
    instance_id = watch.get("current_instance_id")
    if not instance_id:
        return jsonify({"error": "No instance subscribed"}), 400
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM messages WHERE instance_id = ? 
        ORDER BY timestamp DESC LIMIT ?
    """, (instance_id, limit))
    messages = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({"messages": messages, "count": len(messages)}), 200

@app.route("/api/v1/watch/events")
@require_watch_token
def watch_events():
    """SSE stream for real-time updates to subscribed instance"""
    watch = request.watch
    
    instance_id = watch.get("current_instance_id")
    
    def generate():
        queue = []
        client = {"queue": queue, "instance_id": instance_id, "watch_token": watch["watch_token"]}
        
        with sse_clients_lock:
            sse_clients[watch["watch_token"]] = client
        
        try:
            # Send initial connection event
            yield "data: %s\n\n" % json.dumps({
                "type": "connected",
                "instance_id": instance_id,
                "time": get_timestamp()
            })
            
            # Send current status if subscribed
            if instance_id:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT * FROM status WHERE instance_id = ?", (instance_id,))
                status_row = c.fetchone()
                conn.close()
                
                if status_row:
                    yield "data: %s\n\n" % json.dumps({
                        "type": "status",
                        "instance_id": instance_id,
                        "ok": bool(status_row["ok"]),
                        "thinking": bool(status_row["thinking"]),
                        "uptime": status_row["uptime"],
                        "channels": json.loads(status_row["channels"]) if status_row["channels"] else [],
                        "memory": status_row["memory"],
                        "cpu": status_row["cpu"],
                        "last_message_ago": status_row["last_message_ago"],
                        "timestamp": status_row["lastUpdate"]
                    })
            
            # Keep connection alive, stream events
            while True:
                if queue:
                    while queue:
                        item = queue.pop(0)
                        yield "data: %s\n\n" % item
                else:
                    time.sleep(0.5)
        
        finally:
            with sse_clients_lock:
                if watch["watch_token"] in sse_clients:
                    del sse_clients[watch["watch_token"]]
    
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
# Legacy / Compatibility Endpoints (v1)
# ============================================================

@app.route("/webhook", methods=["POST"])
def legacy_webhook():
    """Legacy single-instance webhook - redirects to instance-based"""
    # For backward compatibility during migration
    return jsonify({"error": "Use /api/v1/oc/message instead"}), 410

@app.route("/status", methods=["GET"])
def legacy_get_status():
    return jsonify({"error": "Use /api/v1/watch/status instead"}), 410

@app.route("/status", methods=["POST"])
def legacy_post_status():
    return jsonify({"error": "Use /api/v1/oc/status instead"}), 410

# ============================================================
# Start
# ============================================================

if __name__ == "__main__":
    init_db()
    print(f"[pebble-relay v2.0.0] Starting on port {PORT}")
    print(f"[pebble-relay] Config: {CONFIG_PATH}")
    print(f"[pebble-relay] Database: {DB_PATH}")
    if not config.get("admin", {}).get("password_hash"):
        setup_hint = '{"password": "..."}'
        print(f"[pebble-relay] First-time setup: POST /api/v1/admin/setup with {setup_hint}")
        print(f"[pebble-relay] Registration code: {config.get('admin', {}).get('registration_code', 'N/A')}")
    app.run(host="0.0.0.0", port=PORT, debug=config.get("server", {}).get("debug", False), threaded=True)
