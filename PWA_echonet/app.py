import time
import json
import socket
import subprocess
import threading
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser
from flask import Flask, jsonify, send_from_directory

# ----------------------------
# DEVICE CONFIG
# ----------------------------
NODE_ID = "phoneNode"
PORT = 5000
SKILLS = ["test-skill"]
MAX_LOAD = 5
current_load = 0

# How long before a node is considered stale
# (keep 60s if Windows is being annoying; you can lower later if stable)
STALE_TIME = 60

# Global node table + lock
DISCOVERED_NODES = {}
NODES_LOCK = threading.Lock()

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
# DISCOVERY LISTENER
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

        # Ignore our own service
        if node_id == NODE_ID:
            return

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
        # You could also update metrics here if you want:
        # metrics = json.loads(info.properties[b"metrics"].decode())
        # DISCOVERED_NODES[node_id]["metrics"] = metrics

    def remove_service(self, zc, service_type, name):
        """
        Called when a service is explicitly unregistered by the remote node.
        We delete it immediately from our table.
        """
        node_id = None
        try:
            # Try to get properties first
