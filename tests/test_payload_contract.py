"""Regressions on the published payload, ported from the monorepo's
tests/test_mesh_receiver.py. Receiver behaviour (filtering, dedup, PDR,
topics) is ported with the step that owns it.

Run: python -m unittest discover -s tests -t .
"""
import struct
import unittest

from gateway.decode import decode
from gateway.payload import to_message_payload, to_payload
from gateway.pdr import CadencePdrTracker
from tests.fixtures import packets as pk

RECEIVED_AT = 1793037396
PDR_KEYS = {"pdr", "pdr_window", "pdr_window_slots", "pdr_window_filled", "rx_count",
            "missed_est", "missed_now", "early_count", "cadence_violated", "gap_s"}


def _flow(packet, flow):
    return to_payload(decode(packet), flow, pk.KNOWN_NODE_LABEL, RECEIVED_AT)


def _message(packet, **kwargs):
    return to_message_payload(decode(packet), pk.KNOWN_NODE_LABEL, RECEIVED_AT, **kwargs)


class TestPbxIdByteOrder(unittest.TestCase):
    """The PBX docs say little-endian; the firmware and the air say big-endian.

    Routing compares raw bytes, so a wrong order only shows up as wrong numbers,
    and those become InfluxDB tag values that cannot be corrected in place.
    """

    def test_wire_bytes_decode_to_the_registered_handset(self):
        wire = bytes([0x01, 0x07, 0x5B, 0xCD, 0x15])     # +56123456789, big-endian
        payload = _message(pk.text_packet(wire + b"test_all"))
        self.assertEqual(payload["src_id"], "123456789")
        self.assertNotEqual(payload["src_id"], "365779719")    # the little-endian reading


class TestBooleanFieldsArePublishedAsIntegers(unittest.TestCase):
    """Telegraf's JSON parser drops booleans without an error (seen 2026-08-07)."""

    def test_malformed_flag_is_an_int_on_both_paths(self):
        for packet, want in ((pk.private_packet(pk.pbx_frame()), 0),
                             (pk.private_packet(b"\x01\x02"), 1)):
            flag = _message(packet)["malformed"]
            self.assertIs(type(flag), int)
            self.assertEqual(flag, want)

    def test_cadence_violated_is_an_int_on_every_path(self):
        tracker, flow = CadencePdrTracker(), (pk.KNOWN_NODE_LABEL, "device")
        snapshots = [tracker.observe(flow, 120, 3600, now=t) for t in (0.0, 120.0, 130.0)]
        snapshots += [snap for _, snap in tracker.sweep(now=500.0)]
        self.assertEqual([s["cadence_violated"] for s in snapshots], [0, 0, 1, 1])
        for snap in snapshots:
            payload = to_payload(decode(pk.device_packet()), "device", pk.KNOWN_NODE_LABEL,
                                 RECEIVED_AT, snap)
            self.assertIs(type(payload["cadence_violated"]), int)


class TestChannel(unittest.TestCase):
    """The channel index is the only record of which channel a packet rode."""

    def test_absent_channel_key_means_zero_not_none(self):
        packet = pk.device_packet()
        self.assertNotIn("channel", packet)              # as the library delivers channel 0
        self.assertEqual(_flow(packet, "device")["channel"], 0)

    def test_channel_is_carried_on_pbx_messages(self):
        packet = pk.private_packet(pk.pbx_frame())
        packet["channel"] = 1
        self.assertEqual(_message(packet)["channel"], 1)

    def test_channel_survives_a_malformed_frame(self):
        packet = pk.private_packet(b"\x01\x02\x03")
        packet["channel"] = 1
        payload = _message(packet)
        self.assertEqual(payload["malformed"], 1)
        self.assertEqual(payload["channel"], 1)


class TestOmitNotZero(unittest.TestCase):
    """G2: an absent metric is left out; published as 0 it would read as a real zero."""

    def test_missing_humidity_omitted(self):
        payload = _flow(pk.env_packet(include_humidity=False), "environment")
        self.assertIn("temperature", payload)
        self.assertNotIn("humidity", payload)

    def test_missing_temperature_omitted(self):
        packet = pk.env_packet()
        del packet["decoded"]["telemetry"]["environmentMetrics"]["temperature"]
        self.assertNotIn("temperature", _flow(packet, "environment"))

    def test_missing_battery_level_omitted(self):
        packet = pk.device_packet()
        del packet["decoded"]["telemetry"]["deviceMetrics"]["batteryLevel"]
        self.assertNotIn("battery_level", _flow(packet, "device"))

    def test_missing_altitude_omitted(self):
        payload = _flow(pk.position_packet(include_altitude=False), "position")
        self.assertIn("latitude", payload)
        self.assertIn("longitude", payload)
        self.assertNotIn("altitude", payload)

    def test_a_real_zero_is_published(self):
        self.assertEqual(_flow(pk.env_packet(temp=0.0), "environment")["temperature"], 0.0)


class TestProtobufDefaults(unittest.TestCase):
    """The library omits fields equal to zero, so an absent hopLimit or rxSnr is 0.

    Deliberate change from the monorepo, which published hop=None and snr=None
    for these (D1/D2, see tests/test_decode.py). With hop_limit 1, D1 covered
    every relayed packet.
    """

    def test_hop_computed_when_both_fields_present(self):
        packet = pk.env_packet()
        packet["hopStart"], packet["hopLimit"] = 7, 4
        self.assertEqual(_flow(packet, "environment")["hop"], 3)

    def test_absent_hop_limit_means_every_hop_used(self):
        packet = pk.env_packet()
        del packet["hopLimit"]
        self.assertEqual(_flow(packet, "environment")["hop"], packet["hopStart"])

    def test_absent_rx_snr_means_zero_db(self):
        packet = pk.env_packet()
        del packet["rxSnr"]
        self.assertEqual(_flow(packet, "environment")["snr"], 0.0)

    def test_hop_is_none_but_present_when_hop_start_absent(self):
        packet = pk.env_packet()
        del packet["hopStart"]
        payload = _flow(packet, "environment")
        self.assertIn("hop", payload)
        self.assertIsNone(payload["hop"])

    def test_hop_is_none_when_both_absent(self):
        packet = pk.env_packet()
        del packet["hopStart"], packet["hopLimit"]
        self.assertIsNone(_flow(packet, "environment")["hop"])

    def test_explicit_none_hop_start_does_not_crash(self):
        packet = pk.env_packet()
        packet["hopStart"] = None
        self.assertIsNone(_flow(packet, "environment")["hop"])


class TestDeviceTs(unittest.TestCase):
    """A packet without a device time holds the flow's previous device_ts, or
    omits it. Deliberate change from the monorepo, which published the host
    clock there, indistinguishable from the node's (user, 2026-10-26).
    """

    @staticmethod
    def _timeless(**kwargs):
        packet = pk.env_packet()
        del packet["decoded"]["telemetry"]["time"]
        return to_payload(decode(packet), "environment", pk.KNOWN_NODE_LABEL,
                          RECEIVED_AT, **kwargs)

    def test_device_ts_from_packet_time(self):
        self.assertEqual(_flow(pk.env_packet(), "environment")["device_ts"], 1700000000)

    def test_packet_time_wins_over_the_held_value(self):
        payload = to_payload(decode(pk.env_packet()), "environment", pk.KNOWN_NODE_LABEL,
                             RECEIVED_AT, held_device_ts=1600000000)
        self.assertEqual(payload["device_ts"], 1700000000)

    def test_without_packet_time_the_held_value_is_published(self):
        self.assertEqual(self._timeless(held_device_ts=1600000000)["device_ts"], 1600000000)

    def test_without_packet_time_or_held_value_device_ts_is_omitted(self):
        payload = self._timeless()
        self.assertNotIn("device_ts", payload)
        self.assertIn("temperature", payload, "the telemetry itself still publishes")

    def test_the_host_clock_is_never_published_as_device_ts(self):
        self.assertNotEqual(self._timeless().get("device_ts"), RECEIVED_AT)


class TestFlows(unittest.TestCase):
    def test_device_and_environment_in_one_packet_stay_separate(self):
        packet = pk.device_packet()
        packet["decoded"]["telemetry"]["environmentMetrics"] = {"temperature": 20.0}
        device, env = _flow(packet, "device"), _flow(packet, "environment")
        self.assertNotIn("temperature", device)
        self.assertNotIn("battery_level", env)

    def test_asking_for_a_flow_the_packet_lacks_fails_loudly(self):
        with self.assertRaises(ValueError):
            _flow(pk.env_packet(), "device")


class TestPbxMessageFrame(unittest.TestCase):
    """PRIVATE_APP frames from the PBX: [fw_ver][src_id][dst_id][content]."""

    def test_valid_frame_publishes_src_and_dst(self):
        payload = _message(pk.private_packet(pk.pbx_frame()))
        self.assertEqual(payload["src_id"], str(pk.SRC_PHONE))
        self.assertEqual(payload["dst_id"], str(pk.DST_PHONE))
        self.assertEqual(payload["fw_ver"], 1)
        self.assertEqual(payload["malformed"], 0)
        self.assertEqual(payload["content_len"], len(b"hello"))
        self.assertEqual(payload["payload_len"], 9 + len(b"hello"))

    def test_src_and_dst_are_not_the_same_field(self):
        """A copy-paste once assigned src to both, freezing it into the dst_id tag."""
        payload = _message(pk.private_packet(pk.pbx_frame()))
        self.assertNotEqual(payload["src_id"], payload["dst_id"])

    def test_node_id_is_the_relay_not_the_originator(self):
        payload = _message(pk.private_packet(pk.pbx_frame()))
        self.assertEqual(payload["node_id"], pk.KNOWN_NODE_ID)
        self.assertNotEqual(payload["src_id"], payload["node_id"])

    def test_empty_content_is_valid(self):
        payload = _message(pk.private_packet(pk.pbx_frame(content=b"")))
        self.assertEqual(payload["malformed"], 0)
        self.assertEqual(payload["content_len"], 0)

    def test_truncated_frame_reported_as_malformed(self):
        payload = _message(pk.private_packet(b"\x01\x02\x03"))
        self.assertEqual(payload["malformed"], 1)
        self.assertEqual(payload["payload_len"], 3)

    def test_non_bytes_payload_reported_as_malformed(self):
        self.assertEqual(_message(pk.private_packet("not-bytes"))["malformed"], 1)

    def test_unknown_version_reported_as_malformed(self):
        """A proposed v2 adds a seq at offset 9; reading it as v1 would shift every field."""
        frame = struct.pack(">BII", 0x02, pk.SRC_PHONE, pk.DST_PHONE) + b"hello"
        payload = _message(pk.private_packet(frame))
        self.assertEqual(payload["malformed"], 1)
        self.assertNotIn("src_id", payload)

    def test_no_seq_field_is_published(self):
        self.assertNotIn("seq", _message(pk.private_packet(pk.pbx_frame())))

    def test_the_text_is_published(self):
        """User, 2026-10-30: the dashboard shows it and InfluxDB keeps it."""
        payload = _message(pk.private_packet(pk.pbx_frame(content="¿llegó?".encode())))
        self.assertEqual((payload["origin"], payload["text"]), ("pbx", "¿llegó?"))
        self.assertNotIn("content_hex", payload)

    def test_content_that_is_not_utf8_goes_as_hex(self):
        payload = _message(pk.private_packet(pk.pbx_frame(content=b"\xff\xfe")))
        self.assertEqual(payload["content_hex"], "fffe")
        self.assertNotIn("text", payload)

    def test_messages_carry_no_pdr_fields_and_no_device_ts(self):
        """Phone traffic is aperiodic: there is no cadence to measure against."""
        payload = _message(pk.private_packet(pk.pbx_frame()))
        self.assertFalse(PDR_KEYS & set(payload))
        self.assertNotIn("device_ts", payload)

    def test_a_non_pbx_portnum_fails_loudly(self):
        with self.assertRaises(ValueError):
            _message(pk.env_packet())


class TestAppMessage(unittest.TestCase):
    """TEXT_MESSAGE_APP typed in a Meshtastic app: plain text, between nodes.

    Read as a PBX frame, its first letters were a version byte and a phone
    number, and every such message came out "malformed".
    """

    def test_a_broadcast_text_between_nodes(self):
        payload = _message(pk.app_text_packet("hola a todos"))
        self.assertEqual(payload["origin"], "meshtastic")
        self.assertEqual((payload["src_id"], payload["dst_id"]), (pk.KNOWN_NODE_ID, None))
        self.assertEqual((payload["text"], payload["malformed"]), ("hola a todos", 0))
        self.assertNotIn("fw_ver", payload)

    def test_a_direct_message_names_its_node(self):
        payload = _message(pk.app_text_packet("¿me oyes?", to_id="!11223344"))
        self.assertEqual(payload["dst_id"], "!11223344")

    def test_a_frame_of_an_unknown_version_is_not_shown_as_text(self):
        """A control character first is a damaged or future PBX frame, never a text."""
        frame = struct.pack(">BI", 0x02, pk.SRC_PHONE) + b"hello"
        payload = _message(pk.text_packet(frame))
        self.assertEqual(payload["malformed"], 1)
        self.assertNotIn("text", payload)


class TestBroadcastMessageFrame(unittest.TestCase):
    """TEXT_MESSAGE_APP frames: [version][src_id][content], a 5-byte header.

    Read with the 9-byte layout they would lose 4 bytes of content and report
    them as a destination.
    """

    def test_broadcast_frame_publishes_dst_id_as_null(self):
        """G3b: dst_id is a Telegraf tag; omitting it would change the series."""
        payload = _message(pk.text_packet(pk.broadcast_frame()))
        self.assertEqual(payload["src_id"], str(pk.SRC_PHONE))
        self.assertIn("dst_id", payload)
        self.assertIsNone(payload["dst_id"])
        self.assertEqual(payload["malformed"], 0)

    def test_content_offset_uses_the_five_byte_header(self):
        payload = _message(pk.text_packet(pk.broadcast_frame(content=b"hello")))
        self.assertEqual(payload["content_len"], len(b"hello"))
        self.assertEqual(payload["payload_len"], 5 + len(b"hello"))

    def test_header_only_broadcast_frame_is_valid(self):
        payload = _message(pk.text_packet(pk.broadcast_frame(content=b"")))
        self.assertEqual(payload["malformed"], 0)
        self.assertEqual(payload["content_len"], 0)

    def test_four_byte_payload_is_malformed(self):
        payload = _message(pk.text_packet(b"\x01\x02\x03\x04"))
        self.assertEqual(payload["malformed"], 1)
        self.assertEqual(payload["payload_len"], 4)

    def test_portnum_distinguishes_the_two_frame_shapes(self):
        wire = struct.pack(">BII", 1, pk.SRC_PHONE, pk.DST_PHONE)
        routed = _message(pk.private_packet(wire))
        broadcast = _message(pk.text_packet(wire))
        self.assertEqual(routed["content_len"], 0)
        self.assertEqual(routed["dst_id"], str(pk.DST_PHONE))
        self.assertEqual(broadcast["content_len"], 4)
        self.assertIsNone(broadcast["dst_id"])


if __name__ == "__main__":
    unittest.main()
