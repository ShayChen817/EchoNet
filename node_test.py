import time
import json
import socket
import psutil
import threading
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser

# ----------------------------
# CONFIG
# ----------------------------
NODE_ID = "nodeA"   # Change to nodeB on second machine
PORT = 9999
SKILLS = ["test-skill"]

MAX_LOAD = 10
current_load = 0
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
        bat = psutil.sensors_battery()
        return bat.percent if bat else None
    except:
        return None


def compute_health(cpu, battery, load):
    score = 1.0
    if cpu > 80: score -= 0.3
    elif cpu > 50: score -= 0.15

    if battery is not None:
        if battery < 20: score -= 0.4
        elif battery < 50: score -= 0.2

    if load > MAX_LOAD * 0.75: score -= 0.2
    elif load > MAX_LOAD * 0.5: score -= 0.1

    return max(score, 0.0)


def get_node_metrics():
    cpu = psutil.cpu_percent()
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

        node_ip = socket.inet_ntoa(info.addresses[0])
        node_id = info.properties[b"id"].decode()

        if node_id == NODE_ID:
            return

        metrics = json.loads(info.properties[b"metrics"].decode())
        skills = json.loads(info.properties[b"skills"].decode())

        print(f"\n✨ FOUND NODE → {node_id} @ {node_ip}:{info.port}")
        print(f"   skills: {skills}")
        print(f"   cpu: {metrics['cpu']}%")
        print(f"   battery: {metrics['battery']}")
        print(f"   load: {metrics['load']} / {metrics['max_load']}")
        print(f"   health: {metrics['health']:.2f}")

    def remove_service(self, zc, service_type, name):
        print(f"💦 Node disappeared: {name}")


def advertiser():
    """Correct Zeroconf advertisement loop (no unregister)."""
    zc = Zeroconf()
    ip = get_local_ip()

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
    print(f"📡 Registered {NODE_ID} @ {ip}:{PORT}")

    while True:
        # Update metrics only — no unregister
        info.properties[b"metrics"] = json.dumps(get_node_metrics()).encode()
        zc.update_service(info)
        time.sleep(3)


if __name__ == "__main__":
    adv_thread = threading.Thread(target=advertiser, daemon=True)
    adv_thread.start()

    zc = Zeroconf()
    ServiceBrowser(zc, "_echotest._tcp.lo
