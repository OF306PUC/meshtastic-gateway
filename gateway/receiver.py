"""What the radio hears -> decode -> dedup -> PDR -> publish (docs/design.md §4).

Ported from the monorepo's MeshReceiver, minus the decoder and the payloads.
Time comes from injected clocks: `wall` for received_at (Telegraf's time key),
`mono` for every cadence delta. Nothing is discarded without being counted.
"""
from __future__ import annotations

import collections
import threading
import time
import traceback
from typing import Callable, Mapping

from gateway.decode import DecodeStats, DecodedPacket, decode
from gateway.deployment import Node
from gateway.payload import MESSAGE_PORTNUMS, pbx_frame, to_message_payload, to_payload
from gateway.pdr import CadencePdrTracker
from gateway.publish import topic_for

__all__ = ["Receiver"]

SEEN_MAX = 50
_G10 = "compare this deployment file with the platform's copy (G10, deployments/README.md)"


def _shown(content: bytes) -> str:
    """Message text as one safe terminal line: control characters escaped, so a
    message cannot move the cursor, colour the log or forge another line."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return f"<{len(content)} B, not UTF-8: {content.hex()}>"
    return '"' + "".join(c if c.isprintable() else c.encode("unicode_escape").decode()
                         for c in text) + '"'


class Receiver:
    def __init__(self, publisher, nodes: Mapping[str, Node], *,
                 pdr_window_sec: Mapping[str, int], my_id: str | None = None,
                 my_num: int | None = None, capture_content: bool = False,
                 wall: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic,
                 log: Callable[[str], None] = print):
        """`publisher` has publish_payload(label, kind, payload) and topic_prefix;
        `nodes` maps node_id -> Node (Deployment.known_nodes())."""
        for node in nodes.values():            # a label that is no topic level fails now
            topic_for(publisher.topic_prefix, node.name, "device")
        self.publisher = publisher
        self.nodes = dict(nodes)
        self.pdr_window_sec = dict(pdr_window_sec)
        self.my_id, self.my_num = my_id, my_num
        self.capture_content = capture_content
        self.wall, self.mono, self.log = wall, mono, log

        self.tracker = CadencePdrTracker()
        self.stats = DecodeStats()
        self.discarded: collections.Counter = collections.Counter()
        self.published: collections.Counter = collections.Counter()
        self.errors: collections.Counter = collections.Counter()
        self._seen = collections.deque(maxlen=SEEN_MAX)
        self._uptime: dict[str, int] = {}
        self._last_device_ts: dict[tuple, int] = {}
        self._warned: set = set()
        self._lock = threading.Lock()

    # ── Packets ───────────────────────────────────────────────────────────────

    def on_receive(self, packet, interface=None):
        """pubsub callback for "meshtastic.receive". Never raises: counts and logs."""
        try:
            with self._lock:
                self._receive(packet)
        except Exception as exc:
            self.errors[type(exc).__name__] += 1
            pkt_id = packet.get("id") if isinstance(packet, dict) else None
            self.log(f"[MESH] ERROR processing packet {pkt_id}: {exc!r}\n{traceback.format_exc()}")

    def _receive(self, packet):
        d = decode(packet, known_nodes=self.nodes)
        if ((d.from_id is not None and d.from_id == self.my_id)
                or (d.from_num is not None and d.from_num == self.my_num)):
            self.discarded["own"] += 1
            return
        self.stats.record(d)
        if d.kind in ("encrypted", "empty"):
            self.discarded[d.kind] += 1
            return
        if not d.known:
            self.discarded["unknown_sender"] += 1
            self._warn(("unknown", d.from_id),
                       f"[MESH] WARNING: {d.from_id} is not in the deployment file; its "
                       f"packets are counted, not published — {_G10}")
            return
        if d.packet_id is not None:
            if d.packet_id in self._seen:      # rebroadcast: counting it would inflate the PDR
                self.discarded["duplicate"] += 1
                return
            self._seen.append(d.packet_id)

        node: Node = d.node
        received_at = int(self.wall())
        now = self.mono()
        sent = False
        if d.portnum in MESSAGE_PORTNUMS:
            self._log_message(d, node)
            self._publish(node.name, "message", to_message_payload(
                d, node.name, received_at, capture_content=self.capture_content))
            sent = True
        for flow in d.flows:
            if flow == "device":               # before scoring: a reboot is not a loss
                self._note_uptime(node, d.device.uptime_seconds, now)
            self._publish(node.name, flow, self._flow_payload(d, node, flow, received_at, now))
            sent = True
        if not sent:
            self.discarded[f"not_published:{d.kind}"] += 1

    def _flow_payload(self, d: DecodedPacket, node: Node, flow: str, received_at: int,
                      now: float) -> dict:
        hold_key = (node.node_id, flow)
        device_ts = getattr(d, flow).device_ts
        if device_ts is not None:
            self._last_device_ts[hold_key] = device_ts
        return to_payload(d, flow, node.name, received_at, self._pdr(node, flow, now),
                          held_device_ts=self._last_device_ts.get(hold_key))

    def _log_message(self, d: DecodedPacket, node: Node):
        """The message and its text on the terminal. The text is never published
        unless capture_content: these are real people's messages."""
        via = (f"via {node.name} ({d.portnum}, ch {d.channel}, hop {d.hops_taken}, "
               f"rssi {d.rx_rssi}, snr {d.rx_snr})")
        frame = pbx_frame(d)
        if frame is None:
            self.log(f"[MSG] malformed frame {via}: {d.payload_len or 0} B")
        else:
            self.log(f"[MSG] {frame['src_id']} -> {frame['dst_id'] or 'broadcast'} {via}: "
                     f"{_shown(frame['content'])}")

    def _publish(self, label: str, kind: str, payload: dict):
        self.publisher.publish_payload(label, kind, payload)
        self.published[kind] += 1

    # ── PDR ───────────────────────────────────────────────────────────────────

    def _pdr(self, node: Node, flow: str, now: float) -> dict:
        interval = node.intervals.get(flow)
        if not interval:
            self._warn(("no_cadence", node.ref, flow),
                       f"[PDR] WARNING: {node.name} sends {flow} but the deployment file "
                       f"declares no cadence for it, so it is not measured — {_G10}")
            return {}
        snap = self.tracker.observe((node.name, flow), interval,
                                    self.pdr_window_sec[flow], now)
        if snap["cadence_violated"]:
            self._warn(("early", node.ref, flow),
                       f"[PDR] WARNING: {node.name}/{flow} arrived {snap['gap_s']} s after "
                       f"the previous one, inside its {interval} s cadence: the measurement "
                       f"is invalid until fixed. Usual causes: smart position broadcast "
                       f"on the node, or a cadence that differs from the radio's — {_G10}")
        return snap

    def _note_uptime(self, node: Node, uptime: int | None, now: float):
        """A falling uptimeSeconds is a reboot: re-anchor all of the node's flows."""
        if uptime is None:
            return
        previous = self._uptime.get(node.node_id)
        self._uptime[node.node_id] = uptime
        if previous is None or uptime >= previous:
            return
        self.log(f"[PDR] {node.name} rebooted (uptime {previous}s -> {uptime}s); "
                 f"discarding the downtime gap")
        for kind in node.intervals:
            self.tracker.reanchor((node.name, kind), now)

    def sweep(self, now: float | None = None):
        """Publish the losses charged to flows that have gone quiet."""
        now = self.mono() if now is None else now
        received_at = int(self.wall())
        with self._lock:
            for (label, kind), snap in self.tracker.sweep(now):
                self.log(f"[PDR] {label}/{kind} silent {snap['gap_s']}s "
                         f"(+{snap['missed_now']} missed, pdr={snap['pdr']})")
                self._publish(label, "pdr", {"node_label": label, "flow": kind,
                                             "source": "sweep",    # no packet behind it
                                             "received_at": received_at, **snap})

    # ── Reporting ─────────────────────────────────────────────────────────────

    def report(self) -> dict:
        return {
            "heard": self.stats.as_dict(),
            "published": dict(self.published),
            "discarded": dict(self.discarded),
            "errors": dict(self.errors),
            "mqtt_queued": sum(getattr(self.publisher, "queued", {}).values()),
            "mqtt_dropped": sum(getattr(self.publisher, "dropped", {}).values()),
        }

    def _warn(self, key, message: str):
        if key not in self._warned:
            self._warned.add(key)
            self.log(message)
