"""Golden tests for decode(): the exact values each packet type must produce.

The values were captured from the previous decoders running on these same
packets, and decode() was checked against those decoders directly over a
271-packet corpus: everything matched except the two protobuf3-default cases
pinned in test_decode.TestProtobufDefaults (meshtastic-platform's
docs/session-log.md, 2026-10-23). Ported with the decoder on 2026-10-26.

Run:
    .venv/bin/python -m unittest discover -s tests -t .
"""
import unittest

from gateway.decode import decode
from tests.fixtures import packets as pk


class TestEnvironmentGolden(unittest.TestCase):
    def test_values(self):
        d = decode(pk.env_packet(pkt_id=1001))
        self.assertEqual(d.kind, "environment")
        self.assertEqual(d.flows, ("environment",))
        self.assertEqual(d.from_id, pk.KNOWN_NODE_ID)
        self.assertEqual(d.from_num, pk.KNOWN_NODE_NUM)
        self.assertEqual(d.packet_id, 1001)
        self.assertEqual(d.portnum, "TELEMETRY_APP")
        self.assertEqual(d.environment.temperature, 22.5)
        self.assertEqual(d.environment.relative_humidity, 55.0)
        self.assertEqual(d.environment.device_ts, 1700000000)
        self.assertEqual((d.rx_rssi, d.rx_snr), (-85, 7.5))
        self.assertEqual((d.hop_start, d.hop_limit, d.hops_taken), (5, 3, 2))
        self.assertEqual(d.channel, 0)
        self.assertIsNone(d.device)
        self.assertIsNone(d.position)

    def test_humidity_absent_is_none_not_zero(self):
        d = decode(pk.env_packet(include_humidity=False, pkt_id=1002))
        self.assertIsNone(d.environment.relative_humidity)
        self.assertEqual(d.environment.temperature, 22.5)


class TestDeviceGolden(unittest.TestCase):
    def test_values(self):
        d = decode(pk.device_packet(pkt_id=1003))
        self.assertEqual(d.kind, "device")
        m = d.device
        self.assertEqual((m.battery_level, m.voltage, m.channel_utilization,
                          m.air_util_tx, m.uptime_seconds),
                         (85, 3.95, 0.12, 0.05, 3600))
        self.assertEqual(m.device_ts, 1700000001)
        self.assertEqual((d.rx_rssi, d.rx_snr, d.hops_taken, d.channel), (-90, 5.0, 2, 0))
        self.assertEqual(m.extra, {})


class TestPositionGolden(unittest.TestCase):
    def test_values(self):
        d = decode(pk.position_packet(pkt_id=1004))
        self.assertEqual(d.kind, "position")
        p = d.position
        self.assertEqual((p.latitude, p.longitude, p.altitude), (-33.4489, -70.6693, 567))
        self.assertEqual(p.device_ts, 1700000002)
        self.assertEqual((d.rx_rssi, d.rx_snr, d.hops_taken, d.channel), (-80, 9.0, 2, 0))

    def test_altitude_absent_is_none_not_zero(self):
        d = decode(pk.position_packet(include_altitude=False, pkt_id=1005))
        self.assertIsNone(d.position.altitude)


class TestHopsTaken(unittest.TestCase):
    """hops_taken = hop_start - hop_limit, computed once, here."""

    def test_varies_with_hop_fields(self):
        for hop_start, hop_limit in ((5, 3), (7, 0), (3, 3), (4, 1)):
            pkt = pk.env_packet()
            pkt["hopStart"], pkt["hopLimit"] = hop_start, hop_limit
            self.assertEqual(decode(pkt).hops_taken, hop_start - hop_limit)


if __name__ == "__main__":
    unittest.main()
