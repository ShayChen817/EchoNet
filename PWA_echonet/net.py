import time
import json
import socket
import subprocess
import threading
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser
from flask import Flask, jsonify

# ----------------------------
# CHANGE THIS PER DEVICE
# ----------------------------
NODE_ID = "phoneNode"
PORT = 4321
SKILLS = ["test-skill"]
MAX_LOAD = 5
current_load = 0
# ----------------------------

DISCOVERED_NODES = {}   # <--- NEW: shared node table


def get_local_ip():
    """Get LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# ----- SAFE BATTERY IN TERMUX -----
def get_battery():
    """Get battery level using Termux API."""
    try:
        out = subprocess.check_output(["termux-battery-status"])
        data = json.loads(out.decode())
        return data.get("percentage")
    except:
        return None


# ----- SAFE CPU IN TERMUX -----
def get_cpu():
    """Termux cannot access psutil CPU. Use /proc/stat safely."""
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


class DiscoveryListener:
    def add_service(self, zc, service_type, name):
        info = zc.get_service_info(service_type, name)
        if not info:
            return

        node_id = info.properties[b"id"].decode()
        if node_id == NODE_ID:
            return  # ignore ourselves

        skills = json.loads(info.properties[b"skills"].decode())
        metrics = json.loads(info.properties[b"metrics"].decode())
        node_ip = socket.inet_ntoa(info.addresses[0])

        # store in global table
        DISCOVERED_NODES[node_id] = {
            "id": node_id,
            "ip": node_ip,
            "port": info.port,
            "skills": skills,
            "metrics": metrics,
            "timestamp": time.time()
        }

        print(f"\n✨ FOUND NODE → {node_id} @ {node_ip}:{info.port}")
        print(f"   skills:  {skills}")
        print(f"   cpu:     {metrics['cpu']}")
        print(f"   battery: {metrics['battery']}")
        print(f"   load:    {metrics['load']}/{metrics['max_load']}")
        print(f"   health:  {metrics['health']:.2f}")

    def update_service(self, *a): pass
    def remove_service(self, *a): pass


def advertiser_thread():
    """Advertise updated metrics every ~3 seconds."""
    zc = Zeroconf(ip_version=4)
    ip = get_local_ip()

    while True:
        metrics = get_node_metrics()

        props = {
            "id": NODE_ID,
            "skills": json.dumps(SKILLS),
            "metrics": json.dumps(metrics),
        }

        info = ServiceInfo(
            "_echotest._tcp.local.",
            f"{NODE_ID}._echotest._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=PORT,
            properties=props,
        )

        zc.register_service(info)
        time.sleep(3)
        zc.unregister_service(info)


# ----------------------------
#       FLASK API
# ----------------------------
app = Flask(__name__)

@app.get("/nodes")
def get_nodes():
    # remove stale nodes after 10 sec
    now = time.time()
    dead = [k for k,v in DISCOVERED_NODES.items() if now - v["timestamp"] > 10]
    for k in dead: del DISCOVERED_NODES[k]

    return jsonify(list(DISCOVERED_NODES.values()))


# ----------------------------
#       MAIN ENTRY
# ----------------------------
if __name__ == "__main__":
    # advertiser
    threading.Thread(target=advertiser_thread, daemon=True).start()

    # browser
    zc = Zeroconf(ip_version=4)
    ServiceBrowser(zc, "_echotest._tcp.local.", DiscoveryListener())

    print("\n🔥 Node running... Zeroconf + API online...\n")

    # Flask web server
    app.run(host="0.0.0.0", port=PORT)
