# net_phone.py — PHONE CLIENT ONLY VERSION (static/ + top-level service-worker)

import os
import json
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STATIC_DIR = os.path.join(BASE_DIR, "static")          # Your frontend folder
SW_FILE = os.path.join(BASE_DIR, "service-worker.js")  # Your PWA service worker

# ⭐ Host static as root ("/")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/")
CORS(app)

# ⭐ Cluster entry node Y O U choose
CLUSTER_ENTRY = os.getenv("CLUSTER_ENTRY", "http://192.168.0.105:5001")
USER_TOKEN = os.getenv("USER_TOKEN", "testtoken123")


# ---------------------------------------------------------
#  Serve PWA pages
# ---------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/service-worker.js")
def service_worker():
    # must be served from root domain for PWA
    return send_from_directory(BASE_DIR, "service-worker.js",
                               mimetype="application/javascript")


# ---------------------------------------------------------
# PHONE → CLUSTER PROXY ENDPOINTS
# ---------------------------------------------------------

@app.route("/task", methods=["POST"])
def proxy_task():
    try:
        r = requests.post(
            f"{CLUSTER_ENTRY}/task",
            json=request.json,
            headers={"X-User-Token": USER_TOKEN},
            timeout=60,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": "cluster unreachable", "detail": str(e)}), 500


@app.route("/analyze", methods=["POST"])
def proxy_analyze():
    try:
        r = requests.post(
            f"{CLUSTER_ENTRY}/analyze",
            json=request.json,
            headers={"X-User-Token": USER_TOKEN},
            timeout=60,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": "cluster unreachable", "detail": str(e)}), 500


@app.route("/result/<tid>", methods=["GET"])
def proxy_result(tid):
    try:
        r = requests.get(
            f"{CLUSTER_ENTRY}/result/{tid}",
            headers={"X-User-Token": USER_TOKEN},
            timeout=60,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": "cluster unreachable", "detail": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"📱 Phone client running at http://0.0.0.0:{port}")
    print(f"➡️ Forwarding tasks to: {CLUSTER_ENTRY}")
    app.run(host="0.0.0.0
