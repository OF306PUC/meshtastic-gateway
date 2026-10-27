"""The receiver end to end: packet dict -> topics and JSON, with a fake broker
client and fake clocks. Ported from the monorepo's tests/test_mesh_receiver.py
(filtering, malformed input, PDR integration), plus the gateway's own rules.

Run: .venv/bin/python -m unittest discover -s tests -t .
"""
import contextlib
import io
import json
import unittest
from pathlib import Path

from gateway.deployment import Node, load
from gateway.publish import MQTTConnector
from gateway.receiver import Receiver
from tests.fixtures import packets as pk

DEP = load(str(Path(__file__).resolve().parent / "fixtures" / "deployments" / "test-mesh.yaml"))
P1_ID, P1_NUM = "!11223344", 0x11223344
WALL = 1793037396.0
WINDOWS = {"device": 3600, "environment": 3600, "position": 3600}


class _Sent:
    rc = 0


class _Client:
    def __init__(self):
        self.sent = []

    def publish(self, topic, message, qos):
        self.sent.append((topic, json.loads(message)))
        return _Sent()


class _Clock:
    def __init__(self):
        self.wall, self.mono = WALL, 0.0


def _from_p1(packet):
    packet["fromId"], packet["from"] = P1_ID, P1_NUM
    return packet


class ReceiverCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.rx = self.make()

    def make(self, nodes=None):
        conn = MQTTConnector("localhost", "testbed")
        conn.client = self.client = _Client()
        self.clock, self.logs = _Clock(), []
        return Receiver(conn, DEP.known_nodes() if nodes is None else nodes,
                        pdr_window_sec=WINDOWS, my_id=pk.GATEWAY_ID, my_num=pk.GATEWAY_NUM,
                        wall=lambda: self.clock.wall, mono=lambda: self.clock.mono,
                        log=self.logs.append)

    def receive(self, *packets):
        for packet in packets:
            self.rx.on_receive(packet)

    def sent(self, kind):
        return [p for t, p in self.client.sent if t.rsplit("/", 1)[1] == kind]

    def warnings(self, text):
        return [line for line in self.logs if "WARNING" in line and text in line]


class TestFilteringGuards(ReceiverCase):
    def test_unknown_node_is_counted_not_published(self):
        pkt = pk.env_packet()
        pkt["fromId"], pkt["from"] = "!deadbeef", 0xDEADBEEF
        self.receive(pkt, dict(pkt, id=pk.next_pkt_id()))
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.rx.discarded["unknown_sender"], 2)
        self.assertEqual(len(self.warnings("!deadbeef")), 1, "warned once, with G10")

    def test_own_packets_by_id(self):
        pkt = pk.env_packet()
        pkt["fromId"], pkt["from"] = pk.GATEWAY_ID, pk.GATEWAY_NUM
        self.receive(pkt)
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.rx.discarded["own"], 1)

    def test_own_packets_by_num(self):
        pkt = pk.env_packet()
        pkt["fromId"], pkt["from"] = "!aabbccde", pk.GATEWAY_NUM
        self.receive(pkt)
        self.assertEqual(self.client.sent, [])

    def test_duplicate_packet_id_published_once(self):
        shared = pk.next_pkt_id()
        self.receive(pk.env_packet(pkt_id=shared), pk.env_packet(pkt_id=shared))
        self.assertEqual(len(self.sent("environment")), 1)
        self.assertEqual(self.rx.discarded["duplicate"], 1)


class TestMalformedPackets(ReceiverCase):
    def test_nothing_raises_and_everything_is_counted(self):
        nodeinfo = pk.env_packet()
        nodeinfo["decoded"]["portnum"] = "NODEINFO_APP"
        no_decoded = {"fromId": pk.KNOWN_NODE_ID, "from": pk.KNOWN_NODE_NUM, "id": 1}
        self.receive(None, {}, no_decoded, nodeinfo)
        self.assertEqual(self.client.sent, [])
        self.assertEqual(dict(self.rx.errors), {})
        self.assertEqual(self.rx.discarded["empty"], 3)
        self.assertEqual(self.rx.discarded["not_published:other"], 1)


class TestPublishedPayloads(ReceiverCase):
    def test_topics_carry_prefix_label_and_kind(self):
        self.receive(pk.env_packet(), pk.device_packet(), pk.position_packet(),
                     pk.private_packet(pk.pbx_frame()))
        self.assertEqual([t for t, _ in self.client.sent], [
            "testbed/node-1/environment", "testbed/node-1/device",
            "testbed/node-1/position", "testbed/node-1/message"])

    def test_received_at_is_the_wall_clock(self):
        self.receive(pk.env_packet())
        self.assertEqual(self.sent("environment")[0]["received_at"], int(WALL))

    def test_messages_carry_no_pdr_fields(self):
        self.receive(pk.private_packet(pk.pbx_frame()))
        [msg] = self.sent("message")
        self.assertNotIn("pdr", msg)
        self.assertEqual(msg["src_id"], str(pk.SRC_PHONE))


class TestDeviceTsHold(ReceiverCase):
    @staticmethod
    def _timeless(packet, sub="telemetry"):
        packet["decoded"][sub].pop("time")
        return packet

    def test_the_flows_previous_device_ts_is_held(self):
        self.receive(pk.env_packet(), self._timeless(pk.env_packet()))
        self.assertEqual([p["device_ts"] for p in self.sent("environment")],
                         [1700000000, 1700000000])

    def test_nothing_to_hold_means_no_device_ts(self):
        self.receive(pk.env_packet(), self._timeless(pk.position_packet(), "position"))
        self.assertNotIn("device_ts", self.sent("position")[0], "holds are per flow")

    def test_never_the_host_clock(self):
        self.receive(self._timeless(pk.env_packet()))
        self.assertNotIn("device_ts", self.sent("environment")[0])


class TestPdrIntegration(ReceiverCase):
    def test_pdr_fields_present_on_device_payload(self):
        self.receive(pk.device_packet())
        [payload] = self.sent("device")
        for key in ("pdr", "pdr_window", "pdr_window_slots", "rx_count",
                    "missed_est", "early_count", "cadence_violated"):
            self.assertIn(key, payload)
        self.assertIsNone(payload["pdr"], "first packet yields no ratio")
        self.assertEqual(payload["rx_count"], 1)

    def test_no_pdr_when_the_node_declares_no_cadence(self):
        """P1 declares only device: measuring environment would fabricate loss."""
        self.receive(_from_p1(pk.env_packet()), _from_p1(pk.env_packet()))
        payload = self.sent("environment")[0]
        self.assertNotIn("pdr", payload)
        self.assertIn("temperature", payload, "the telemetry itself still publishes")
        self.assertEqual(len(self.warnings("declares no cadence")), 1)

    def test_device_and_env_are_separate_flows(self):
        self.receive(pk.device_packet(), pk.env_packet())
        self.assertEqual(self.sent("device")[0]["rx_count"], 1)
        self.assertEqual(self.sent("environment")[0]["rx_count"], 1)

    def test_reboot_detected_from_falling_uptime(self):
        first, second = pk.device_packet(), pk.device_packet()
        first["decoded"]["telemetry"]["deviceMetrics"]["uptimeSeconds"] = 7200
        second["decoded"]["telemetry"]["deviceMetrics"]["uptimeSeconds"] = 30
        self.receive(first, second)
        self.assertEqual(self.sent("device")[1]["early_count"], 0,
                         "a reboot must restart the cadence grid, not flag an early packet")
        self.assertTrue(any("rebooted" in line for line in self.logs))

    def test_sweep_publishes_losses_for_silent_flows(self):
        self.receive(pk.device_packet())
        self.rx.sweep(now=3.1 * 120)
        [payload] = self.sent("pdr")
        self.assertEqual((payload["node_label"], payload["flow"], payload["source"]),
                         ("node-1", "device", "sweep"))
        self.assertEqual(payload["missed_est"], 2)
        self.assertEqual(payload["received_at"], int(WALL))

    def test_sweep_is_silent_when_nothing_is_overdue(self):
        self.receive(pk.device_packet())
        self.rx.sweep(now=0.0)
        self.assertEqual(self.sent("pdr"), [])

    def test_duplicate_packet_does_not_inflate_pdr(self):
        shared = pk.next_pkt_id()
        self.receive(pk.device_packet(pkt_id=shared), pk.device_packet(pkt_id=shared))
        self.assertEqual(len(self.sent("device")), 1)
        self.assertEqual(self.sent("device")[0]["rx_count"], 1)

    def test_a_broken_cadence_is_warned_once(self):
        self.receive(pk.device_packet())
        self.clock.mono = 10.0
        self.receive(pk.device_packet(), pk.device_packet())
        self.assertEqual(self.sent("device")[-1]["cadence_violated"], 1)
        self.assertEqual(len(self.warnings("inside its 120 s cadence")), 1)


class TestMessageLog(ReceiverCase):
    """The PBX message text goes to the terminal, never to MQTT by default."""

    def messages(self):
        return [line for line in self.logs if line.startswith("[MSG]")]

    def test_routed_message_with_its_text(self):
        self.receive(pk.private_packet(pk.pbx_frame(content=b"hola mundo")))
        [line] = self.messages()
        self.assertIn(f"{pk.SRC_PHONE} -> {pk.DST_PHONE} via node-1 (PRIVATE_APP", line)
        self.assertTrue(line.endswith(': "hola mundo"'), line)

    def test_broadcast_message(self):
        self.receive(pk.text_packet(pk.broadcast_frame(content="¿llegó?".encode())))
        [line] = self.messages()
        self.assertIn(f"{pk.SRC_PHONE} -> broadcast via node-1 (TEXT_MESSAGE_APP", line)
        self.assertTrue(line.endswith(': "¿llegó?"'), line)

    def test_control_characters_cannot_reach_the_terminal(self):
        self.receive(pk.private_packet(pk.pbx_frame(content=b"hi\x1b[31m\n[MSG] forged")))
        [line] = self.messages()
        self.assertNotIn("\x1b", line)
        self.assertNotIn("\n", line)
        self.assertIn(r'"hi\x1b[31m\n[MSG] forged"', line)

    def test_text_that_is_not_utf8_is_shown_in_hex(self):
        self.receive(pk.private_packet(pk.pbx_frame(content=b"\xff\xfe")))
        self.assertIn("<2 B, not UTF-8: fffe>", self.messages()[0])

    def test_a_malformed_frame_is_logged_too(self):
        self.receive(pk.private_packet(b"\x01\x02\x03"))
        [line] = self.messages()
        self.assertIn("malformed frame via node-1 (PRIVATE_APP", line)
        self.assertTrue(line.endswith(": 3 B"), line)

    def test_a_duplicate_is_logged_once(self):
        shared = pk.next_pkt_id()
        self.receive(pk.private_packet(pk.pbx_frame(), pkt_id=shared),
                     pk.private_packet(pk.pbx_frame(), pkt_id=shared))
        self.assertEqual(len(self.messages()), 1)

    def test_the_text_is_still_not_published(self):
        self.receive(pk.private_packet(pk.pbx_frame(content=b"secret")))
        self.assertNotIn("secret", json.dumps(self.sent("message")))


class TestFailsLoudly(ReceiverCase):
    def test_a_label_that_is_no_topic_level_fails_at_start(self):
        bad = {"!0b64122b": Node(ref="N1", name="node 1", function="node",
                                 node_id="!0b64122b", intervals={})}
        with self.assertRaises(ValueError):
            self.make(bad)

    def test_a_failing_packet_is_counted_and_logged_with_its_traceback(self):
        self.receive(pk.env_packet(temp=float("nan")))
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.rx.errors["ValueError"], 1)
        self.assertTrue(any("Traceback" in line for line in self.logs))

    def test_report_accounts_for_every_packet(self):
        dup = pk.next_pkt_id()
        self.receive(pk.env_packet(pkt_id=dup), pk.env_packet(pkt_id=dup), {})
        report = self.rx.report()
        self.assertEqual(report["published"], {"environment": 1})
        self.assertEqual(report["discarded"], {"duplicate": 1, "empty": 1})
        self.assertEqual(report["heard"]["packets"], 3)
        self.assertEqual((report["mqtt_queued"], report["mqtt_dropped"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
