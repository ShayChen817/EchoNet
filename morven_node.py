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

stop_event = threading.Event()
service_info = None


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


def get_metrics():
    cpu = psutil.cpu_percent(interval=None)
    try:
        bat = psutil.sensors_battery()
        battery = bat.percent if bat else None
    except Exception:
        battery = None

    return {
        "cpu": cpu,
        "battery": battery,
        "load": current_load,
        "max_load": MAX_LOAD,
        "health": 1.0,
    }


class DiscoveryListener:
    def add_service(self, zc, stype, name):
        info = zc.get_service_info(stype, name)
        if not info:
            return

        try:
            node_id = info.properties[b"id"].decode()
        except Exception:
            return

        if node_id == NODE_ID:
            return

        try:
            ip = socket.inet_ntoa(info.addresses[0])
        except Exception:
            ip = "?"

        try:
            skills = json.loads(info.properties[b"skills"].decode())
        except Exception:
            skills = []

        print(f"✨ FOUND NODE → {node_id} @ {ip}:{info.port}, skills={skills}")


def advertiser(zc: Zeroconf):
    global service_info

    ip = get_local_ip()
    props = {
        "id": NODE_ID,
        "skills": json.dumps(SKILLS),
        "metrics": json.dumps(get_metrics()),
    }

    info = ServiceInfo(
        "_echotest._tcp.local.",
        f"{NODE_ID}._echotest._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=PORT,
        properties=props,
        server=f"{NODE_ID}.local.",  # IMPORTANT: match phoneNode pattern
    )

    zc.register_service(info)
    service_info = info

    print(f"📡 ADVERTISING {NODE_ID} on {ip}:{PORT}")

    while not stop_event.is_set():
        # Update metrics
        info.properties[b"metrics"] = json.dumps(get_metrics()).encode()
        try:
            zc.update_service(info)
        except Exception as e:
            print(f"⚠️ update_service failed: {e}")
        time.sleep(3)


if __name__ == "__main__":
    zc = Zeroconf()

    adv_thread = threading.Thread(target=advertiser, args=(zc,), daemon=True)
    adv_thread.start()

    # Optional: this node can also discover others
    ServiceBrowser(zc, "_echotest._tcp.local.", DiscoveryListener())

    print("🔥 Node running, waiting for others… (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping nodeA…")
        stop_event.set()
        time.sleep(0.5)
        try:
            if service_info is not None:
                zc.unregister_service(service_info)
                print("❌ Unregistered service from Zeroconf")
        except Exception as e:
            print(f"Error during unregister_service: {e}")
        finally:
            zc.close()
            print("Zeroconf closed. Bye.")
