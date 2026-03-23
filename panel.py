from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid, time, json, os, random, string, requests

app = Flask(__name__)
CORS(app)

# ======================
# CONFIGURATION
# ======================
DATA_FILE = "database.json"
TOKEN_EXPIRY = 5       # 5 minutes for token
COOLDOWN = 120           # anti-spam
KEY_LIMIT = 120         

# ❗ I-PASTE DITO YUNG URL NA NAKUHA NATIN SA GOOGLE SHEETS
SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzU7JO0eziv1-pP6UAPTsD_qf5niJkwxYFr8NcG7ORLyfJYjFRz1chU0D2sClZV0oj98A/exec"

TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

# ======================
# DB HELPERS
# ======================
def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f: return json.load(f)
        except: pass
    return {"keys": {}, "tokens": {}, "ip_limit": {}, "cooldowns": {}}

db = load_db()

def save_db():
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, indent=4)

# ======================
# GOOGLE SHEETS SYNC
# ======================
def sync_to_sheets(key, device, status, expiry_timestamp):
    if not SHEETS_WEBHOOK_URL: return
    try:
        expiry_str = time.ctime(expiry_timestamp) if expiry_timestamp else "N/A"
        payload = {
            "key": key,
            "device": device or "N/A",
            "status": status,
            "expiry": expiry_str
        }
        # Ito ang magpapadala ng data sa Google Sheet mo
        requests.post(SHEETS_WEBHOOK_URL, json=payload, timeout=8)
    except: pass

# ======================
# TELEGRAM ALERT
# ======================
def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not OWNER_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": OWNER_ID, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, data=payload, timeout=5)
    except: pass

# ======================
# HELPERS
# ======================
def cleanup():
    now = time.time()
    for t in list(db["tokens"].keys()):
        if now - db["tokens"][t]["time"] > TOKEN_EXPIRY: del db["tokens"][t]
    for ip in list(db["ip_limit"].keys()):
        if now - db["ip_limit"][ip] > KEY_LIMIT: del db["ip_limit"][ip]

def convert_duration(duration: str):
    duration = duration.lower()
    if duration.endswith("m"): return int(duration[:-1]) * 60
    if duration.endswith("h"): return int(duration[:-1]) * 3600
    if duration.endswith("d"): return int(duration[:-1]) * 86400
    if duration == "lifetime": return 999999999
    return 43200 # default 12h

# ======================
# ROUTES
# ======================
@app.route("/")
def home():
    return "KAZE SERVER ONLINE 🚀 (Sheets Linked)"

# ======================
# TOKEN
# ======================
@app.route("/token")
def token():
    cleanup()
    ip = request.remote_addr
    now = time.time()
    source = request.args.get("src", "site")

    # CHECK COOLDOWN ONLY IF IP ALREADY HAS ONE
    if source != "bot":
        if ip in db["cooldowns"]:
            elapsed = now - db["cooldowns"][ip]
            if elapsed < COOLDOWN:
                return jsonify({
                    "status":"cooldown",
                    "redirect":"https://kazehayamodz-main-page-zua8.onrender.com"
                })

    # GENERATE TOKEN
    token_id = str(uuid.uuid4())
    db["tokens"][token_id] = {"ip": ip, "time": now}

    save_db()
    return jsonify({
        "status":"success",
        "token": token_id
    })

@app.route("/getkey")
def getkey():
    token_id = request.args.get("token")
    duration = request.args.get("duration", "12h")
    source = request.args.get("src", "site")

    if not token_id or token_id not in db["tokens"]:
        return jsonify({"status": "error", "message": "Invalid Token"}), 403

    # Kunin muna natin ang IP mula sa token bago ito i-delete
    ip = db["tokens"][token_id]["ip"]

    prefix = "Kaze-" if source == "bot" else "KazeFreeKey-"
    key = prefix + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    expiry_seconds = convert_duration(duration)
    db["keys"][key] = {
        "expiry": time.time() + expiry_seconds,
        "device": None,
        "revoked": False
    }
    
    # --- DITO MO ILALAGAY YUNG TINATANONG MO ---
    if source != "bot":
        db["cooldowns"][ip] = time.time() # Dito magsisimula ang cooldown
    
    del db["tokens"][token_id]
    save_db() #
    # ------------------------------------------
    
    sync_to_sheets(key, "N/A", "GENERATED", db["keys"][key]["expiry"])
    
    return jsonify({"status": "success", "key": key, "expires_in": expiry_seconds})
    
@app.route("/verify")
def verify():
    key = request.args.get("key")
    device = request.args.get("device")
    
    if not key or key not in db["keys"]: return "invalid"
    
    data = db["keys"][key]
    if data.get("revoked"): return "revoked"
    if time.time() > data["expiry"]: return "expired"

    if data["device"] is None:
        data["device"] = device
        save_db()
        send_telegram_alert(f"✅ *New Login*\nKey: `{key}`\nDevice: `{device}`")
        sync_to_sheets(key, device, "FIRST LOGIN", data["expiry"])
        return "valid"

    if data["device"] == device:
        sync_to_sheets(key, device, "RE-LOGIN", data["expiry"])
        return "valid"

    return "locked"

@app.route("/stats")
def stats():
    cleanup()
    total = len(db["keys"])
    active = len([k for k in db["keys"] if not db["keys"][k].get("revoked") and time.time() < db["keys"][k]["expiry"]])
    return jsonify({
        "total_keys": total,
        "active_keys": active,
        "expired_keys": total - active
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
