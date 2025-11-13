import time
import json
import socket
import psutil
import threading
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser

NODE_ID = "nodeA"
PORT = 9999
SKILLS = ["test-skill"]

MAX_LOAD = 10
current_load = 0

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def get_metrics():
    cpu = psutil.cpu_percent()
    try:
        bat = psutil.sensors_battery()
        battery = bat.percent if bat else None
    except:
        battery = None

    return {
        "cpu": cpu,
        "battery": battery,
        "load": current_load,
        "max_load": MAX_LOAD,
        "health": 1.0
    }

class DiscoveryListener:
    def add_service(self, zc, stype, name):
        info = zc.get_service_info(stype, name)
        if not info:
            return
        node_id = info.properties[b"id"].decode()
        if node_id == NODE_ID:
            return

        ip = socket.inet_ntoa(info.addresses[0])
        skills = json.loads(info.properties[b"skills"].decode())

        print(f"✨ FOUND NODE → {node_id} @ {ip}:{info.port}, skills={skills}")

def advertiser(zc):
    ip = get_local_ip()

    info = ServiceInfo(
        "_echotest._tcp.local.",
        f"{NODE_ID}._echotest._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=PORT,
        properties={
            "id": NODE_ID,
            "skills": json.dumps(SKILLS),
            "metrics": json.dumps(get_metrics())
        }
    )

    zc.register_service(info)
    print(f"📡 ADVERTISING {NODE_ID} on {ip}")

    while True:
        info.properties[b"metrics"] = json.dumps(get_metrics()).encode()
        zc.update_service(info)
        time.sleep(3)

if __name__ == "__main__":
    zc = Zeroconf()

    threading.Thread(target=advertiser, args=(zc,), daemon=True).start()
    ServiceBrowser(zc, "_echotest._tcp.local.", DiscoveryListener())

    print("🔥 Node running, waiting for others…")
    while True:
        time.sleep(1)
