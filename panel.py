from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from pymongo import MongoClient
import uuid, time, os, random, string, requests

app = Flask(__name__)
CORS(app)

# ======================
# 1. MONGO DB CONFIGURATION
# ======================
MONGO_URI = "mongodb+srv://KAZEHAYAMODZ:<db_password>@cluster0.uxadnqx.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db_mongo = client["KAZE_DATABASE"]
keys_col = db_mongo["keys"]
tokens_col = db_mongo["tokens"]
limits_col = db_mongo["limits"]

# MASTER KEYS - Hindi mawawala kahit mag-suspension
MASTER_KEYS = ["KAZE-OWNER-PRO", "VIP-PERMANENT-2026"]

# ======================
# CONSTANTS
# ======================
TOKEN_EXPIRY = 300       # 5 minutes para sa token
COOLDOWN = 120           
KEY_LIMIT = 120         
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

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
# HTML WITH COPY BUTTON
# ======================
HTML_TEMPLATE = """
<body style="background:#0a0a0a; color:#00ff00; text-align:center; padding:50px; font-family:monospace;">
    <div style="border:2px solid #00ff00; padding:20px; display:inline-block; border-radius:15px; box-shadow: 0 0 15px #00ff00;">
        <h2 style="text-shadow: 0 0 10px #00ff00;">KAZE MODZ PANEL</h2>
        <input id="t" value="{{t}}" readonly style="background:#000; color:#fff; border:1px solid #00ff00; padding:12px; width:280px; text-align:center; font-size:16px; border-radius:5px;">
        <br><br>
        <button onclick="copy()" style="background:#00ff00; color:#000; padding:12px 20px; font-weight:bold; cursor:pointer; width:100%; border:none; border-radius:5px;">CLICK TO COPY TOKEN</button>
        <p style="color:#888; font-size:12px; margin-top:15px;">Use this token to get your key.</p>
    </div>
    <script>
        function copy() { 
            var t=document.getElementById('t'); t.select(); 
            navigator.clipboard.writeText(t.value); 
            alert('Token Copied!'); 
        }
    </script>
</body>
"""

# ======================
# ROUTES
# ======================
@app.route("/")
def home():
    return "KAZE SERVER ONLINE 🚀"

@app.route("/token")
def token():
    ip = request.remote_addr
    token_id = str(uuid.uuid4())
    # Save token to MongoDB
    tokens_col.insert_one({"token": token_id, "ip": ip, "time": time.time()})
    return render_template_string(HTML_TEMPLATE, t=token_id)

@app.route("/getkey")
def getkey():
    token_id = request.args.get("token")
    source = request.args.get("src", "site")
    now = time.time()

    # Check MongoDB for Token
    token_data = tokens_col.find_one({"token": token_id})
    if not token_data:
        return jsonify({"status": "error", "message": "Invalid or Expired Token"}), 403

    ip = token_data["ip"]
    
    # Anti-spam check (MongoDB)
    last_gen = limits_col.find_one({"ip": ip})
    if last_gen and (now - last_gen["time"] < KEY_LIMIT):
        wait = int(KEY_LIMIT - (now - last_gen["time"]))
        return jsonify({"status": "wait", "message": f"Wait {wait}s"}), 403

    prefix = "Kaze-" if source == "bot" else "KazeFreeKey-"
    key = prefix + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    # Save Key to MongoDB
    keys_col.insert_one({
        "key": key,
        "expiry": now + 43200, # Default 12h
        "device": None,
        "revoked": False
    })

    # Update IP limit and delete token
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
    
    if data["device"] == device: return "valid"
    
    return "locked"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
