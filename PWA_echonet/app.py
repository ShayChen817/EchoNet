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

# How long before a node is considered stale (Windows needs 60s)
STALE_TIME = 60

# Global node table
DISCOVERED_NODES = {}

app = Flask(__name__, static_folder="static", static_url_path="")

# ----------------------------
# UTILS
# ----------------------------
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except:
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
    except:
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
    except:
        return 0.0


def compute_health(cpu, battery, load):
    score = 1.0
    if cpu > 80: score -= 0.3
    elif cpu > 50: score -= 0.15

    if battery is not None:
        if battery < 20: score -= 0.4
        elif battery < 50: score -= 0.2

    if load > MAX_LOAD * 0.7: score -= 0.2
    elif load > MAX_LOAD * 0.5: score -= 0.1

    return max(score, 0)


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
        except:
            return

        # Ignore our own service
        if node_id == NODE_ID:
            return

        try:
            node_ip = socket.inet_ntoa(info.addresses[0])
        except:
            return

        skills = json.loads(info.properties[b"skills"].decode())
        metrics = json.loads(info.properties[b"metrics"].decode())

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
        """Refresh timestamp when a node advertises again"""
        info = zc.get_service_info(service_type, name)
        if not info:
            return

        try:
            node_id = info.properties[b"id"].decode()
        except:
            return

        if node_id in DISCOVERED_NODES:
            DISCOVERED_NODES[node_id]["timestamp"] = time.time()
            DISCOVERED_NODES[node_id]["last_seen"] = time.strftime("%H:%M:%S")

    def remove_service(self, *args):
        # Do NOT remove nodes here — stale removal is handled elsewhere
        pass


# ----------------------------
# ADVERTISER THREAD
# ----------------------------
def advertiser_thread():
    zc = Zeroconf(ip_version=4)
    ip = get_local_ip()

    props = {
        "id": NODE_ID,
        "skills": json.dumps(SKILLS),
        "metrics": json.dumps(get_node_metrics()),
    }

    info = ServiceInfo(
        "_echotest._tcp.local.",
        f"{NODE_ID}._echotest._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=PORT,
        properties=props,
        server=f"{NODE_ID}.local.",  # REQUIRED for Windows reliability
    )

    zc.register_service(info)
    print(f"📡 Advertising node {NODE_ID} on {ip}:{PORT}")

    while True:
        # Refresh metrics
        metrics = json.dumps(get_node_metrics()).encode()
        info.properties[b"metrics"] = metrics

        # Try to update
        try:
            zc.update_service(info)
        except:
            # Windows fallback: rebuild service
            print("⚠️ Rebuilding ServiceInfo for stability")
            new_info = ServiceInfo(
                "_echotest._tcp.local.",
                f"{NODE_ID}._echotest._tcp.local.",
                addresses=[socket.inet_aton(get_local_ip())],
                port=PORT,
                properties=info.properties,
                server=f"{NODE_ID}.local.",
            )
            zc.register_service(new_info)
            info = new_info

        time.sleep(3)


# ----------------------------
# FLASK ROUTES
# ----------------------------
@app.route("/")
def serve_index():
    return app.send_static_file("index.html")


@app.get("/info")
def info():
    return jsonify(get_node_metrics())


@app.get("/nodes")
def get_nodes():
    now = time.time()

    # Filter stale nodes (WAS 10 seconds — TOO SHORT!)
    stale = [nid for nid, n in DISCOVERED_NODES.items()
             if now - n["timestamp"] > STALE_TIME]

    for nid in stale:
        del DISCOVERED_NODES[nid]

    return jsonify(list(DISCOVERED_NODES.values()))


@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)


# ----------------------------
# MAIN APP EXECUTION
# ----------------------------
if __name__ == "__main__":
    # Start advertiser
    threading.Thread(target=advertiser_thread, daemon=True).start()

    # Start Flask in background
    flask_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT),
        daemon=True
    )
    flask_thread.start()

    time.sleep(1)

    # Start discovery
    zc = Zeroconf(ip_version=4)
    ServiceBrowser(zc, "_echotest._tcp.local.", DiscoveryListener())

    print("\n🔥 All systems running...\n")

    while True:
        time.sleep(1)
