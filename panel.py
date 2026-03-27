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
# CONSTANTS (Updated)
# ======================
TOKEN_EXPIRY = 300       # Ginawa nating 5 mins para hindi sila ma-expire agad habang nasa gplinks
COOLDOWN = 60            
KEY_LIMIT = 43200        # 12 HOURS (Para hindi sila makakuha ng bagong key agad-agad)
DATA_FILE = "database.json"

TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

# ======================
# LOAD DB
# ======================
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        db = json.load(f)
else:
    db = {
        "keys": {},
        "tokens": {},
        "ip_limit": {},
        "cooldowns": {},
        "ip_keys": {}  # DITO NATIN I-STORE ANG KEY PER IP
    }

# Siguraduhin na may "ip_keys" sa db kung luma na ang json mo
if "ip_keys" not in db:
    db["ip_keys"] = {}

def save_db():
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, indent=4)

# ======================
# HELPER: GET REAL IP (For Render)
# ======================
def get_ip():
    # Sa Render, kailangan ang X-Forwarded-For para sa totoong IP ng user
    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

# ======================
# CLEANUP (Updated)
# ======================
def cleanup():
    now = time.time()
    for t in list(db["tokens"].keys()):
        if now - db["tokens"][t]["time"] > TOKEN_EXPIRY:
            del db["tokens"][t]
    
    # Linisin ang IP limit kapag tapos na ang 12 hours
    for ip in list(db["ip_limit"].keys()):
        if now - db["ip_limit"][ip] > KEY_LIMIT:
            del db["ip_limit"][ip]
            if ip in db["ip_keys"]:
                del db["ip_keys"][ip]

# ... [Keep your convert_duration, home, and token functions as they are] ...

# ======================
# GENERATE KEY (SECURE VERSION)
# ======================
@app.route("/getkey")
def getkey():
    cleanup()
    token_id = request.args.get("token")
    source = request.args.get("src", "site")
    duration = request.args.get("duration", "12h")
    
    ip = get_ip()
    now = time.time()

    # 1. SMART CHECK: Meron na ba siyang existing key para sa IP na ito?
    # Kung nag-refresh ang user sa Chrome, ibigay lang ang lumang key.
    if ip in db["ip_keys"]:
        existing_key = db["ip_keys"][ip]
        # I-verify kung valid pa ang key na ito
        if existing_key in db["keys"] and now < db["keys"][existing_key]["expiry"]:
            return jsonify({
                "status": "success",
                "key": existing_key,
                "message": "Key restored (Refresh Protection)"
            })

    # 2. TOKEN VALIDATION
    if not token_id or token_id not in db["tokens"]:
        return jsonify({"status": "error", "message": "Invalid or Expired Token. Go back to main page."}), 403

    # 3. ANTI-SPAM (Wait for 12 hours before getting a TRULY NEW key)
    if ip in db["ip_limit"]:
        elapsed = now - db["ip_limit"][ip]
        if elapsed < KEY_LIMIT:
            # Dito, kung wala sa ip_keys pero nasa ip_limit, ibig sabihin may error o bypass
            return jsonify({"status": "error", "message": "Limit reached. Try again later."}), 403

    # 4. GENERATE NEW KEY
    prefix = "Kaze-" if source == "bot" else "KazeFreeKey-"
    key = prefix + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    expiry_seconds = convert_duration(duration)

    db["keys"][key] = {
        "expiry": now + expiry_seconds,
        "device": None,
        "revoked": False,
        "login_time": None
    }

    # 5. SAVE TO IP MEMORY
    db["ip_limit"][ip] = now
    db["ip_keys"][ip] = key # I-bind ang key sa IP na ito

    # remove used token
    del db["tokens"][token_id]
    save_db()

    return jsonify({
        "status": "success",
        "key": key,
        "expires_in": expiry_seconds
    })

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
    
