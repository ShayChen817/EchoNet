# net_phone.py — PHONE CLIENT ONLY VERSION
import os
import json
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="frontend", static_url_path="")
CORS(app)

# 💗 Your cluster entry node (only one needed)
CLUSTER_ENTRY = os.getenv("CLUSTER_ENTRY", "http://192.168.0.105:5001")

# Simple user token
USER_TOKEN = os.getenv("USER_TOKEN", "testtoken123")


@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


# ====== PHONE → CLUSTER PROXY ENDPOINTS ======

@app.route("/task", methods=["POST"])
def proxy_task():
    """Phone forwards tasks to the cluster entry node."""
    payload = request.json or {}
    try:
        r = requests.post(
            f"{CLUSTER_ENTRY}/task",
            json=payload,
            headers={"X-User-Token": USER_TOKEN},
            timeout=60,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": "cluster unreachable", "detail": str(e)}), 500


@app.route("/analyze", methods=["POST"])
def proxy_analyze():
    """Optional: let phone call cluster’s /analyze."""
    payload = request.json or {}
    try:
        r = requests.post(
            f"{CLUSTER_ENTRY}/analyze",
            json=payload,
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


# Serve static frontend files
@app.route("/<path:path>")
def static_proxy(path):
    return send_from_directory("frontend", path)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"📱 Phone client starting on 0.0.0.0:{port}")
    print(f"➡️ Forwarding all cluster calls to: {CLUSTER_ENTRY}")
    app.run(host="0.0.0.0", port=port)
