"""What the radio hears -> decode -> dedup -> PDR -> publish (docs/design.md §4).

Ported from the monorepo's MeshReceiver, minus the decoder and the payloads.
Time comes from injected clocks: `wall` for received_at (Telegraf's time key),
`mono` for every cadence delta. Nothing is discarded without being counted.
"""
from __future__ import annotations

import collections
import dataclasses
import threading
import time
import traceback
from typing import Callable, Mapping

from gateway.decode import DecodeStats, DecodedPacket, decode
from gateway.deployment import Node
from gateway.decode import NodeInfo
from gateway.deployment import relay_name
from gateway.payload import (MESSAGE_PORTNUMS, destination, meshtastic_text, pbx_frame,
                             relay_node, to_message_payload, to_neighbor_payloads,
                             to_nodeinfo_payload, to_payload)
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


def _described(info: NodeInfo) -> str:
    names = " ".join(_shown(n.encode()) for n in (info.long_name, info.short_name) if n)
    return (f"a {info.hw_model or 'radio with no hardware model'} ({info.role}), "
            f"MAC {info.mac or 'not given'}" + (f", named {names}" if names else ""))


class Receiver:
    def __init__(self, publisher, nodes: Mapping[str, Node], *,
                 pdr_window_sec: Mapping[str, int], my_id: str | None = None,
                 my_num: int | None = None,
                 settle_sec: float = 0.0,
                 neighbor_info_secs: int | None = None,
                 wall: Callable[[], float] = time.time,
                 mono: Callable[[], float] = time.monotonic,
                 log: Callable[[str], None] = print):
        """`publisher` has publish_payload(label, kind, payload) and topic_prefix;
        `nodes` maps node_id -> Node (Deployment.known_nodes()).

        Receptions in the first `settle_sec` are published but not scored for
        PDR: on connection the radio delivers, all at once, the packets it held
        while nothing was connected, and their arrival times say nothing about
        the cadence (seen 2026-10-27: two packets sent 60 s apart, 0.1 s apart
        on arrival, scored as early).

        `neighbor_info_secs` is the file's radio.neighbor_info interval, which
        each node's reports are checked against."""
        for node in nodes.values():            # a label that is no topic level fails now
            topic_for(publisher.topic_prefix, node.name, "device")
        self.publisher = publisher
        self.nodes = dict(nodes)
        self.pdr_window_sec = dict(pdr_window_sec)
        self.my_id, self.my_num = my_id, my_num
        self.neighbor_info_secs = neighbor_info_secs
        self.wall, self.mono, self.log = wall, mono, log

        self.tracker = CadencePdrTracker()
        self.stats = DecodeStats()
        self.discarded: collections.Counter = collections.Counter()
        self.published: collections.Counter = collections.Counter()
        self.errors: collections.Counter = collections.Counter()
        self._seen = collections.deque(maxlen=SEEN_MAX)
        self._uptime: dict[str, int] = {}
        self._last_device_ts: dict[tuple, int] = {}
        self._identities: dict[str, NodeInfo] = {}
        self._neighbor_sets: dict[str, frozenset] = {}
        self._warned: set = set()
        self._lock = threading.Lock()
        self._settle_until = self.mono() + settle_sec
        self.unscored_at_startup = 0

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
            if d.nodeinfo is not None:
                self._introduced(d, None)
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
            self._publish(node.name, "message", to_message_payload(d, node.name, received_at))
            sent = True
        if d.nodeinfo is not None:
            self._introduced(d, node)
            self._publish(node.name, "nodeinfo", to_nodeinfo_payload(d, node.name, received_at))
            sent = True
        if d.neighborinfo is not None:
            self._neighbors_reported(d, node)
            for payload in to_neighbor_payloads(d, node.name, received_at):
                self._publish(node.name, "neighbor", payload)
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
        if now < self._settle_until:
            self.unscored_at_startup += 1
            self._warn(("settling",),
                       f"[PDR] Not scoring receptions until {self._settle_until - now:.0f} s from "
                       f"now: the radio first delivers, at once, the packets it held while "
                       f"nothing was connected. They are published all the same.")
            pdr = {}
        else:
            pdr = self._pdr(node, flow, now)
        return to_payload(d, flow, node.name, received_at, pdr,
                          held_device_ts=self._last_device_ts.get(hold_key))

    def _log_message(self, d: DecodedPacket, node: Node):
        """The message and its text on the terminal, as published: a PBX frame
        between phone numbers, or a Meshtastic app's text between nodes."""
        relay = relay_node(d)
        last = (f", last relay {relay_name(relay, self.nodes.values())}"
                if relay and d.hops_taken else "")
        via = (f"via {node.name} ({d.portnum}, ch {d.channel}, hop {d.hops_taken}{last}, "
               f"rssi {d.rx_rssi}, snr {d.rx_snr})")
        frame = pbx_frame(d)
        text = meshtastic_text(d) if frame is None else None
        if frame is not None:
            self.log(f"[MSG] {frame['src_id']} -> {frame['dst_id'] or 'broadcast'} {via}: "
                     f"{_shown(frame['content'])}")
        elif text is not None:
            self.log(f"[MSG] {d.from_id} -> {destination(d) or 'broadcast'} {via}: "
                     f"{_shown(text.encode())}")
        else:
            self.log(f"[MSG] malformed frame {via}: {d.payload_len or 0} B")

    def _introduced(self, d: DecodedPacket, node: Node | None):
        """What a node says it is, logged when it first says so or changes. For a
        radio missing from the file this is how to tell which one it is; for a
        node in it, a role other than the file's means it was provisioned from
        another file."""
        info = dataclasses.replace(d.nodeinfo, extra={})
        if self._identities.get(d.from_id) == info:
            return
        self._identities[d.from_id] = info
        if node is None:
            self.log(f"[MESH] WARNING: {d.from_id}, not in the deployment file, is "
                     f"{_described(info)}. If it is one of this mesh's radios, its node_id "
                     f"and mac belong in the platform's file — {_G10}")
            return
        self.log(f"[MESH] {node.name} ({d.from_id}) is {_described(info)}")
        if node.role and info.role != node.role:
            self.log(f"[MESH] WARNING: {node.name} runs as {info.role}, but the deployment "
                     f"file says {node.role}: provision it again from the platform, or {_G10}")

    def _neighbors_reported(self, d: DecodedPacket, node: Node):
        """A node's neighbour report, logged when the set of radios it hears
        changes. A neighbour missing from the file is warned once (it may be a
        radio whose own packets never reach the gateway); an interval other than
        the file's means the radio was provisioned from another file."""
        report = d.neighborinfo
        heard = frozenset(n.node_id for n in report.neighbors)
        if self._neighbor_sets.get(node.node_id) != heard:
            self._neighbor_sets[node.node_id] = heard
            listed = ", ".join(f"{self._name(n.node_id)} ({n.snr:.2f} dB)"
                               for n in report.neighbors)
            self.log(f"[MESH] {node.name} hears without a hop: {listed or 'nobody'}")
        for n in report.neighbors:
            if n.node_id not in self.nodes and n.node_id != self.my_id:
                self._warn(("unknown_neighbor", n.node_id),
                           f"[MESH] WARNING: {node.name} hears {n.node_id} (SNR {n.snr:.2f} dB), "
                           f"which is not in the deployment file: a radio of this mesh with no "
                           f"node_id yet, or another mesh nearby — {_G10}")
        if (self.neighbor_info_secs and report.interval_s
                and report.interval_s != self.neighbor_info_secs):
            self._warn(("neighbor_interval", node.ref),
                       f"[MESH] WARNING: {node.name} reports its neighbours every "
                       f"{report.interval_s} s, but the deployment file says "
                       f"{self.neighbor_info_secs} s: provision it again from the platform, "
                       f"or {_G10}")

    def _name(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        return node.name if node else node_id

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
            "pdr_unscored_at_startup": self.unscored_at_startup,
            "unknown_radios": {node_id: _described(info)
                               for node_id, info in self._identities.items()
                               if node_id not in self.nodes},
        }

    def _warn(self, key, message: str):
        if key not in self._warned:
            self._warned.add(key)
            self.log(message)
