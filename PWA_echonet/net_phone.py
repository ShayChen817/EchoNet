import time
import json
import socket
import subprocess
import threading
import requests
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser
from flask import Flask, jsonify, send_from_directory

# ----------------------------
# DEVICE CONFIG (PHONE CLIENT)
# ----------------------------
NODE_ID = "phoneNode"
PORT = 5000

# IMPORTANT: phone should NOT be a worker node
SKILLS = []          # ← phone advertises NO skills
MAX_LOAD = 5
current_load = 0

# cluster entry (your laptop node)
CLUSTER_ENTRY = "http://192.168.0.105:5001"
USER_TOKEN = "testtoken123"

# remove nodes after stale time
STALE_TIME = 60

# global node table
DISCOVERED_NODES = {}
NODES_LOCK = threading.Lock()

# static folder = frontend
app = Flask(__name__, static_folder="static", static_url_path="")


# ----------------------------
# UTILS
# ----------------------------
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_battery():
    """Termux-only battery API"""
    try:
        out = subprocess.check_output(["termux-battery-status"])
        data = json.loads(out.decode())
        return data.get("percentage")
    except Exception:
        return None


def get_cpu():
    """Termux-friendly CPU usage"""
    try:
        out = subprocess.check_output("top -bn1 | head -n 5", shell=True)
        text = out.decode().lower()
        for line in text.splitlines():
            if "%cpu" in line:
                num = "".join(ch for ch in line if ch.isdigit() or ch == ".")
                return float(num) if num else 0.0
        return 0.0
    except Exception:
        return 0.0


def compute_health(cpu, battery, load):
    score = 1.0
    if cpu > 80:
        score -= 0.3
    elif cpu > 50:
        score -= 0.15

    if battery is not None:
        if battery < 20:
            score -= 0.4
        elif battery < 50:
            score -= 0.2

    if load > MAX_LOAD * 0.7:
        score -= 0.2
    elif load > MAX_LOAD * 0.5:
        score -= 0.1

    return max(score, 0.0)


def get_node_metrics():
    cpu = get_cpu()
    battery = get_battery()
    health = compute_health(cpu, battery, current_load)

    return {
        "cpu": cpu,
        "battery": battery,
        "load": current_load,
        "max_load": MAX_LOAD,
        "health": health,
    }


# ----------------------------
# DISCOVERY
# ----------------------------
class DiscoveryListener:
    def add_service(self, zc, service_type, name):
        info = zc.get_service_info(service_type, name)
        if not info:
            return

        try:
            node_id = info.properties[b"id"].decode()
        except Exception:
            return

        if node_id == NODE_ID:
            return  # ignore ourself

        try:
            node_ip = socket.inet_ntoa(info.addresses[0])
        except Exception:
            return

        try:
            skills = json.loads(info.properties[b"skills"].decode())
        except Exception:
            skills = []

        try:
            metrics = json.loads(info.properties[b"metrics"].decode())
        except Exception:
            metrics = {}

        with NODES_LOCK:
            DISCOVERED_NODES[node_id] = {
                "id": node_id,
                "ip": node_ip,
                "port": info.port,
                "skills": skills,
                "metrics": metrics,
                "timestamp": time.time(),
                "last_seen": time.strftime("%H:%M:%S"),
            }

        print(f"\n✨ FOUND NODE → {node_id} @ {node_ip}:{info.port}")

    def update_service(self, zc, service_type, name):
        info = zc.get_service_info(service_type, name)
        if not info:
            return

        try:
            node_id = info.properties[b"id"].decode()
        except Exception:
            return

        with NODES_LOCK:
            if node_id in DISCOVERED_NODES:
                DISCOVERED_NODES[node_id]["timestamp"] = time.time()
                DISCOVERED_NODES[node_id]["last_seen"] = time.strftime("%H:%M:%S")

    def remove_service(self, zc, service_type, name):
        node_id = None
        try:
            info = zc.get_service_info(service_type, name)
            if info and b"id" in info.properties:
                node_id = info.properties[b"id"].decode()
        except:
            pass

        if not node_id:
            try:
                node_id = name.split(".")[0]
            except:
                return

        with NODES_LOCK:
            if node_id in DISCOVERED_NODES:
                del DISCOVERED_NODES[node_id]
                print(f"❌ NODE DISCONNECTED → {node_id}")


# ----------------------------
# ADVERTISER (PHONE ANNOUNCES ITSELF)
# ----------------------------
def advertiser_thread():
    zc = Zeroconf(ip_version=4)
    ip = get_local_ip()

    props = {
        "id": NODE_ID,
        "skills": json.dumps([]),  # phone advertises NO skills
        "metrics": json.dumps(get_node_metrics()),
    }

    info = ServiceInfo(
        "_echotest._tcp.local.",
        f"{NODE_ID}._echotest._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=PORT,
        properties=props,
        server=f"{NODE_ID}.local.",
    )

    zc.register_service(info)
    print(f"📡 Advertising phone node {NODE_ID} on {ip}:{PORT}")

    while True:
        metrics = json.dumps(get_node_metrics()).encode()
        info.properties[b"metrics"] = metrics
        try:
            zc.update_service(info)
        except:
            pass
        time.sleep(3)


# ----------------------------
# FLASK ROUTES
# ----------------------------
@app.route("/")
def serve_index():
    return app.send_static_file("index.html")


@app.get("/service-worker.js")
def sw():
    return send_from_directory(".", "service-worker.js")


@app.get("/info")
def info():
    return jsonify(get_node_metrics())


@app.get("/nodes")
def get_nodes():
    now = time.time()
    with NODES_LOCK:
        stale = [nid for nid, n in DISCOVERED_NODES.items() if now - n["timestamp"] > STALE_TIME]
        for nid in stale:
            print(f"⏱ Removing stale node → {nid}")
            del DISCOVERED_NODES[nid]

        nodes_list = list(DISCOVERED_NODES.values())

    return jsonify(nodes_list)


# ⭐ PHONE → CLUSTER TASK FORWARDER ⭐
@app.post("/task")
def proxy_task():
    """Send tasks from phone to the real cluster node."""
    try:
        r = requests.post(
            f"{CLUSTER_ENTRY}/task",
            json=request.json,
            headers={"X-User-Token": USER_TOKEN},
            timeout=60
        )
        return (r.json(), r.status_code)
    except Exception as e:
        return {"error": "cluster unreachable", "detail": str(e)}, 500


@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)


# ---
