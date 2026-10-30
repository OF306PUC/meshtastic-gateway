"""DecodedPacket -> published payload dict. The field-name contract lives here.

Pure: no clock, no I/O. The caller supplies `received_at` (wall clock; Telegraf's
time key) and the PDR snapshot to merge. Telegraf and the web app read these
names, and a renamed field is dropped downstream without an error, so the
names are pinned by tests/test_payload_golden.py.
"""
from __future__ import annotations

import struct
from typing import Any, Mapping

from gateway.decode import DecodedPacket

__all__ = ["MESSAGE_PORTNUMS", "destination", "meshtastic_text", "parse_pbx_frame", "pbx_frame",
           "to_message_payload", "to_payload"]

# PBX frames ride in decoded.payload; the portnum selects the header layout:
#     PRIVATE_APP       [VERSION:1][SRC_ID:4][DST_ID:4][content]   routed
#     TEXT_MESSAGE_APP  [VERSION:1][SRC_ID:4][content]             broadcast
# Ids are BIG-ENDIAN uint32 phone numbers without country code, published in
# decimal to match the PBX log ("+56<id>"). They are not Meshtastic node ids.
_FRAME_HEADERS = {
    "PRIVATE_APP": struct.Struct(">BII"),
    "TEXT_MESSAGE_APP": struct.Struct(">BI"),
}
_FRAME_VERSION = 0x01
_BROADCAST_NUM = 0xFFFFFFFF
MESSAGE_PORTNUMS = tuple(_FRAME_HEADERS)

# (published name, DecodedPacket attribute) per flow. `humidity` is the
# published name for the protobuf's relativeHumidity.
_METRICS = {
    "environment": (("temperature", "temperature"),
                    ("humidity", "relative_humidity")),
    "device": (("battery_level", "battery_level"),
               ("voltage", "voltage"),
               ("channel_util", "channel_utilization"),
               ("air_util_tx", "air_util_tx"),
               ("uptime_seconds", "uptime_seconds")),
    "position": (("latitude", "latitude"),
                 ("longitude", "longitude"),
                 ("altitude", "altitude")),
}


def to_payload(decoded: DecodedPacket, flow: str, label: str, received_at: int,
               pdr: Mapping[str, Any] | None = None, *,
               held_device_ts: int | None = None) -> dict:
    """One telemetry flow of a packet -> its payload, PDR snapshot merged in.

    A packet without a device time publishes `held_device_ts`, the flow's
    previous device_ts that the caller keeps, or no device_ts at all. Never the
    host clock: it would pass for the node's.
    """
    metrics = getattr(decoded, flow) if flow in _METRICS else None
    if metrics is None:
        raise ValueError(f"packet {decoded.packet_id} has no {flow!r} flow "
                         f"(it has {decoded.flows})")
    payload = {
        "node_id": decoded.from_id,
        "node_label": label,
        "rssi": decoded.rx_rssi,
        "snr": decoded.rx_snr,
        "hop": decoded.hops_taken,
        "channel": decoded.channel,
        "received_at": received_at,
    }
    device_ts = metrics.device_ts if metrics.device_ts is not None else held_device_ts
    if device_ts is not None:
        payload["device_ts"] = device_ts
    for name, attr in _METRICS[flow]:
        value = getattr(metrics, attr)
        if value is not None:          # omit, never zero: 0 reads as a real measurement
            payload[name] = value
    payload.update(pdr or {})
    return payload


def to_message_payload(decoded: DecodedPacket, label: str, received_at: int) -> dict:
    """A message -> its payload: a PBX frame, or a text from a Meshtastic app.

    `origin` says which, and what src_id / dst_id are: phone numbers for "pbx",
    node ids for "meshtastic". The text itself is published (user, 2026-10-30:
    the dashboard shows it and InfluxDB keeps it); content that is not UTF-8
    goes as `content_hex`. No device_ts and no PDR: messages have no cadence.
    """
    if decoded.portnum not in _FRAME_HEADERS:
        raise ValueError(f"packet {decoded.packet_id}: portnum {decoded.portnum!r} "
                         f"carries no message")
    payload = {
        "node_id": decoded.from_id,    # the mesh node heard, not the originating phone
        "node_label": label,
        "portnum": decoded.portnum,
        "channel": decoded.channel,
        "pkt_id": decoded.packet_id,
        "payload_len": decoded.payload_len or 0,
        "rssi": decoded.rx_rssi,
        "snr": decoded.rx_snr,
        "hop": decoded.hops_taken,
        "received_at": received_at,
    }
    frame = pbx_frame(decoded)
    if frame is not None:
        payload.update(
            origin="pbx",
            src_id=frame["src_id"],
            dst_id=frame["dst_id"],    # None on broadcast, published as null (a Telegraf tag)
            fw_ver=frame["fw_ver"],
            malformed=0,
            content_len=frame["content_len"],
            **_body(frame["content"]),
        )
        return payload
    text = meshtastic_text(decoded)
    if text is not None:
        payload.update(
            origin="meshtastic",
            src_id=decoded.from_id,
            dst_id=destination(decoded),
            malformed=0,
            content_len=len(text.encode()),
            text=text,
        )
        return payload
    payload["malformed"] = 1           # the only trace a bad frame leaves
    return payload


def meshtastic_text(decoded: DecodedPacket) -> str | None:
    """The text of a message typed in a Meshtastic app; None if it is not one.

    Asked only of a packet that is not a valid PBX frame. A PBX frame starts with
    its version byte, a control character no app puts first: such a packet is a
    damaged or future frame, reported malformed, never shown as text.
    """
    if decoded.portnum != "TEXT_MESSAGE_APP" or decoded.text is None:
        return None
    text = decoded.text.text
    return text if text and text[0] >= " " else None


def destination(decoded: DecodedPacket) -> str | None:
    """The addressed node of a Meshtastic message; None on broadcast (G3b)."""
    if decoded.to_num == _BROADCAST_NUM or decoded.to_id in (None, "^all"):
        return None
    return decoded.to_id


def _body(content: bytes) -> dict:
    try:
        return {"text": content.decode("utf-8")}
    except UnicodeDecodeError:
        return {"content_hex": content.hex()}


def pbx_frame(decoded: DecodedPacket) -> dict | None:
    """The packet's PBX frame (see parse_pbx_frame); None if it carries none or a malformed one."""
    return parse_pbx_frame((decoded.raw.get("decoded") or {}).get("payload"), decoded.portnum)


def parse_pbx_frame(payload, portnum: str) -> dict | None:
    """Unpack a PBX frame with the header its portnum implies; None if malformed.

    The layout comes from the portnum, never from the length: the same 9 bytes
    are a routed header, or a broadcast header plus 4 bytes of content. Any
    VERSION other than 1 is rejected, so a future v2 is reported, not misread.
    """
    header = _FRAME_HEADERS.get(portnum)
    if header is None or not isinstance(payload, (bytes, bytearray)) or len(payload) < header.size:
        return None
    version, src, *dst = header.unpack_from(payload)
    if version != _FRAME_VERSION:
        return None
    return {
        "fw_ver": version,
        "src_id": str(src),
        "dst_id": str(dst[0]) if dst else None,
        "content": bytes(payload[header.size:]),
        "content_len": len(payload) - header.size,
    }
