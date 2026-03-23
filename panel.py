from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import uuid, time, os, random, string, requests

app = Flask(__name__)
CORS(app)

# ==========================================
# 1. MONGO DB CONFIGURATION
# SIGURADUHIN NA TAMA ANG PASSWORD (Kaze828)
# ==========================================
MONGO_URI = "mongodb+srv://KAZEHAYAMODZ:Kaze828@cluster0.uxadnqx.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)
db_mongo = client["KAZE_DATABASE"]
keys_col = db_mongo["keys"]
tokens_col = db_mongo["tokens"]
limits_col = db_mongo["limits"]

# MASTER KEYS - Backup mo para laging may working key
MASTER_KEYS = ["KAZE-OWNER-PRO", "VIP-PERMANENT-2026"]

# CONSTANTS
TOKEN_EXPIRY = 300       
KEY_LIMIT = 120         
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not OWNER_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": OWNER_ID, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, data=payload, timeout=5)
    except: pass

# ==========================================
# ROUTES (JSON FORMAT ONLY)
# ==========================================
@app.route("/")
def home():
    return "KAZE SERVER ONLINE 🚀"

@app.route("/token")
def token():
    try:
        ip = request.remote_addr
        token_id = str(uuid.uuid4())
        # Save token to MongoDB
        tokens_col.insert_one({"token": token_id, "ip": ip, "time": time.time()})
        
        # Binalik sa dating JSON format
        return jsonify({
            "status": "success",
            "token": token_id
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/getkey")
def getkey():
    token_id = request.args.get("token")
    source = request.args.get("src", "site")
    now = time.time()

    token_data = tokens_col.find_one({"token": token_id})
    if not token_data:
        return jsonify({"status": "error", "message": "Invalid or Expired Token"}), 403

    ip = token_data["ip"]
    
    last_gen = limits_col.find_one({"ip": ip})
    if last_gen and (now - last_gen["time"] < KEY_LIMIT):
        wait = int(KEY_LIMIT - (now - last_gen["time"]))
        return jsonify({"status": "wait", "message": f"Wait {wait}s"}), 403

    prefix = "Kaze-" if source == "bot" else "KazeFreeKey-"
    key = prefix + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    keys_col.insert_one({
        "key": key,
        "expiry": now + 43200, 
        "device": None,
        "revoked": False
    })

    limits_col.update_one({"ip": ip}, {"$set": {"time": now}}, upsert=True)
    tokens_col.delete_one({"token": token_id})

    return jsonify({"status": "success", "key": key})

@app.route("/verify")
def verify():
    key = request.args.get("key")
    device = request.args.get("device")
    
    if key in MASTER_KEYS: return "valid"

    data = keys_col.find_one({"key": key})
    if not data: return "invalid"
    if data.get("revoked"): return "revoked"
    if time.time() > data["expiry"]: return "expired"

    if data["device"] is None:
        keys_col.update_one({"key": key}, {"$set": {"device": device}})
        send_telegram_alert(f"✓ *Key Used*\nKey: `{key}`\nDevice: `{device}`")
        return "valid"
    
    return "valid" if data["device"] == device else "locked"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
