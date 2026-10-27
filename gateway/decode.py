"""Turn one received packet into a clean, typed record. Nothing else.

The gateway's own decoder, forked from meshtastic-platform's decode/ on
2026-10-26 so the gateway can adapt it to its needs (user decision). The two
copies are not kept in sync.

When a radio hears a packet, the meshtastic library hands the program a nested
dict (it calls it a MeshPacket). Its shape depends on the packet type, its keys
are camelCase, and fields whose value is zero are simply missing. decode()
reads that dict once and returns a DecodedPacket:

    raw dict from the library                      DecodedPacket
    ───────────────────────────────────────────    ─────────────────────────────
    {"fromId": "!1234abcd",                        from_id      = "!1234abcd"
     "rxRssi": -85, "rxSnr": 7.5,                  rx_rssi      = -85, rx_snr = 7.5
     "hopStart": 3,                (hopLimit       hop_limit    = 0
                                    missing = 0)   hops_taken   = 3
     "decoded": {"portnum": "TELEMETRY_APP",       kind         = "environment"
       "telemetry": {"time": 1700000000,           environment.temperature       = 22.5
         "environmentMetrics":                     environment.relative_humidity = 55.0
           {"temperature": 22.5,                   environment.device_ts         = 1700000000
            "relativeHumidity": 55.0}}}}           node         = the registry entry for !1234abcd

What it does, concretely:
  * says what KIND of packet it is: device, environment, position (the
    periodic flows), text, private (PRIVATE_APP, portnum 256: an application's
    own payload, kept opaque — only its size is read; gateway.payload parses
    the PBX frame),
    telemetry (a variant not mapped here), other (any other app), encrypted
    (heard but not decryptable: another key or another mesh), empty;
  * pulls out the link measurements (RSSI, SNR), the hop count and the channel;
  * fills in zeros the library left out where zero is a real value — channel
    0, a hop limit used up (0), an SNR of exactly 0.0 dB — and leaves real
    metrics (battery, temperature...) None when absent, never a fake 0;
  * attaches the sender's registry entry when the caller passes known_nodes.

What it does NOT do: read the clock, drop duplicates, filter unknown senders,
print, write or publish. Those are the caller's decisions (the receiver).
So the same packet always gives the same result, and it is tested
with plain dicts instead of a radio. Anything it does not map stays available
in `raw`, and DecodeStats counts it, so nothing disappears silently.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "FLOW_KINDS", "DecodedPacket", "DecodeStats", "DeviceMetrics",
    "EnvironmentMetrics", "Position", "TextMessage", "decode",
]

# Periodic broadcast flows. One flow per (node, kind); each has its own
# cadence in the deployment registry, and the gap estimator measures against it.
FLOW_KINDS = ("device", "environment", "position")

# Keys the library adds that mirror the parsed protobuf; never "unknown fields".
_MIRROR_KEYS = {"raw"}


@dataclass(frozen=True)
class DeviceMetrics:
    battery_level: int | None
    voltage: float | None
    channel_utilization: float | None
    air_util_tx: float | None
    uptime_seconds: int | None
    device_ts: int | None              # telemetry.time, the node's clock
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EnvironmentMetrics:
    temperature: float | None
    relative_humidity: float | None
    device_ts: int | None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Position:
    latitude: float | None
    longitude: float | None
    altitude: int | None
    device_ts: int | None              # position.time, the node's clock
    precision_bits: int | None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextMessage:
    text: str | None                   # None when the payload is not UTF-8


@dataclass(frozen=True)
class DecodedPacket:
    # Envelope, common to every packet.
    from_id: str | None
    from_num: int | None
    to_id: str | None
    to_num: int | None
    packet_id: int | None
    rx_rssi: int | None
    rx_snr: float | None
    hop_start: int | None
    hop_limit: int | None
    hops_taken: int | None
    channel: int | None                # channel INDEX, not the on-air hash
    portnum: str | None
    payload_len: int | None            # bytes of application payload, when decoded
    rx_time: int | None                # receiving radio's clock, if it has one
    relay_node: int | None             # low byte of the last relayer's node num

    kind: str
    node: Any = None                   # known_nodes[from_id], if supplied
    device: DeviceMetrics | None = None
    environment: EnvironmentMetrics | None = None
    position: Position | None = None
    text: TextMessage | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def flows(self) -> tuple[str, ...]:
        """The periodic flows this packet is a reception of, in FLOW_KINDS order."""
        present = {"device": self.device, "environment": self.environment,
                   "position": self.position}
        return tuple(k for k in FLOW_KINDS if present[k] is not None)

    @property
    def known(self) -> bool:
        return self.node is not None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _int_or_none(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _extra(src: Mapping[str, Any], mapped: set[str]) -> dict[str, Any]:
    """Fields this decoder does not map, kept so a new firmware field is visible."""
    return {k: v for k, v in src.items() if k not in mapped and k not in _MIRROR_KEYS}


def _device(telem: Mapping[str, Any]) -> DeviceMetrics | None:
    dm = telem.get("deviceMetrics") or {}
    if not dm:
        return None
    return DeviceMetrics(
        battery_level=dm.get("batteryLevel"),
        voltage=dm.get("voltage"),
        channel_utilization=dm.get("channelUtilization"),
        air_util_tx=dm.get("airUtilTx"),
        uptime_seconds=dm.get("uptimeSeconds"),
        device_ts=telem.get("time"),
        extra=_extra(dm, {"batteryLevel", "voltage", "channelUtilization",
                          "airUtilTx", "uptimeSeconds"}),
    )


def _environment(telem: Mapping[str, Any]) -> EnvironmentMetrics | None:
    em = telem.get("environmentMetrics") or {}
    if not em:
        return None
    return EnvironmentMetrics(
        temperature=em.get("temperature"),
        relative_humidity=em.get("relativeHumidity"),
        device_ts=telem.get("time"),
        extra=_extra(em, {"temperature", "relativeHumidity"}),
    )


def _position(pos: Mapping[str, Any]) -> Position:
    # Emitted even when empty: a POSITION_APP packet is a reception of the
    # position flow whatever it carries, and the estimators count it as one.
    return Position(
        latitude=pos.get("latitude"),
        longitude=pos.get("longitude"),
        altitude=pos.get("altitude"),
        device_ts=pos.get("time"),
        precision_bits=pos.get("precisionBits"),
        extra=_extra(pos, {"latitude", "longitude", "latitudeI", "longitudeI",
                           "altitude", "time", "precisionBits"}),
    )


def _text(decoded: Mapping[str, Any]) -> TextMessage:
    payload = decoded.get("payload")
    text = decoded.get("text")
    if not isinstance(text, str) and isinstance(payload, (bytes, bytearray)):
        try:
            text = bytes(payload).decode("utf-8")
        except UnicodeDecodeError:
            text = None
    return TextMessage(text=text if isinstance(text, str) else None)


def _payload_len(payload) -> int | None:
    if payload is None:
        return None
    try:
        return len(payload)
    except TypeError:
        return None


# ── Entry point ───────────────────────────────────────────────────────────────

def decode(packet: Mapping[str, Any] | None, *,
           known_nodes: Mapping[str, Any] | None = None) -> DecodedPacket:
    """Library packet dict -> DecodedPacket. No side effects, same input same output.

    `known_nodes` maps node_id -> whatever the caller wants attached as
    `decoded.node` (normally the registry's Node). Unknown senders still decode;
    filtering them is the caller's decision.
    """
    packet = packet or {}

    hop_start = _int_or_none(packet.get("hopStart"))
    hop_limit = _int_or_none(packet.get("hopLimit"))
    if hop_start is not None and hop_limit is None:
        hop_limit = 0                  # omitted because it is zero: every hop was used
    hops_taken = (hop_start - hop_limit
                  if hop_start is not None and hop_limit is not None else None)

    rx_rssi = packet.get("rxRssi")
    rx_snr = packet.get("rxSnr")
    if rx_snr is None and rx_rssi is not None:
        rx_snr = 0.0                   # omitted because it is zero: SNR measured as 0.0 dB

    decoded = packet.get("decoded")
    envelope = dict(
        from_id=packet.get("fromId"),
        from_num=packet.get("from"),
        to_id=packet.get("toId"),
        to_num=packet.get("to"),
        packet_id=packet.get("id"),
        rx_rssi=rx_rssi,
        rx_snr=rx_snr,
        hop_start=hop_start,
        hop_limit=hop_limit,
        hops_taken=hops_taken,
        channel=packet.get("channel", 0),
        payload_len=_payload_len(decoded.get("payload")) if isinstance(decoded, Mapping) else None,
        rx_time=packet.get("rxTime"),
        relay_node=packet.get("relayNode"),
        node=(known_nodes or {}).get(packet.get("fromId")),
        raw=packet,
    )

    if not isinstance(decoded, Mapping):
        kind = "encrypted" if "encrypted" in packet else "empty"
        return DecodedPacket(portnum=None, kind=kind, **envelope)

    portnum = decoded.get("portnum")
    parts: dict[str, Any] = {}

    if portnum == "TELEMETRY_APP":
        telem = decoded.get("telemetry") or {}
        parts["device"] = _device(telem)
        parts["environment"] = _environment(telem)
        if parts["device"] is not None:
            kind = "device"
        elif parts["environment"] is not None:
            kind = "environment"
        else:
            kind = "telemetry"         # a variant this decoder does not map
    elif portnum == "POSITION_APP":
        parts["position"] = _position(decoded.get("position") or {})
        kind = "position"
    elif portnum == "TEXT_MESSAGE_APP":
        parts["text"] = _text(decoded)
        kind = "text"
    elif portnum == "PRIVATE_APP":
        kind = "private"               # an application's own format: opaque here
    else:
        kind = "other"

    return DecodedPacket(portnum=portnum, kind=kind, **envelope, **parts)


# ── Counters ──────────────────────────────────────────────────────────────────

@dataclass
class DecodeStats:
    """What was heard and what could not be mapped.

    decode() is pure, so it cannot count; the caller feeds every result here
    and reports it, instead of discarding what it did not understand quietly.
    """
    packets: int = 0
    by_kind: Counter = field(default_factory=Counter)
    unknown_portnum: Counter = field(default_factory=Counter)
    unhandled_telemetry: Counter = field(default_factory=Counter)
    unknown_sender: Counter = field(default_factory=Counter)

    def record(self, d: DecodedPacket, *, sender_known: bool | None = None) -> None:
        self.packets += 1
        self.by_kind[d.kind] += 1
        if d.kind == "other":
            self.unknown_portnum[str(d.portnum)] += 1
        elif d.kind == "telemetry":
            telem = (d.raw.get("decoded") or {}).get("telemetry") or {}
            variants = [k for k in telem if k not in ("time", *_MIRROR_KEYS)]
            for v in variants or ["<empty>"]:
                self.unhandled_telemetry[v] += 1
        known = d.known if sender_known is None else sender_known
        if not known and d.from_id is not None:
            self.unknown_sender[d.from_id] += 1

    def as_dict(self) -> dict:
        return {
            "packets": self.packets,
            "by_kind": dict(self.by_kind),
            "unknown_portnum": dict(self.unknown_portnum),
            "unhandled_telemetry": dict(self.unhandled_telemetry),
            "unknown_sender": dict(self.unknown_sender),
        }
