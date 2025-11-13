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
PORT = 5000        # <--- Flask + Zeroconf use SAME PORT!
SKILLS = ["test-skill"]
MAX_LOAD = 5
current_load = 0
# ----------------------------

DISCOVERED_NODES = {}   # shared table for all discovered devices

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
    try:
        out = subprocess.check_output(["termux-battery-status"])
        data = json.loads(out.decode())
        return data.get("percentage")
    except:
        return None


def get_cpu():
    try:
        out = subprocess.check_output("top -bn1 | head -n 5", shell=True)
        text = out.decode().lower()
        for line in text.splitlines():
            if "%cpu" in line:
                num = "".join(ch for ch in line if ch.isdigit() or ch == '.')
                return float(num) if num else 0.0
        return 0.0
    except:
        return 0.0


def compute_health(cpu, battery, load):
    score = 1.0
    if cpu > 80: score -= 0.3
    if cpu > 50: score -= 0.15

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
# ZEROCONF LISTENER
# ----------------------------
class DiscoveryListener:
    def add_service(self, zc, service_type, name):
        info = zc.get_service_info(service_type, name)
        if not info: return

        node_id = info.properties[b"id"].decode()
        if node_id == NODE_ID:
            return

        skills = json.loads(info.properties[b"skills"].decode())
        metrics = json.loads(info.properties[b"metrics"].decode())
        node_ip = socket.inet_ntoa(info.addresses[0])

        DISCOVERED_NODES[node_id] = {
            "id": node_id,
            "ip": node_ip,
            "port": info.port,
            "skills": skills,
            "metrics": metrics,
            "timestamp": time.time()
        }

        print(f"\n✨ FOUND NODE → {node_id} @ {node_ip}:{info.port}")

    def update_service(self, *args): pass
    def remove_service(self, *args): pass


# ----------------------------
# ZEROCONF ADVERTISER THREAD
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
    )

    zc.register_service(info)

    while True:
        # update metrics without re-registering
        info.properties[b"metrics"] = json.dumps(get_node_metrics()).encode()
        zc.update_service(info)
        time.sleep(3)


# ----------------------------
# FLASK ROUTES (PWA + NODES)
# ----------------------------
@app.route("/")
def serve_index():
    return app.send_static_file("index.html")

@app.get("/info")
def info():
    return jsonify(get_node_metrics())


@app.get("/nodes")
def get_nodes():
    # remove stale nodes older than 10s
    now = time.time()
    dead = [k for k,v in DISCOVERED_NODES.items() if now - v["timestamp"] > 10]
    for k in dead: del DISCOVERED_NODES[k]

    return jsonify(list(DISCOVERED_NODES.values()))


@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)


# ----------------------------
# MAIN
# ----------------------------
if __name__ == "__main__":
    # Start advertiser first
    threading.Thread(target=advertiser_thread, daemon=True).start()

    # Start Flask
    flask_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT),
        daemon=True
    )
    flask_thread.start()

    time.sleep(1)   # Allow Flask to start fully

    # Start Zeroconf browser LAST
    zc = Zeroconf(ip_version=4)
    ServiceBrowser(zc, "_echotest._tcp.local.", DiscoveryListener())

    print("\n🔥 All systems running...\n")

    while True:
        time.sleep(1)

