"""Golden payloads: the published contract, field for field (G1).

A failure here is a contract change for Telegraf and the web app, not a test
to update.

Run: python -m unittest discover -s tests -t .
"""
import unittest

from gateway.decode import decode
from gateway.payload import to_message_payload, to_payload
from gateway.pdr import CadencePdrTracker
from tests.fixtures import golden
from tests.fixtures import packets as pk

RECEIVED_AT = 1793037396
LABEL = pk.KNOWN_NODE_LABEL


class TestTelemetryGolden(unittest.TestCase):
    """decode() -> the real tracker's first snapshot -> to_payload()."""

    def assertGolden(self, packet, flow, expected):
        pdr = CadencePdrTracker().observe((LABEL, flow), golden.CADENCE[flow],
                                          golden.PDR_WINDOW_SEC, now=0.0)
        payload = to_payload(decode(packet), flow, LABEL, RECEIVED_AT, pdr)
        self.assertEqual(payload, {**expected, "received_at": RECEIVED_AT,
                                   **golden.FIRST_RX_PDR,
                                   "pdr_window_slots": golden.PDR_WINDOW_SLOTS[flow]})

    def test_environment(self):
        self.assertGolden(pk.env_packet(pkt_id=1001), "environment", golden.ENVIRONMENT)

    def test_device(self):
        self.assertGolden(pk.device_packet(pkt_id=1003), "device", golden.DEVICE)

    def test_position(self):
        self.assertGolden(pk.position_packet(pkt_id=1004), "position", golden.POSITION)

    def test_a_flow_without_cadence_publishes_no_pdr_fields(self):
        payload = to_payload(decode(pk.env_packet()), "environment", LABEL, RECEIVED_AT)
        self.assertEqual(payload, {**golden.ENVIRONMENT, "received_at": RECEIVED_AT})


class TestMessageGolden(unittest.TestCase):
    def assertGolden(self, packet, expected):
        payload = to_message_payload(decode(packet), LABEL, RECEIVED_AT)
        self.assertEqual(payload, {**expected, "pkt_id": packet["id"], "received_at": RECEIVED_AT})

    def test_routed(self):
        self.assertGolden(pk.private_packet(pk.pbx_frame(), pkt_id=2001), golden.ROUTED_MESSAGE)

    def test_broadcast(self):
        self.assertGolden(pk.text_packet(pk.broadcast_frame(), pkt_id=2002),
                          golden.BROADCAST_MESSAGE)

    def test_app_text(self):
        self.assertGolden(pk.app_text_packet("¿llegó?", pkt_id=2004), golden.APP_MESSAGE)

    def test_malformed(self):
        self.assertGolden(pk.private_packet(b"\x01\x02\x03", pkt_id=2003),
                          golden.MALFORMED_MESSAGE)


class TestHopsTaken(unittest.TestCase):
    def test_hop_is_hop_start_minus_hop_limit(self):
        for hop_start, hop_limit in ((5, 3), (7, 0), (3, 3), (4, 1)):
            packet = pk.env_packet()
            packet["hopStart"], packet["hopLimit"] = hop_start, hop_limit
            payload = to_payload(decode(packet), "environment", LABEL, RECEIVED_AT)
            self.assertEqual(payload["hop"], hop_start - hop_limit,
                             f"hopStart={hop_start} hopLimit={hop_limit}")


if __name__ == "__main__":
    unittest.main()
