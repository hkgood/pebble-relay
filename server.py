"""
pebble-relay v2.0-pb
Multi-user relay server for OpenClaw <-> Smartwatch
Uses PocketBase for account management (pebble_users, pebble_reg_codes, pebble_admins collections)
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
import requests
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

# PocketBase configuration
PB_URL = os.environ.get("PB_URL", "https://pb.osglab.com")
PB_ADMIN_EMAIL = os.environ.get("PB_ADMIN_EMAIL", "rocky.hk@gmail.com")
PB_ADMIN_PASSWORD = os.environ.get("PB_ADMIN_PASSWORD", "gz203799")

# In-memory cache for PocketBase admin token
_pb_admin_token = None
_pb_admin_token_exp = 0

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
            "password_hash": "",
            "registration_code": secrets.token_hex(8)
        },
        "limits": {
            "message_retention_days": 7,
            "max_messages_per_instance": 200
        },
        "pocketbase": {
            "url": PB_URL,
            "admin_email": PB_ADMIN_EMAIL,
            "admin_password": PB_ADMIN_PASSWORD
        }
    }

config = load_config()

# In-memory SSE clients: {watch_token: {"queue": [], "instance_id": None}}
sse_clients = {}
sse_clients_lock = threading.Lock()

# ============================================================
# PocketBase API Helpers
# ============================================================

def get_pb_admin_token():
    """Get or refresh PocketBase admin token"""
    global _pb_admin_token, _pb_admin_token_exp
    
    # Check if current token is still valid
    if _pb_admin_token and time.time() < _pb_admin_token_exp - 60:
        return _pb_admin_token
    
    # Refresh token using superuser auth (0.35.x style)
    try:
        resp = requests.post(
            f"{PB_URL}/api/collections/users/auth-with-password",
            json={"identity": PB_ADMIN_EMAIL, "password": PB_ADMIN_PASSWORD},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            _pb_admin_token = data.get("token", "")
            # Token typically expires in 24 hours, refresh 1 hour before
            _pb_admin_token_exp = time.time() + 23 * 3600
            return _pb_admin_token
    except Exception as e:
        print(f"[pb] Failed to get admin token: {e}")
    
    return _pb_admin_token

def pb_api_get(collection, record_id=None, params=None):
    """GET request to PocketBase API"""
    token = get_pb_admin_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    if record_id:
        url = f"{PB_URL}/api/collections/{collection}/records/{record_id}"
    else:
        url = f"{PB_URL}/api/collections/{collection}/records"
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        return resp.status_code, resp.json()
    except Exception as e:
        return 500, {"error": str(e)}

def pb_api_post(collection, data, record_id=None):
    """POST request to PocketBase API"""
    token = get_pb_admin_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    if record_id:
        url = f"{PB_URL}/api/collections/{collection}/records/{record_id}"
        try:
            resp = requests.patch(url, headers=headers, json=data, timeout=10)
            return resp.status_code, resp.json()
        except Exception as e:
            return 500, {"error": str(e)}
    else:
        url = f"{PB_URL}/api/collections/{collection}/records"
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=10)
            return resp.status_code, resp.json()
        except Exception as e:
            return 500, {"error": str(e)}

def pb_api_delete(collection, record_id):
    """DELETE request to PocketBase API"""
    token = get_pb_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    url = f"{PB_URL}/api/collections/{collection}/records/{record_id}"
    try:
        resp = requests.delete(url, headers=headers, timeout=10)
        return resp.status_code, resp.json() if resp.content else {}
    except Exception as e:
        return 500, {"error": str(e)}

# ============================================================
# Database (Local - for relay data only, not users)
# ============================================================

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # oc_instances - OpenClaw instances per user
    c.execute("""
        CREATE TABLE IF NOT EXISTS oc_instances (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            instance_token_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    
    # watch_devices - Watch devices per user
    c.execute("""
        CREATE TABLE IF NOT EXISTS watch_devices (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            watch_token_hash TEXT NOT NULL,
            current_instance_id TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (current_instance_id) REFERENCES oc_instances(id)
        )
    """)
    
    # messages - Messages per instance
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
    
    # status - Status snapshots per instance
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

# ============================================================
# User Management via PocketBase
# ============================================================

def get_user_by_token(user_token: str) -> dict | None:
    """Find user by user_token in pebble_users collection"""
    status, data = pb_api_get("pebble_users", params={"filter": f'user_token="{user_token}"'})
    
    if status == 200 and data.get("items"):
        item = data["items"][0]
        return {
            "id": item["id"],
            "name": item.get("name", ""),
            "email": item.get("email", ""),
            "user_token": item.get("user_token", "")
        }
    return None

def get_user_by_id(user_id: str) -> dict | None:
    """Find user by ID in pebble_users collection"""
    status, data = pb_api_get("pebble_users", record_id=user_id)
    
    if status == 200:
        return {
            "id": data["id"],
            "name": data.get("name", ""),
            "email": data.get("email", ""),
            "user_token": data.get("user_token", "")
        }
    return None

def create_user(name: str, user_token: str) -> dict | None:
    """Create a new user in pebble_users collection"""
    status, data = pb_api_post("pebble_users", {
        "name": name,
        "user_token": user_token
    })
    
    if status in (200, 201):
        return {
            "id": data["id"],
            "name": name,
            "user_token": user_token
        }
    print(f"[pb] create_user failed: {status} {data}")
    return None

def validate_registration_code(code: str) -> bool:
    """Check if registration code exists and is unused"""
    status, data = pb_api_get("pebble_reg_codes", params={"filter": f'code="{code}"'})
    
    if status == 200 and data.get("items"):
        # Filter manually for unused codes
        for item in data["items"]:
            if not item.get("used", True):
                return True
    return False

def mark_reg_code_used(code: str) -> bool:
    """Mark a registration code as used"""
    # Find the record first
    status, data = pb_api_get("pebble_reg_codes", params={"filter": f'code="{code}"'})
    
    if status == 200 and data.get("items"):
        record_id = data["items"][0]["id"]
        status, _ = pb_api_post("pebble_reg_codes", {"used": True}, record_id=record_id)
        return status in (200, 204)
    
    return False

def generate_registration_code() -> str:
    """Generate a new registration code in pebble_reg_codes"""
    code = secrets.token_hex(8)
    status, data = pb_api_post("pebble_reg_codes", {
        "code": code,
        "used": False,
        "created_at": int(time.time())
    })
    
    if status in (200, 201):
        return code
    print(f"[pb] generate_reg_code failed: {status} {data}")
    return None

def get_reg_code_count() -> int:
    """Get total registration code count"""
    status, data = pb_api_get("pebble_reg_codes")
    if status == 200:
        return data.get("totalItems", 0)
    return 0

def get_user_count() -> int:
    """Get total user count"""
    status, data = pb_api_get("pebble_users")
    if status == 200:
        return data.get("totalItems", 0)
    return 0

def get_all_users() -> list:
    """Get all users from pebble_users"""
    status, data = pb_api_get("pebble_users")
    if status == 200:
        return data.get("items", [])
    return []

def delete_user(user_id: str) -> bool:
    """Delete a user"""
    status, _ = pb_api_delete("pebble_users", user_id)
    return status in (200, 204)

# ============================================================
# Admin Management via PocketBase (pebble_admins collection)
# ============================================================

def setup_admin(username: str, password: str) -> bool:
    """Setup admin user in pebble_admins collection"""
    status, data = pb_api_post("pebble_admins", {
        "username": username,
        "password": password,
        "passwordConfirm": password,
        "name": "Admin"
    })
    
    # 400 might mean already exists
    if status in (200, 201, 400):
        return True
    print(f"[pb] setup_admin failed: {status} {data}")
    return False

def verify_admin(username: str, password: str) -> dict | None:
    """Verify admin credentials against pebble_admins"""
    try:
        resp = requests.post(
            f"{PB_URL}/api/collections/pebble_admins/auth-with-password",
            json={"identity": username, "password": password},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "id": data["record"]["id"],
                "username": data["record"]["username"],
                "token": data.get("token", "")
            }
    except Exception as e:
        print(f"[pb] verify_admin error: {e}")
    return None

# ============================================================
# Local instance/watch lookup (still uses local SQLite)
# ============================================================

def get_instance_by_token(instance_token: str) -> dict | None:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM oc_instances")
    for row in c.fetchall():
        if verify_token(instance_token, row['instance_token_hash']):
            conn.close()
            return dict(row)
    conn.close()
    return None

def get_watch_by_token(watch_token: str) -> dict | None:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM watch_devices")
    for row in c.fetchall():
        if verify_token(watch_token, row['watch_token_hash']):
            conn.close()
            return dict(row)
    conn.close()
    return None

# ============================================================
# Auth decorators
# ============================================================

def require_instance_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
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
        # Check header-based admin auth
        password = request.headers.get("X-Admin-Password", "")
        stored_hash = config.get("admin", {}).get("password_hash", "")
        
        if stored_hash and password:
            try:
                if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                    return f(*args, **kwargs)
            except:
                pass
        
        # Check pebble_admins auth
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            # Try to verify via pebble_admins
            try:
                resp = requests.get(
                    f"{PB_URL}/api/collections/pebble_admins/auth-refresh",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10
                )
                if resp.status_code == 200:
                    return f(*args, **kwargs)
            except:
                pass
        
        return jsonify({"error": "Unauthorized"}), 401
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
    
    c.execute("DELETE FROM messages WHERE instance_id = ? AND timestamp < ?", (instance_id, cutoff))
    
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

# ============================================================
# Health & Admin
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True, 
        "service": "pebble-relay", 
        "version": "2.0.0-pb", 
        "pocketbase": PB_URL,
        "time": get_timestamp()
    }), 200

@app.route("/api/v1/admin/setup", methods=["POST"])
def admin_setup():
    """First-time admin setup - creates admin in pebble_admins collection"""
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")
    
    stored_hash = config.get("admin", {}).get("password_hash", "")
    if stored_hash:
        return jsonify({"error": "Admin already configured"}), 400
    
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    
    # Set local config password hash
    config["admin"]["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    # Also create in PocketBase pebble_admins
    if username:
        setup_admin(username, password)
    
    # Generate first registration code
    first_code = generate_registration_code()
    
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config, f)
    
    return jsonify({
        "ok": True, 
        "message": "Admin password set",
        "first_registration_code": first_code
    }), 200

@app.route("/api/v1/admin/info", methods=["GET"])
@require_admin
def admin_info():
    """Get server info"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) as cnt FROM oc_instances")
    instance_count = c.fetchone()["cnt"]
    
    c.execute("SELECT COUNT(*) as cnt FROM watch_devices")
    watch_count = c.fetchone()["cnt"]
    
    conn.close()
    
    user_count = get_user_count()
    
    return jsonify({
        "user_count": user_count,
        "instance_count": instance_count,
        "watch_count": watch_count,
        "pocketbase_url": PB_URL,
        "uptime": get_timestamp()
    }), 200

@app.route("/api/v1/admin/registration-code", methods=["POST"])
@require_admin
def regenerate_registration_code():
    """Generate a new registration code"""
    new_code = generate_registration_code()
    if new_code:
        config["admin"]["registration_code"] = new_code
        with open(CONFIG_PATH, 'w') as f:
            yaml.dump(config, f)
        return jsonify({"registration_code": new_code}), 200
    return jsonify({"error": "Failed to generate code"}), 500

@app.route("/api/v1/admin/users", methods=["GET"])
@require_admin
def list_users():
    """List all users with their instances"""
    users = get_all_users()
    
    # Get instances per user from local SQLite
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, user_id FROM oc_instances")
    all_instances = c.fetchall()
    conn.close()
    
    user_instances = {}
    for inst in all_instances:
        uid = inst["user_id"]
        if uid not in user_instances:
            user_instances[uid] = []
        user_instances[uid].append({"id": inst["id"], "name": inst["name"]})
    
    result = []
    for u in users:
        uid = u["id"]
        created = u.get("created", "")
        if created and isinstance(created, str):
            # PocketBase returns created ISO string
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                created = dt.strftime("%Y-%m-%d %H:%M")
            except:
                pass
        result.append({
            "id": uid,
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "created_at": created,
            "instances": user_instances.get(uid, [])
        })
    
    return jsonify({
        "users": result,
        "total": len(result)
    }), 200


@app.route("/api/v1/admin/users", methods=["POST"])
@require_admin
def create_user_admin():
    """Create a new user directly (admin only, no registration code needed)"""
    data = request.get_json() or {}
    name = data.get("name", "")
    
    user_token = secrets.token_urlsafe(32)
    user = create_user(name, user_token)
    
    if not user:
        return jsonify({"error": "Failed to create user"}), 500
    
    return jsonify({
        "ok": True,
        "user_id": user["id"],
        "user_token": user_token,
        "name": name,
        "message": "Save this token securely - it cannot be recovered"
    }), 201

@app.route("/api/v1/admin/users/<user_id>", methods=["DELETE"])
@require_admin
def delete_user_api(user_id):
    """Delete a user"""
    if delete_user(user_id):
        return jsonify({"ok": True}), 200
    return jsonify({"error": "Failed to delete user"}), 500

# ============================================================
# User Registration
# ============================================================

@app.route("/api/v1/register", methods=["POST"])
def register_user():
    """Register a new user (requires valid registration code from PocketBase)"""
    data = request.get_json() or {}
    code = data.get("registration_code", "")
    name = data.get("name", "")
    
    # Validate registration code against PocketBase
    if not validate_registration_code(code):
        return jsonify({"error": "Invalid or used registration code"}), 401
    
    user_token = secrets.token_urlsafe(32)
    
    # Create user in PocketBase
    user = create_user(name, user_token)
    if not user:
        return jsonify({"error": "Failed to create user"}), 500
    
    # Mark registration code as used
    mark_reg_code_used(code)
    
    return jsonify({
        "ok": True,
        "user_id": user["id"],
        "user_token": user_token,
        "message": "Save this token securely - it cannot be recovered"
    }), 201

# ============================================================
# OpenClaw Instance Management (local SQLite)
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
    
    msg_id = str(uuid.uuid4())[:8]
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (id, instance_id, type, content, source, sender, timestamp, read) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (msg_id, instance["id"], msg_type, content[:200], source, sender, get_timestamp())
    )
    conn.commit()
    conn.close()
    
    cleanup_old_messages(instance["id"])
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE status SET last_message_ago = 0, lastUpdate = ? WHERE instance_id = ?",
              (get_timestamp(), instance["id"]))
    conn.commit()
    conn.close()
    
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
    
    c.execute("SELECT * FROM oc_instances WHERE id = ?", (instance_id,))
    instance_row = c.fetchone()
    if not instance_row:
        conn.close()
        return jsonify({"error": "Instance not found"}), 404
    
    c.execute("SELECT * FROM status WHERE instance_id = ?", (instance_id,))
    status_row = c.fetchone()
    
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
            yield "data: %s\n\n" % json.dumps({
                "type": "connected",
                "instance_id": instance_id,
                "time": get_timestamp()
            })
            
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
# PocketBase Proxy (for UI pages)
# ============================================================

@app.route("/api/collections/pebble_admins/auth-with-password", methods=["POST"])
def pb_admin_auth():
    """Proxy to PocketBase admin auth"""
    data = request.get_json() or {}
    try:
        resp = requests.post(
            f"{PB_URL}/api/collections/pebble_admins/auth-with-password",
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================
# Legacy / Compatibility
# ============================================================

@app.route("/webhook", methods=["POST"])
def legacy_webhook():
    return jsonify({"error": "Use /api/v1/oc/message instead"}), 410

@app.route("/status", methods=["GET"])
def legacy_get_status():
    return jsonify({"error": "Use /api/v1/watch/status instead"}), 410

@app.route("/status", methods=["POST"])
def legacy_post_status():
    return jsonify({"error": "Use /api/v1/oc/status instead"}), 410

# ============================================================
# Static UI Pages
# ============================================================

@app.route("/register")
def register_page():
    return send_from_directory("/app", "register.html")

@app.route("/admin")
def admin_page():
    return send_from_directory("/app", "admin.html")

@app.route("/watch-setup")
def watch_setup_page():
    return send_from_directory("/app", "watch-setup.html")

# ============================================================
# Start
# ============================================================

if __name__ == "__main__":
    init_db()
    print(f"[pebble-relay v2.0.0-pb] Starting on port {PORT}")
    print(f"[pebble-relay] Config: {CONFIG_PATH}")
    print(f"[pebble-relay] Database: {DB_PATH}")
    print(f"[pebble-relay] PocketBase: {PB_URL}")
    if not config.get("admin", {}).get("password_hash"):
        print(f"[pebble-relay] First-time setup: POST /api/v1/admin/setup with {{\"username\":\"admin\",\"password\":\"...\"}}")
        print(f"[pebble-relay] Registration code: {config.get('admin', {}).get('registration_code', 'N/A')}")
    app.run(host="0.0.0.0", port=PORT, debug=config.get("server", {}).get("debug", False), threaded=True)
