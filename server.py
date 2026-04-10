"""
pebble-relay v1.0.3
Multi-user relay server for OpenClaw <-> Smartwatch
Uses PocketBase for all data storage: relay_users, oc_instances, watch_devices, relay_status, relay_messages
"""
import os, secrets, time, sqlite3, yaml, re
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, Response
import bcrypt, requests

app = Flask(__name__)

# ============================================================
# Configuration
# ============================================================
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/data/config.yaml")
PB_URL = os.environ.get("PB_URL", "https://pb.osglab.com")
PB_SUPERUSER_EMAIL = os.environ.get("PB_SUPERUSER_EMAIL", "rocky.hk@gmail.com")
PB_SUPERUSER_PASSWORD = os.environ.get("PB_SUPERUSER_PASSWORD", "gz203799")

config = {}
_pb_admin_token = None
_pb_admin_token_exp = 0

# ============================================================
# PocketBase Helpers
# ============================================================
def _get_admin_token():
    """Get or refresh PocketBase superuser token"""
    global _pb_admin_token, _pb_admin_token_exp
    if _pb_admin_token and time.time() < _pb_admin_token_exp - 60:
        return _pb_admin_token
    try:
        resp = requests.post(
            f"{PB_URL}/api/collections/_superusers/auth-with-password",
            json={"identity": PB_SUPERUSER_EMAIL, "password": PB_SUPERUSER_PASSWORD},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            _pb_admin_token = data.get("token", "")
            _pb_admin_token_exp = time.time() + 23 * 3600
            return _pb_admin_token
        else:
            print(f"[pb] auth failed: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        print(f"[pb] auth error: {e}")
    return None

def pb_headers(token=None):
    """Return headers dict for PocketBase API calls"""
    t = token or _get_admin_token()
    return {
        "Authorization": f"Bearer {t}",
        "Content-Type": "application/json"
    }

def pb_get(collection, record_id=None, params=None):
    """GET from PocketBase collection"""
    token = _get_admin_token()
    if not token:
        return None, None
    url = f"{PB_URL}/api/collections/{collection}/records"
    if record_id:
        url += f"/{record_id}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{qs}"
    try:
        resp = requests.get(url, headers=pb_headers(token), timeout=10)
        return resp.status_code, resp.json()
    except Exception as e:
        return None, {"error": str(e)}

def pb_post(collection, data, record_id=None):
    """POST or PATCH to PocketBase collection"""
    token = _get_admin_token()
    if not token:
        return None, {"error": "no token"}
    url = f"{PB_URL}/api/collections/{collection}/records"
    if record_id:
        url += f"/{record_id}"
    try:
        resp = requests.request(
            "PATCH" if record_id else "POST",
            url, headers=pb_headers(token), json=data, timeout=10
        )
        return resp.status_code, resp.json()
    except Exception as e:
        return None, {"error": str(e)}

def pb_delete(collection, record_id):
    """DELETE from PocketBase collection"""
    token = _get_admin_token()
    if not token:
        return None, {"error": "no token"}
    try:
        resp = requests.delete(
            f"{PB_URL}/api/collections/{collection}/records/{record_id}",
            headers=pb_headers(token), timeout=10
        )
        return resp.status_code, resp.json() if resp.content else {}
    except Exception as e:
        return None, {"error": str(e)}

def pb_upsert(collection, filter_query, data):
    """Upsert: find by filter, update if exists, create if not"""
    filter_enc = requests.utils.quote(filter_query)
    status, result = pb_get(collection, params={"filter": filter_enc, "sort": "-lastUpdate", "perPage": 1})
    if status == 200 and result.get("items"):
        record_id = result["items"][0]["id"]
        print(f"[pb_upsert] {collection}: found record {record_id}, updating")
        return pb_post(collection, data, record_id)
    else:
        print(f"[pb_upsert] {collection}: no existing record found (status={status}), creating new")
        return pb_post(collection, data)

def hash_token(token: str) -> str:
    return bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()

def verify_token(token: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(token.encode(), hashed.encode())
    except:
        return False

# ============================================================
# Load config
# ============================================================
def load_config():
    global config
    try:
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
    except:
        config = {}
    if "admin" not in config:
        config["admin"] = {}
    if "relay_tokens" not in config:
        config["relay_tokens"] = {}  # map: relay_token_hash -> user_id (for fast lookup)

def save_config():
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f)

load_config()

# ============================================================
# Admin Auth
# ============================================================
def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        stored = config.get("admin", {}).get("password_hash", "")
        if stored and token:
            try:
                if bcrypt.checkpw(token.encode(), stored.encode()):
                    return f(*args, **kwargs)
            except:
                pass
        return jsonify({"error": "Unauthorized"}), 401
    return decorated

# ============================================================
# User Token Auth (relay_token in relay_users collection)
# ============================================================
def get_user_by_relay_token(relay_token: str) -> dict | None:
    """Find user by relay_token in relay_users, using local cache for speed"""
    # Fast path: check local cache
    token_hash = bcrypt.hashpw(relay_token.encode(), bcrypt.gensalt()).decode()[:60]
    # Try to find in local config cache
    for th, uid in config.get("relay_tokens", {}).items():
        try:
            if bcrypt.checkpw(relay_token.encode(), th.encode()):
                # Found in cache, get full record
                status, data = pb_get("relay_users", params={"filter": f'id="{uid}"'})
                if status == 200 and data.get("items"):
                    return data["items"][0]
        except:
            pass
    
    # Slow path: search PocketBase
    filter_enc = requests.utils.quote(f'relay_token="{relay_token}"')
    status, data = pb_get("relay_users", params={"filter": filter_enc})
    if status == 200 and data.get("items"):
        user = data["items"][0]
        # Cache it
        if "relay_tokens" not in config:
            config["relay_tokens"] = {}
        try:
            hashed = bcrypt.hashpw(relay_token.encode(), bcrypt.gensalt()).decode()
            config["relay_tokens"][hashed] = user["id"]
            save_config()
        except:
            pass
        return user
    return None

# ============================================================
# Config Init
# ============================================================
REL_DEFAULT_PASSWORD = os.environ.get("RELAY_ADMIN_PASSWORD", "pebblereply")

@app.route("/api/v1/admin/setup", methods=["POST"])
def admin_setup():
    """Set admin password (one-time)"""
    data = request.get_json() or {}
    password = data.get("password", "")
    # If admin not configured and REL_DEFAULT_PASSWORD env is set, auto-use it
    if not config.get("admin", {}).get("password_hash"):
        auto_password = REL_DEFAULT_PASSWORD
        config["admin"]["password_hash"] = bcrypt.hashpw(auto_password.encode(), bcrypt.gensalt()).decode()
        save_config()
        print(f"[pebble-relay] Admin auto-configured with default password: {auto_password}")
        return jsonify({"ok": True, "message": f"Admin password auto-set to '{auto_password}'"}), 200
    if not password or len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if config.get("admin", {}).get("password_hash"):
        return jsonify({"error": "Admin already configured"}), 400
    config["admin"]["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    save_config()
    return jsonify({"ok": True, "message": "Admin password set"}), 200

# ============================================================
# Health
# ============================================================
@app.route("/health")
def health():
    return jsonify({"ok": True, "version": "2.1", "timestamp": int(time.time())})

# ============================================================
# Admin API
# ============================================================
@app.route("/api/v1/admin/info")
@require_admin
def admin_info():
    """Get server stats"""
    # Count users
    _, users = pb_get("relay_users")
    user_count = len(users.get("items", [])) if users else 0
    _, instances = pb_get("oc_instances")
    instance_count = len(instances.get("items", [])) if instances else 0
    _, watches = pb_get("watch_devices")
    watch_count = len(watches.get("items", [])) if watches else 0
    return jsonify({
        "user_count": user_count,
        "instance_count": instance_count,
        "watch_count": watch_count,
        "pocketbase_url": PB_URL
    }), 200

@app.route("/api/v1/admin/check")
@require_admin
def admin_check():
    token = _get_admin_token()
    return jsonify({"ok": bool(token), "pb_connected": bool(token)}), 200

@app.route("/api/v1/admin/users", methods=["GET"])
@require_admin
def list_users():
    """List all users with their instances and watches"""
    _, users = pb_get("relay_users")
    items = users.get("items", []) if users else []
    _, instances = pb_get("oc_instances")
    _, watches = pb_get("watch_devices")
    instance_map = {}
    watch_map = {}
    for inst in (instances.get("items", []) if instances else []):
        uid = inst.get("user_id", "")
        if uid not in instance_map:
            instance_map[uid] = []
        instance_map[uid].append({"id": inst.get("id"), "name": inst.get("name", "")})
    for w in (watches.get("items", []) if watches else []):
        uid = w.get("user_id", "")
        if uid not in watch_map:
            watch_map[uid] = []
        watch_map[uid].append({"id": w.get("id"), "name": w.get("name", "")})
    result = [{
        "id": u["id"],
        "name": u.get("name", ""),
        "created_at": u.get("created", ""),
        "user_token": u.get("relay_token", ""),
        "instances": instance_map.get(u["id"], []),
        "watches": watch_map.get(u["id"], [])
    } for u in items]
    return jsonify({"users": result, "total": len(result)}), 200

@app.route("/api/v1/register", methods=["POST"])
def register():
    """Public user registration - creates relay_token for user in PocketBase relay_users"""
    data = request.get_json() or {}
    name = data.get("name", "Unnamed User")
    email = data.get("email", "")
    password = data.get("password", "")
    
    # Check if registration code is required
    reg_code = data.get("registration_code", "")
    required_code = config.get("registration", {}).get("code", "")
    if required_code and reg_code != required_code:
        return jsonify({"error": "Invalid registration code"}), 403
    
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    
    # Check if email already exists
    _, existing = pb_get("relay_users", params={"filter": f'email="{email}"'})
    if existing and existing.get("items"):
        return jsonify({"error": "Email already registered"}), 409
    
    # Generate relay_token
    relay_token = secrets.token_urlsafe(32)
    
    # Use direct PocketBase auth collection API for user creation
    try:
        resp = requests.post(
            f"{PB_URL}/api/collections/relay_users/records",
            json={
                "email": email,
                "password": password,
                "passwordConfirm": password,
                "name": name,
                "relay_token": relay_token
            },
            timeout=10
        )
        if resp.status_code not in (200, 201):
            err = resp.json()
            return jsonify({"error": err.get("message", "Failed to create user")}), resp.status_code
        result = resp.json()
        return jsonify({
            "ok": True,
            "user_id": result.get("id"),
            "user_token": relay_token
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/v1/user/token", methods=["GET"])
@app.route("/api/v1/user/token", methods=["POST"])
def user_token():
    """Get or regenerate user's relay_token. Requires email in body for lookup."""
    data = request.get_json() or {}
    email = data.get("email", "")
    regenerate = data.get("regenerate", False)
    
    if not email:
        return jsonify({"error": "Email required"}), 400
    
    # Find user by email
    _, result = pb_get("relay_users", params={"filter": f'email="{email}"'})
    items = result.get("items", []) if result else []
    if not items:
        return jsonify({"error": "User not found"}), 404
    
    user = items[0]
    user_id = user.get("id")
    
    if regenerate:
        new_token = secrets.token_urlsafe(32)
        _, updated = pb_post("relay_users", {"relay_token": new_token}, record_id=user_id)
        if updated and updated.get("id"):
            return jsonify({"ok": True, "user_token": new_token})
        return jsonify({"error": "Failed to update token"}), 500
    
    # Return existing token
    return jsonify({
        "ok": True,
        "user_id": user_id,
        "user_token": user.get("relay_token", "")
    })

@app.route("/api/v1/admin/users", methods=["POST"])
@require_admin
def create_user():
    """Create a new user and return relay_token"""
    data = request.get_json() or {}
    name = data.get("name", "Unnamed User")
    relay_token = secrets.token_urlsafe(32)
    status, result = pb_post("relay_users", {
        "name": name,
        "relay_token": relay_token
    })
    if status not in (200, 201):
        return jsonify({"error": result.get("message", "Failed to create user")}), 500
    return jsonify({
        "ok": True,
        "user_id": result.get("id"),
        "user_token": relay_token
    }), 201

@app.route("/api/v1/admin/users/<user_id>", methods=["DELETE"])
@require_admin
def delete_user(user_id):
    status, _ = pb_delete("relay_users", user_id)
    if status not in (200, 204):
        return jsonify({"error": "Delete failed"}), 500
    # Also delete user's instances and watches
    _, instances = pb_get("oc_instances", params={"filter": f'user_id="{user_id}"'})
    for inst in (instances.get("items", []) if instances else []):
        pb_delete("oc_instances", inst["id"])
    _, watches = pb_get("watch_devices", params={"filter": f'user_id="{user_id}"'})
    for w in (watches.get("items", []) if watches else []):
        pb_delete("watch_devices", w["id"])
    return jsonify({"ok": True}), 200

@app.route("/api/v1/admin/users/<user_id>/regenerate-token", methods=["POST"])
@require_admin
def regenerate_user_token(user_id):
    """Regenerate a user's relay_token"""
    new_token = secrets.token_urlsafe(32)
    status, result = pb_post("relay_users", {"relay_token": new_token}, record_id=user_id)
    if status not in (200, 201):
        return jsonify({"error": result.get("message", "Failed to update token")}), 500
    return jsonify({"ok": True, "user_token": new_token})

# ============================================================
# OpenClaw Instance API
# ============================================================
@app.route("/api/v1/oc/register", methods=["POST"])
def oc_register():
    """Register a new OpenClaw instance for a user"""
    relay_token = request.headers.get("X-User-Token", "")
    if not relay_token:
        return jsonify({"error": "Missing X-User-Token"}), 401
    user = get_user_by_relay_token(relay_token)
    if not user:
        return jsonify({"error": "Invalid relay_token"}), 401
    data = request.get_json() or {}
    name = data.get("name", "OpenClaw")
    instance_token = secrets.token_urlsafe(32)
    instance_token_hash = hash_token(instance_token)
    status, result = pb_post("oc_instances", {
        "user_id": user["id"],
        "name": name,
        "instance_token": instance_token_hash
    })
    if status not in (200, 201):
        return jsonify({"error": result.get("message", "Failed to register")}), 500
    return jsonify({
        "ok": True,
        "instance_id": result.get("id"),
        "instance_token": instance_token
    }), 201

def verify_instance_token(instance_token: str, stored_hash: str) -> bool:
    return verify_token(instance_token, stored_hash)

def get_instance_by_token(instance_token: str) -> dict | None:
    """Find instance by token hash"""
    _, instances = pb_get("oc_instances", params={"perPage": 500})
    if not instances:
        return None
    for inst in instances.get("items", []):
        if verify_instance_token(instance_token, inst.get("instance_token", "")):
            return inst
    return None

@app.route("/api/v1/oc/status", methods=["POST"])
def oc_status():
    """Push OpenClaw status (upsert - update existing or create)"""
    try:
        instance_token = request.headers.get("X-Instance-Token", "")
        if not instance_token:
            return jsonify({"error": "Missing X-Instance-Token"}), 401
        instance = get_instance_by_token(instance_token)
        if not instance:
            return jsonify({"error": "Invalid instance token"}), 401
        data = request.get_json() or {}
        channels = data.get("channels", [])
        if isinstance(channels, list):
            channels = ",".join(channels)
        lastUpdate = int(time.time())
        online_channels = data.get("onlineChannels", [])
        if isinstance(online_channels, list):
            online_channels = json.dumps(online_channels)
        elif not online_channels:
            online_channels = "[]"
        # Upsert relay_status by instance_id
        filter_q = f'instance_id="{instance["id"]}"'
        status, result = pb_upsert("relay_status", filter_q, {
            "instance_id": instance["id"],
            "ok": bool(data.get("ok", False)),
            "uptime": int(data.get("uptime", 0)),
            "channels": str(channels),
            "memory": float(data.get("memory", 0)),
            "cpu": float(data.get("cpu", 0)),
            "last_message_ago": int(data.get("last_message_ago", 0)),
            "lastUpdate": lastUpdate,
            "version": str(data.get("version", "")),
            "currentModel": str(data.get("currentModel", "")),
            "currentAgent": str(data.get("currentAgent", "")),
            "sessionCount": int(data.get("sessionCount", 0)),
            "channelCount": int(data.get("channelCount", 0)),
            "nodeCount": int(data.get("nodeCount", 0)),
            "onlineChannels": online_channels,
            "totalTokenUsage": int(data.get("totalTokenUsage", 0))
        })
        if status not in (200, 201):
            print(f"[oc_status] pb_upsert relay_status FAILED: status={status} result={result}")
            return jsonify({"error": "Failed to update status", "detail": str(result)[:300]}), 500
        return jsonify({"ok": True}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal error", "detail": str(e)[:200]}), 500

@app.route("/api/v1/oc/status/<instance_id>", methods=["GET"])
def oc_status_get(instance_id):
    """Get latest status for an instance (used by App)"""
    # Find instance by instance_id (not PocketBase id)
    _, instances = pb_get("oc_instances", params={"perPage": 500})
    if not instances:
        return jsonify({"error": "Instance not found"}), 404
    instance = None
    for inst in instances.get("items", []):
        if inst.get("id") == instance_id:
            instance = inst
            break
    if not instance:
        return jsonify({"error": "Instance not found"}), 404
    # Get latest status from relay_status
    filter_enc = requests.utils.quote(f'instance_id="{instance_id}"')
    _, status_data = pb_get("relay_status", params={"filter": filter_enc, "sort": "-lastUpdate", "perPage": 1})
    items = status_data.get("items", []) if status_data else []
    if not items:
        return jsonify({"ok": False, "error": "No status data"}), 200
    st = items[0]
    channels = st.get("channels", "")
    if isinstance(channels, str):
        channels = [c for c in channels.split(",") if c]
    return jsonify({
        "ok": bool(st.get("ok")),
        "name": instance.get("name", ""),
        "uptime": st.get("uptime", 0),
        "cpu": st.get("cpu", 0),
        "memory": st.get("memory", 0),
        "channels": channels,
        "lastUpdate": st.get("lastUpdate", 0),
        "version": st.get("version", ""),
        "currentModel": st.get("currentModel", ""),
        "currentAgent": st.get("currentAgent", ""),
        "sessionCount": st.get("sessionCount", 0),
        "channelCount": st.get("channelCount", 0),
        "nodeCount": st.get("nodeCount", 0),
        "onlineChannels": st.get("onlineChannels", []),
        "totalTokenUsage": st.get("totalTokenUsage", 0),
    }), 200

@app.route("/api/v1/oc/instances", methods=["GET"])
def oc_instances():
    """List all OpenClaw instances for the authenticated user (auto-discovery for App)"""
    user_token = request.headers.get("X-User-Token", "")
    if not user_token:
        return jsonify({"error": "Missing X-User-Token"}), 401
    user = get_user_by_relay_token(user_token)
    if not user:
        return jsonify({"error": "Invalid relay_token"}), 401

    # Get all instances for this user
    filter_enc = requests.utils.quote(f'user_id="{user["id"]}"')
    _, instances_data = pb_get("oc_instances", params={"filter": filter_enc})
    instance_items = instances_data.get("items", []) if instances_data else []

    result = []
    for inst in instance_items:
        inst_id = inst.get("id")
        # Get latest status for this instance
        status_filter = requests.utils.quote(f'instance_id="{inst_id}"')
        _, status_data = pb_get("relay_status", params={"filter": status_filter, "sort": "-lastUpdate", "perPage": 1})
        status_items = status_data.get("items", []) if status_data else []
        st = status_items[0] if status_items else {}
        channels = st.get("channels", "")
        if isinstance(channels, str):
            channels = [c for c in channels.split(",") if c]
        result.append({
            "id": inst_id,
            "name": inst.get("name", ""),
            "ok": bool(st.get("ok")),
            "uptime": st.get("uptime", 0),
            "cpu": st.get("cpu", 0),
            "memory": st.get("memory", 0),
            "channels": channels,
            "lastUpdate": st.get("lastUpdate", 0),
            "version": st.get("version", ""),
            "currentModel": st.get("currentModel", ""),
            "currentAgent": st.get("currentAgent", ""),
            "sessionCount": st.get("sessionCount", 0),
            "channelCount": st.get("channelCount", 0),
            "nodeCount": st.get("nodeCount", 0),
            "onlineChannels": st.get("onlineChannels", []),
            "totalTokenUsage": st.get("totalTokenUsage", 0),
            "thinking": bool(st.get("thinking")),
            "lastMessageAgo": st.get("last_message_ago", 0),
        })

    return jsonify({"instances": result}), 200

@app.route("/api/v1/oc/thinking", methods=["POST"])
def oc_thinking():
    """Push thinking status"""
    instance_token = request.headers.get("X-Instance-Token", "")
    if not instance_token:
        return jsonify({"error": "Missing X-Instance-Token"}), 401
    instance = get_instance_by_token(instance_token)
    if not instance:
        return jsonify({"error": "Invalid instance token"}), 401
    data = request.get_json() or {}
    filter_q = f'instance_id="{instance["id"]}"'
    status, result = pb_upsert("relay_status", filter_q, {
        "instance_id": instance["id"],
        "thinking": 1 if data.get("thinking") else 0
    })
    if status not in (200, 201):
        return jsonify({"error": "Failed to update thinking"}), 500
    return jsonify({"ok": True}), 200

@app.route("/api/v1/oc/message", methods=["POST"])
def oc_message():
    """Push a message from OpenClaw"""
    instance_token = request.headers.get("X-Instance-Token", "")
    if not instance_token:
        return jsonify({"error": "Missing X-Instance-Token"}), 401
    instance = get_instance_by_token(instance_token)
    if not instance:
        return jsonify({"error": "Invalid instance token"}), 401
    data = request.get_json() or {}
    content = (data.get("content", "") or "")[:200]
    msg_id = secrets.token_urlsafe(16)
    status, result = pb_post("relay_messages", {
        "instance_id": instance["id"],
        "type": data.get("type", "message"),
        "content": content,
        "source": data.get("source", ""),
        "sender": data.get("sender", ""),
        "timestamp": int(time.time()),
        "read": 0
    })
    if status not in (200, 201):
        return jsonify({"error": "Failed to save message"}), 500
    return jsonify({"ok": True, "id": result.get("id", msg_id)}), 200

# ============================================================
# Watch Device API
# ============================================================
@app.route("/api/v1/watch/bind", methods=["POST"])
def watch_bind():
    """Bind a new watch device to a user"""
    relay_token = request.headers.get("X-User-Token", "")
    if not relay_token:
        return jsonify({"error": "Missing X-User-Token"}), 401
    user = get_user_by_relay_token(relay_token)
    if not user:
        return jsonify({"error": "Invalid relay_token"}), 401
    data = request.get_json() or {}
    name = data.get("name", "Watch")
    watch_token = secrets.token_urlsafe(32)
    watch_token_hash = hash_token(watch_token)
    status, result = pb_post("watch_devices", {
        "user_id": user["id"],
        "name": name,
        "watch_token": watch_token_hash,
        "current_instance_id": ""
    })
    if status not in (200, 201):
        return jsonify({"error": result.get("message", "Failed to bind watch")}), 500
    return jsonify({
        "ok": True,
        "watch_id": result.get("id"),
        "watch_token": watch_token
    }), 201

def verify_watch_token(watch_token: str, stored_hash: str) -> bool:
    return verify_token(watch_token, stored_hash)

def get_watch_by_token(watch_token: str) -> dict | None:
    _, watches = pb_get("watch_devices", params={"perPage": 500})
    if not watches:
        return None
    for w in watches.get("items", []):
        if verify_watch_token(watch_token, w.get("watch_token", "")):
            return w
    return None

@app.route("/api/v1/watch/instances", methods=["GET"])
def watch_instances():
    """Get all instances for the watch's user"""
    watch_token = request.headers.get("X-Watch-Token", "")
    if not watch_token:
        return jsonify({"error": "Missing X-Watch-Token"}), 401
    watch = get_watch_by_token(watch_token)
    if not watch:
        return jsonify({"error": "Invalid watch token"}), 401
    _, instances = pb_get("oc_instances", params={
        "filter": f'user_id="{watch["user_id"]}"'
    })
    items = instances.get("items", []) if instances else []
    current = watch.get("current_instance_id", "")
    result = [{
        "id": inst.get("id"),
        "name": inst.get("name", "OpenClaw"),
        "subscribed": inst.get("id") == current
    } for inst in items]
    return jsonify({"instances": result}), 200

@app.route("/api/v1/watch/subscribe", methods=["POST"])
def watch_subscribe():
    """Switch subscribed instance"""
    watch_token = request.headers.get("X-Watch-Token", "")
    if not watch_token:
        return jsonify({"error": "Missing X-Watch-Token"}), 401
    watch = get_watch_by_token(watch_token)
    if not watch:
        return jsonify({"error": "Invalid watch token"}), 401
    data = request.get_json() or {}
    instance_id = data.get("instance_id", "")
    status, _ = pb_post("watch_devices", {"current_instance_id": instance_id}, watch["id"])
    if status not in (200, 201):
        return jsonify({"error": "Failed to subscribe"}), 500
    return jsonify({"ok": True}), 200

@app.route("/api/v1/watch/status", methods=["GET"])
def watch_status():
    """Get current status for watch's subscribed instance"""
    watch_token = request.headers.get("X-Watch-Token", "")
    if not watch_token:
        return jsonify({"error": "Missing X-Watch-Token"}), 401
    watch = get_watch_by_token(watch_token)
    if not watch:
        return jsonify({"error": "Invalid watch token"}), 401
    instance_id = watch.get("current_instance_id", "")
    if not instance_id:
        return jsonify({"ok": False, "error": "No instance subscribed"}), 200
    # Get instance info
    _, inst_data = pb_get("oc_instances", instance_id)
    if not inst_data or not inst_data.get("id"):
        return jsonify({"ok": False, "error": "Instance not found"}), 200
    # Get status
    filter_enc = requests.utils.quote(f'instance_id="{instance_id}"')
    _, status_data = pb_get("relay_status", params={"filter": filter_enc})
    status_items = status_data.get("items", []) if status_data else []
    # Get recent messages
    filter_enc2 = requests.utils.quote(f'instance_id="{instance_id}"')
    _, msg_data = pb_get("relay_messages", params={
        "filter": filter_enc2,
        "sort": "-timestamp",
        "perPage": 10
    })
    messages = [{
        "id": m.get("id"),
        "type": m.get("type"),
        "content": m.get("content"),
        "source": m.get("source"),
        "sender": m.get("sender"),
        "timestamp": m.get("timestamp")
    } for m in (msg_data.get("items", []) if msg_data else [])]
    st = status_items[0] if status_items else {}
    channels = st.get("channels", "")
    if isinstance(channels, str):
        channels = [c for c in channels.split(",") if c]
    return jsonify({
        "ok": bool(st.get("ok")),
        "thinking": bool(st.get("thinking")),
        "uptime": st.get("uptime", 0),
        "channels": channels,
        "memory": st.get("memory", 0),
        "cpu": st.get("cpu", 0),
        "last_message_ago": st.get("last_message_ago", 0),
        "recent_messages": messages,
        "instance_name": inst_data.get("name", "OpenClaw")
    }), 200

@app.route("/api/v1/watch/messages", methods=["GET"])
def watch_messages():
    """Get message history for watch's subscribed instance"""
    watch_token = request.headers.get("X-Watch-Token", "")
    if not watch_token:
        return jsonify({"error": "Missing X-Watch-Token"}), 401
    watch = get_watch_by_token(watch_token)
    if not watch:
        return jsonify({"error": "Invalid watch token"}), 401
    instance_id = watch.get("current_instance_id", "")
    if not instance_id:
        return jsonify({"messages": [], "count": 0}), 200
    limit = int(request.args.get("limit", 20))
    filter_enc = requests.utils.quote(f'instance_id="{instance_id}"')
    _, msg_data = pb_get("relay_messages", params={
        "filter": filter_enc,
        "sort": "-timestamp",
        "perPage": limit
    })
    messages = [{
        "id": m.get("id"),
        "type": m.get("type"),
        "content": m.get("content"),
        "source": m.get("source"),
        "sender": m.get("sender"),
        "timestamp": m.get("timestamp")
    } for m in (msg_data.get("items", []) if msg_data else [])]
    return jsonify({"messages": messages, "count": len(messages)}), 200

@app.route("/api/v1/watch/events", methods=["GET"])
def watch_events():
    """SSE stream for watch real-time events"""
    watch_token = request.headers.get("X-Watch-Token", "")
    if not watch_token:
        return Response("data: {\"error\":\"Missing X-Watch-Token\"}\n\n", mimetype="text/event-stream")
    watch = get_watch_by_token(watch_token)
    if not watch:
        return Response("data: {\"error\":\"Invalid watch token\"}\n\n", mimetype="text/event-stream")
    def generate():
        last_mtime = 0
        last_status = {}
        while True:
            instance_id = watch.get("current_instance_id", "")
            if instance_id:
                # Check for new messages
                filter_enc = requests.utils.quote(f'instance_id="{instance_id}"&timestamp>{last_mtime}')
                _, msg_data = pb_get("relay_messages", params={
                    "filter": filter_enc,
                    "sort": "-timestamp",
                    "perPage": 5
                })
                for m in (msg_data.get("items", []) if msg_data else []):
                    ts = m.get("timestamp", 0)
                    if ts > last_mtime:
                        last_mtime = ts
                        yield f"data: {json.dumps({'type':'message','data':m})}\n\n"
                # Check status change
                filter_enc2 = requests.utils.quote(f'instance_id="{instance_id}"')
                _, status_data = pb_get("relay_status", params={"filter": filter_enc2})
                items = status_data.get("items", []) if status_data else []
                if items:
                    st = items[0]
                    st_key = f"{st.get('uptime')}-{st.get('lastUpdate')}"
                    if st_key != last_status.get(instance_id):
                        last_status[instance_id] = st_key
                        yield f"data: {json.dumps({'type':'status','data':st})}\n\n"
            time.sleep(3)
    return Response(generate(), mimetype="text/event-stream")

# ============================================================
# Admin HTML
# ============================================================
@app.route("/admin")
def admin_page():
    with open(os.path.join(os.path.dirname(__file__), "admin.html")) as f:
        return f.read(), 200, {"Content-Type": "text/html"}

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    import sys
    port = int(os.environ.get("PORT", 8977))
    print(f"[pebble-relay] Starting v2.1 on port {port}")
    print(f"[pebble-relay] PocketBase: {PB_URL}")
    if not config.get("admin", {}).get("password_hash"):
        print(f"[pebble-relay] First-time setup: POST /api/v1/admin/setup with {{\"password\":\"your_password\"}}")
    app.run(host="0.0.0.0", port=port, debug=False)
