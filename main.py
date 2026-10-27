"""gateway-receiver: the gateway radio over serial -> MQTT. The container runs this file.

Configuration comes from the environment (.env and secrets/gateway.env; see
.env.example) and from deployments/<MESH_DEPLOYMENT>.yaml. It exits non-zero on
anything that would otherwise leave it running without data, so the container
restarts and the log says why.
"""
import json
import signal
import sys
import threading
import time

from pubsub import pub

from gateway import startup
from gateway.config import ConfigError, from_env
from gateway.deployment import DeploymentError, load
from gateway.publish import MQTTConnector
from gateway.receiver import Receiver

REPORT_EVERY_SEC = 600
# Opening the port restarts the radio, which then hands over the packets it held
# in one burst: long enough to cover it, short against any cadence.
STARTUP_SETTLE_SEC = 10


def main() -> int:
    try:
        cfg = from_env()
        dep = load(cfg.deployment)
    except (ConfigError, DeploymentError) as exc:
        print(f"[GW] ERROR: {exc}", file=sys.stderr)
        return 2
    nodes = dep.known_nodes()
    if not nodes:
        print(f"[GW] ERROR: no node in {dep.path} has a node_id; nothing could be published",
              file=sys.stderr)
        return 2

    print(f"[GW] Deployment {dep.name}: {dep.path} sha256={dep.sha256}")
    print("[GW] It must be byte-identical to the platform's copy: compare the sha256 "
          "(G10, deployments/README.md)")
    print(f"[GW] Nodes: {', '.join(f'{n.name}={i}' for i, n in nodes.items())}")
    print(f"[GW] Cadences: { {n.name: dict(n.intervals) for n in nodes.values() if n.intervals} }")
    print(f"[GW] PDR windows (s): {dict(cfg.pdr_window_sec)}; sweep every {cfg.sweep_interval_sec} s")
    print(f"[GW] Publishing {cfg.topic_prefix}/<node>/<kind> to "
          f"{cfg.broker_address}:{cfg.broker_port} as {cfg.client_id}")

    mqtt = MQTTConnector(cfg.broker_address, cfg.topic_prefix, cfg.broker_port,
                         cfg.client_id, cfg.username, cfg.password)
    mqtt.connect()
    mqtt.wait_until_connected()

    import meshtastic.serial_interface
    from meshtastic.protobuf.config_pb2 import Config as RadioConfig

    iface = meshtastic.serial_interface.SerialInterface(devPath=cfg.serial_port)
    me = iface.getMyNodeInfo() or {}
    my_id, my_num = me.get("user", {}).get("id"), me.get("num")
    role = RadioConfig.DeviceConfig.Role.Name(iface.localNode.localConfig.device.role)
    print(f"[GW] Gateway radio: {my_id} (num={my_num}, role={role}) on {cfg.serial_port}")
    for warning in startup.warnings(dep, cfg, my_id, role):
        print(f"[GW] WARNING: {warning}")

    receiver = Receiver(mqtt, nodes, pdr_window_sec=cfg.pdr_window_sec,
                        my_id=my_id, my_num=my_num, settle_sec=STARTUP_SETTLE_SEC)
    lost = threading.Event()

    def on_lost(interface=None):
        lost.set()

    # pypubsub keeps listeners by weak reference: both stay alive in this frame.
    pub.subscribe(receiver.on_receive, "meshtastic.receive")
    pub.subscribe(on_lost, "meshtastic.connection.lost")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print("[GW] Listening.")

    code = 0
    next_sweep = time.monotonic() + cfg.sweep_interval_sec
    next_report = time.monotonic() + REPORT_EVERY_SEC
    try:
        while not lost.is_set():
            time.sleep(1)
            now = time.monotonic()
            if now >= next_sweep:
                next_sweep = now + cfg.sweep_interval_sec
                receiver.sweep(now)
            if now >= next_report:
                next_report = now + REPORT_EVERY_SEC
                print(f"[GW] Report: {json.dumps(receiver.report())}")
        print("[GW] ERROR: lost the serial link to the radio; exiting so the container "
              "restarts", file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        pass
    finally:
        print(f"[GW] Final report: {json.dumps(receiver.report())}")
        iface.close()
        mqtt.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
