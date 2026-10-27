"""The web container's entry point: python -m monitor."""
import eventlet

eventlet.monkey_patch()          # before anything else opens a socket or a thread

import os  # noqa: E402
import sys  # noqa: E402

from gateway.config import ConfigError  # noqa: E402
from monitor import param  # noqa: E402
from monitor.app import create_app  # noqa: E402
from monitor.utils import InfluxDBConnector, MQTTConnector  # noqa: E402


def main() -> int:
    try:
        cfg = param.from_env()
    except ConfigError as exc:
        print(f"[WEB] ERROR: {exc}", file=sys.stderr)
        return 2
    if not cfg.deployment:
        print("[WEB] WARNING: MESH_DEPLOYMENT is not set: the map shows reported GPS only")

    db = InfluxDBConnector(cfg.db_host, cfg.db_port, cfg.db_username, cfg.db_password,
                           cfg.db_name)
    problem = db.check()
    print(f"[DB] {cfg.db_host}:{cfg.db_port}/{cfg.db_name}: "
          f"{'WARNING: ' + problem + ' — queries answer 503 until it is' if problem else 'OK'}")

    app, socketio = create_app(cfg, db)
    mqtt = MQTTConnector(cfg.broker_address, cfg.broker_port, cfg.client_id,
                         username=cfg.username, password=cfg.password)
    mqtt.socketio = socketio
    mqtt.connect()
    mqtt.loop()                  # the network thread must run before subscribing
    for topic in cfg.subscribe_topics:
        mqtt.subscribe(topic)
    print(f"[WEB] Live feed {cfg.subscribe_topics}; browsers allowed from "
          f"{cfg.allowed_origins or 'the same origin only'}")

    try:
        socketio.run(app, host="0.0.0.0", port=5000,
                     debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
                     use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        mqtt.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
