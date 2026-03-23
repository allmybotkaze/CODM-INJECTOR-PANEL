from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid, time, json, os, random, string, requests

app = Flask(__name__)
CORS(app)

# ======================
# CONFIGURATION
# ======================
DATA_FILE = "database.json"
TOKEN_EXPIRY = 5
COOLDOWN = 120
KEY_LIMIT = 120

# ❗ I-PASTE DITO YUNG NASA SCREENSHOT 202149
SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbyMPXyWqdIV5BPiW8RSKSLRphNPpxrv5SjKMy65pbTkjIZYZY13wsH14u_gPXD4uB7u/exec"

TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

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
# GOOGLE SHEETS SYNC (READ/WRITE)
# ======================
def sync_to_sheets(key, device, status, expiry_timestamp):
    if not SHEETS_WEBHOOK_URL: return
    try:
        expiry_str = time.ctime(expiry_timestamp) if expiry_timestamp else "N/A"
        payload = {"key": key, "device": device or "N/A", "status": status, "expiry": expiry_str}
        requests.post(SHEETS_WEBHOOK_URL, json=payload, timeout=8)
    except: pass

def recover_from_sheets():
    if not SHEETS_WEBHOOK_URL: return
    try:
        # Kumukuha ng data mula sa Google Sheets GET method
        response = requests.get(SHEETS_WEBHOOK_URL, timeout=10)
        rows = response.json()
        for row in rows[1:]: # Skip header
            key_name = row[1]
            device_id = row[2]
            if key_name not in db["keys"]:
                db["keys"][key_name] = {
                    "expiry": time.time() + 43200, 
                    "device": None if device_id == "N/A" else device_id,
                    "revoked": False
                }
        save_db()
    except: pass

# ======================
# ROUTES
# ======================
@app.route("/")
def home():
    return "KAZE SERVER ONLINE 🚀"

@app.route("/token")
def token():
    ip = request.remote_addr
    now = time.time()
    source = request.args.get("src", "site")

    if source != "bot" and ip in db.get("cooldowns", {}):
        if now - db["cooldowns"][ip] < COOLDOWN:
            return jsonify({"status":"cooldown", "redirect":"https://kazehayamodz-main-page-zua8.onrender.com"})

    token_id = str(uuid.uuid4())
    db["tokens"][token_id] = {"ip": ip, "time": now}
    save_db()
    return jsonify({"status":"success", "token": token_id})

@app.route("/getkey")
def getkey():
    token_id = request.args.get("token")
    source = request.args.get("src", "site")
    duration = request.args.get("duration", "12h")

    if not token_id or token_id not in db["tokens"]:
        return jsonify({"status": "error", "message": "Invalid Token"}), 403

    user_ip = db["tokens"][token_id]["ip"]
    prefix = "Kaze-" if source == "bot" else "KazeFreeKey-"
    key = prefix + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    expiry_seconds = 43200 # 12h default
    if duration == "24h": expiry_seconds = 86400

    db["keys"][key] = {"expiry": time.time() + expiry_seconds, "device": None, "revoked": False}
    
    if source != "bot":
        db["cooldowns"][user_ip] = time.time()

    del db["tokens"][token_id]
    save_db()
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
        sync_to_sheets(key, device, "FIRST LOGIN", data["expiry"])
        return "valid"
    return "valid" if data["device"] == device else "locked"

# ======================
# STARTUP RECOVERY
# ======================
if __name__ == "__main__":
    recover_from_sheets() # Kukunin ang keys sa Sheets bago mag-start
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
