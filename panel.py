from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid
import time
import json
import os
import random
import string
import requests

app = Flask(__name__)
CORS(app)

# ======================
# CONFIG
# ======================
TOKEN_EXPIRY = 1000      # 16.6 minutes para relax ang user sa gplinks
COOLDOWN = 60            # 1 minute cooldown para sa token request
KEY_LIMIT = 43200        # 12 HOURS (Same key for the same IP)
DATA_FILE = "database.json"

TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

# ======================
# DATABASE INITIALIZATION
# ======================
def load_db():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            # Siguraduhin na nandito lahat ng keys para iwas Server Error
            if "ip_keys" not in data: data["ip_keys"] = {}
            if "keys" not in data: data["keys"] = {}
            if "tokens" not in data: data["tokens"] = {}
            if "ip_limit" not in data: data["ip_limit"] = {}
            if "cooldowns" not in data: data["cooldowns"] = {}
            return data
    return {"keys": {}, "tokens": {}, "ip_limit": {}, "cooldowns": {}, "ip_keys": {}}

db = load_db()

def save_db():
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, indent=4)

def get_ip():
    # Fix para sa Render Proxy IP
    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

# ======================
# CLEANUP
# ======================
def cleanup():
    now = time.time()
    for t in list(db["tokens"].keys()):
        if now - db["tokens"][t]["time"] > TOKEN_EXPIRY:
            del db["tokens"][t]
    
    for ip in list(db["ip_limit"].keys()):
        if now - db["ip_limit"][ip] > KEY_LIMIT:
            del db["ip_limit"][ip]
            if ip in db["ip_keys"]:
                del db["ip_keys"][ip]
    save_db()

# ======================
# CORE FUNCTIONS
# ======================
def convert_duration(duration: str):
    duration = duration.lower()
    if duration.endswith("h"): return int(duration[:-1]) * 3600
    if duration.endswith("d"): return int(duration[:-1]) * 86400
    if duration == "lifetime": return 999999999
    return 43200 # Default 12h

@app.route("/")
def home():
    return "KAZE SERVER ONLINE 🚀"

@app.route("/token")
def token():
    cleanup()
    ip = get_ip()
    now = time.time()
    
    if ip in db["cooldowns"]:
        if now - db["cooldowns"][ip] < COOLDOWN:
            return jsonify({"status": "cooldown", "redirect": "https://kazehayamodz-main-page-zua8.onrender.com"})
    
    token_id = str(uuid.uuid4())
    db["tokens"][token_id] = {"ip": ip, "time": now}
    db["cooldowns"][ip] = now
    save_db()
    return jsonify({"status": "success", "token": token_id})

@app.route("/getkey")
def getkey():
    cleanup()
    token_id = request.args.get("token")
    source = request.args.get("src", "site")
    duration = request.args.get("duration", "12h")
    ip = get_ip()
    now = time.time()

    # 1. SMART RESTORE (Anti-Refresh)
    if ip in db["ip_keys"]:
        k = db["ip_keys"][ip]
        if k in db["keys"] and now < db["keys"][k]["expiry"]:
            return jsonify({"status": "success", "key": k, "restored": True})

    # 2. TOKEN CHECK
    if not token_id or token_id not in db["tokens"]:
        return jsonify({"status": "error", "message": "Expired Token. Restart Process."}), 403

    # 3. GENERATE
    prefix = "Kaze-" if source == "bot" else "KazeFreeKey-"
    new_key = prefix + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    expiry_sec = convert_duration(duration)
    db["keys"][new_key] = {"expiry": now + expiry_sec, "device": None, "revoked": False}
    db["ip_limit"][ip] = now
    db["ip_keys"][ip] = new_key
    
    if token_id in db["tokens"]: del db["tokens"][token_id]
    save_db()
    return jsonify({"status": "success", "key": new_key, "expires_in": expiry_sec})

# ======================
# VERIFY KEY
# ======================
@app.route("/verify")
def verify():
    cleanup()
    key = request.args.get("key")
    device = request.args.get("device")
    if not key or key not in db["keys"]:
        return "invalid"
    data = db["keys"][key]
    if data.get("revoked"):
        send_telegram_alert(f"ðŸš« *Key Revoked*\nKey: `{key}`\nDevice: `{device}`")
        return "revoked"
    if time.time() > data["expiry"]:
        send_telegram_alert(f"âš ï¸ *Key Expired*\nKey: `{key}`\nDevice: `{device}`")
        return "expired"
    if data["device"] is None:
        data["device"] = device
        data["login_time"] = time.time()
        save_db()
        remaining = int(data["expiry"] - time.time())
        send_telegram_alert(f"âœ“ *Key Used*\nKey: `{key}`\nDevice: `{device}`\nExpires in: `{remaining}s`")
        return "valid"
    if data["device"] == device:
        remaining = int(data["expiry"] - time.time())
        send_telegram_alert(f"âœ“ *Key Used*\nKey: `{key}`\nDevice: `{device}`\nExpires in: `{remaining}s`")
        return "valid"
    send_telegram_alert(f"ðŸ”’ *Key Locked - Device Mismatch*\nKey: `{key}`\nDevice Attempt: `{device}`\nAssigned Device: `{data['device']}`")
    return "locked"

# ======================
# REVOKE KEY
# ======================
@app.route("/revoke")
def revoke():
    key = request.args.get("key")
    if not key or key not in db["keys"]:
        return jsonify({"status": "error", "message": "Key not found"}), 404
    db["keys"][key]["revoked"] = True
    save_db()
    send_telegram_alert(f"ðŸš« *Key Revoked*\nKey: `{key}`")
    return jsonify({"status": "success", "message": f"{key} revoked"})

# ======================
# LIST ACTIVE KEYS
# ======================
@app.route("/list")
def list_keys():
    cleanup()
    result = []
    for key, data in db["keys"].items():
        if data.get("revoked"):
            continue
        if time.time() > data["expiry"]:
            continue
        result.append({
            "key": key,
            "device": data["device"],
            "expire_in": int(data["expiry"] - time.time())
        })
    return jsonify(result)

# ======================
# STATS
# ======================
@app.route("/stats")
def stats():
    cleanup()
    total = len(db["keys"])
    active = len([k for k in db["keys"] if not db["keys"][k].get("revoked") and time.time() < db["keys"][k]["expiry"]])
    expired = total - active
    return jsonify({
        "total_keys": total,
        "active_keys": active,
        "expired_keys": expired
    })

# ======================
# RUN SERVER
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
    
