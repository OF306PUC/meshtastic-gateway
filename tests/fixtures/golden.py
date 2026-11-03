"""The published contract as data: payloads the monorepo's running gateway produced.

Telemetry dicts come from the monorepo's tests/test_decode_golden.py. Message
dicts were captured on 2026-10-26 by running its MeshReceiver on these same
fixtures. `received_at` and `pkt_id` are left to the caller. `relay_node` is the
gateway's own addition (2026-11-02), as are `origin` and `text` before it.
"""
from tests.fixtures import packets as pk

ENVIRONMENT = {
    "node_id": pk.KNOWN_NODE_ID,
    "node_label": pk.KNOWN_NODE_LABEL,
    "temperature": 22.5,
    "humidity": 55.0,
    "rssi": -85,
    "snr": 7.5,
    "hop": 2,
    "relay_node": "44",
    "channel": 0,
    "device_ts": 1700000000,
}

DEVICE = {
    "node_id": pk.KNOWN_NODE_ID,
    "node_label": pk.KNOWN_NODE_LABEL,
    "battery_level": 85,
    "voltage": 3.95,
    "channel_util": 0.12,
    "air_util_tx": 0.05,
    "uptime_seconds": 3600,
    "rssi": -90,
    "snr": 5.0,
    "hop": 2,
    "relay_node": "44",
    "channel": 0,
    "device_ts": 1700000001,
}

POSITION = {
    "node_id": pk.KNOWN_NODE_ID,
    "node_label": pk.KNOWN_NODE_LABEL,
    "latitude": -33.4489,
    "longitude": -70.6693,
    "altitude": 567,
    "rssi": -80,
    "snr": 9.0,
    "hop": 2,
    "relay_node": "44",
    "channel": 0,
    "device_ts": 1700000002,
}

# The cadences and window the telemetry goldens were captured with (the
# monorepo's DEFAULT_INTERVALS and DEFAULT_PDR_WINDOW_SEC).
CADENCE = {"environment": 120, "device": 120, "position": 600}
PDR_WINDOW_SEC = 3600

# The tracker's snapshot on a flow's first reception: no gap yet, so pdr is None.
FIRST_RX_PDR = {
    "pdr": None,
    "pdr_window": 1.0,
    "pdr_window_filled": 1,
    "rx_count": 1,
    "missed_est": 0,
    "missed_now": 0,
    "early_count": 0,
    "cadence_violated": 0,
    "gap_s": None,
}
PDR_WINDOW_SLOTS = {"environment": 30, "device": 30, "position": 6}   # 3600 s / cadence

ROUTED_MESSAGE = {
    "node_id": pk.KNOWN_NODE_ID,
    "node_label": pk.KNOWN_NODE_LABEL,
    "portnum": "PRIVATE_APP",
    "channel": 0,
    "src_id": "123456789",
    "dst_id": "987654321",
    "origin": "pbx",
    "fw_ver": 1,
    "malformed": 0,
    "payload_len": 14,
    "content_len": 5,
    "text": "hello",
    "rssi": -95,
    "snr": 3.5,
    "hop": 1,
    "relay_node": "44",
}

BROADCAST_MESSAGE = {
    **ROUTED_MESSAGE,
    "portnum": "TEXT_MESSAGE_APP",
    "dst_id": None,
    "payload_len": 10,
}

APP_MESSAGE = {
    "node_id": pk.KNOWN_NODE_ID,
    "node_label": pk.KNOWN_NODE_LABEL,
    "portnum": "TEXT_MESSAGE_APP",
    "channel": 0,
    "origin": "meshtastic",
    "src_id": pk.KNOWN_NODE_ID,
    "dst_id": None,
    "malformed": 0,
    "payload_len": 9,
    "content_len": 9,                  # bytes, not characters: 7 of them
    "text": "¿llegó?",
    "rssi": -101,
    "snr": -2.25,
    "hop": 0,
    "relay_node": "2b",
}

NODEINFO = {
    "node_id": pk.KNOWN_NODE_ID,
    "node_label": pk.KNOWN_NODE_LABEL,
    "long_name": "Meshtastic 122b",
    "short_name": "122b",
    "hw_model": "SEEED_SOLAR_NODE",
    "role": "CLIENT",
    "mac": "C1:C8:0B:64:12:2B",
    "rssi": -97,
    "snr": 4.25,
    "hop": 0,
    "relay_node": "2b",
    "channel": 0,
}

NEIGHBORS = [   # one payload per neighbour, in the report's order
    {"node_id": pk.KNOWN_NODE_ID, "node_label": pk.KNOWN_NODE_LABEL, "neighbor_count": 2,
     "interval_s": 14400, "rssi": -104, "snr": -1.5, "hop": 1, "relay_node": "44", "channel": 0,
     "neighbor_id": "!11223344", "neighbor_snr": 6.5},
    {"node_id": pk.KNOWN_NODE_ID, "node_label": pk.KNOWN_NODE_LABEL, "neighbor_count": 2,
     "interval_s": 14400, "rssi": -104, "snr": -1.5, "hop": 1, "relay_node": "44", "channel": 0,
     "neighbor_id": "!deadbeef", "neighbor_snr": -3.25},
]

MALFORMED_MESSAGE = {
    "node_id": pk.KNOWN_NODE_ID,
    "node_label": pk.KNOWN_NODE_LABEL,
    "portnum": "PRIVATE_APP",
    "channel": 0,
    "malformed": 1,
    "payload_len": 3,
    "rssi": -95,
    "snr": 3.5,
    "hop": 1,
    "relay_node": "44",
}
