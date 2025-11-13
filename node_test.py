import time
import json
import socket
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser

# ----------------------------
# CHANGE THIS PER DEVICE
# ----------------------------
NODE_ID = "nodeA"   # change to "nodeB" on the second laptop
PORT = 9999
SKILLS = ["test-skill", "ai_execute"]

# Maximum "weight" this device can handle (your decision)
MAX_LOAD = 10
current_load = 0
# ----------------------------


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


def get_battery():
    """Get battery percentage or None if unavailable."""
    try:
        bat = psutil.sensors_battery()
        if bat:
            return bat.percent
        return None
    except:
        return None


def compute_health(cpu, battery, load):
    """Define a health score (0-1)"""
    score = 1.0

    # CPU penalty
    if cpu > 80:
        score -= 0.3
    elif cpu > 50:
        score -= 0.15

    # Battery penalty
    if battery is not None:
        if battery < 20:
            score -= 0.4
        elif battery < 50:
            score -= 0.2

    # Load penalty
    if load > MAX_LOAD * 0.75:
        score -= 0.2
    elif load > MAX_LOAD * 0.5:
        score -= 0.1

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

    def add_service(self, zeroconf, service_type, name):
        info = zeroconf.get_service_info(service_type, name)
        if not info:
            return

        node_ip = socket.inet_ntoa(info.addresses[0])
        node_id = info.properties[b"id"].decode()
        skills = json.loads(info.properties[b"skills"].decode())

        print(f"✨ FOUND NODE → {node_id} @ {node_ip}:{info.port}, skills={skills}")

    def remove_service(self, zeroconf, service_type, name):
        print(f"💦 Node disappeared: {name}")


def advertise():
    """Advertise node metrics via Zeroconf."""
    zc = Zeroconf()
    ip = get_local_ip()

    # include a metrics blob so discoverers can show CPU/battery/load/health
    try:
        import psutil
    except Exception:
        psutil = None

    metrics = None
    try:
        if psutil:
            cpu = round(psutil.cpu_percent(interval=0.1), 1)
            try:
                batt = psutil.sensors_battery()
                battery = round(batt.percent, 1) if batt and batt.percent is not None else None
            except Exception:
                battery = None
            metrics = {'cpu': cpu, 'battery': battery, 'load': current_load, 'max_load': MAX_LOAD, 'health': 1.0}
    except Exception:
        metrics = None

    props = {
        "id": NODE_ID,
        "skills": json.dumps(SKILLS),
        "metrics": json.dumps(metrics) if metrics is not None else None
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
    print(f"🐣 ADVERTISING: {NODE_ID} @ {ip}:{PORT}")

    return zc, info


def start_discovery(zc):
    """Start browsing for other nodes."""
    print("🔎 STARTING DISCOVERY...")
    return ServiceBrowser(zc, "_echotest._tcp.local.", DiscoveryListener())


if __name__ == "__main__":
    # Start advertiser in background thread
    import threading
    adv_thread = threading.Thread(target=advertise, daemon=True)
    adv_thread.start()

    # Start discovery browser
    zc = Zeroconf()
    ServiceBrowser(zc, "_echotest._tcp.local.", DiscoveryListener())

    print("\n🔥 Running — waiting for other devices with metrics...\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Stopping...")
        zc.close()
