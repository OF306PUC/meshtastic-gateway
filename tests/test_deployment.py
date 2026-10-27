"""The gateway's deployment reader: the platform's semantics on the fields it reads."""
import hashlib
import tempfile
import textwrap
import unittest
from pathlib import Path

from gateway.deployment import (ENV_DEPLOYMENT, ENV_DEPLOYMENTS_DIR, DeploymentError, load)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "deployments"
TEST_MESH = FIXTURES / "test-mesh.yaml"

NODE = """
  - ref: {ref}
    function: node
    node_id: "{node_id}"
    intervals: {intervals}
"""


def _write(directory: str, name: str, nodes: str, meta_extra: str = "") -> Path:
    path = Path(directory) / f"{name}.yaml"
    path.write_text(f"meta:\n  deployment: {name}\n{meta_extra}radio: {{}}\nnodes:\n"
                    + textwrap.dedent(nodes))
    return path


class TestLoad(unittest.TestCase):
    def test_reads_the_fixture(self):
        dep = load(str(TEST_MESH))
        self.assertEqual(dep.name, "test-mesh")
        self.assertEqual([n.ref for n in dep.nodes], ["N1", "P1", "GW", "R1"])

    def test_sha256_is_the_hash_of_the_bytes(self):
        """The same hash the platform records, so both copies can be compared (G10)."""
        self.assertEqual(load(str(TEST_MESH)).sha256,
                         hashlib.sha256(TEST_MESH.read_bytes()).hexdigest())

    def test_published_name_is_label_or_ref(self):
        names = {n.ref: n.name for n in load(str(TEST_MESH)).nodes}
        self.assertEqual(names["N1"], "node-1")
        self.assertEqual(names["P1"], "P1")

    def test_known_nodes_are_those_with_a_node_id(self):
        known = load(str(TEST_MESH)).known_nodes()
        self.assertEqual(sorted(n.ref for n in known.values()), ["GW", "N1", "P1"])
        self.assertEqual(known["!0b64122b"].ref, "N1")

    def test_absent_flow_is_not_emitted(self):
        p1 = load(str(TEST_MESH)).known_nodes()["!11223344"]
        self.assertEqual(dict(p1.intervals), {"device": 900})

    def test_by_name_from_the_environment(self):
        env = {ENV_DEPLOYMENT: "test-mesh", ENV_DEPLOYMENTS_DIR: str(FIXTURES)}
        self.assertEqual(load(environ=env).name, "test-mesh")

    def test_nothing_defaults(self):
        with self.assertRaisesRegex(DeploymentError, ENV_DEPLOYMENT):
            load(environ={})

    def test_unknown_name_lists_what_exists(self):
        env = {ENV_DEPLOYMENTS_DIR: str(FIXTURES)}
        with self.assertRaisesRegex(DeploymentError, "available in .*: test-mesh"):
            load("nope", environ=env)


class TestCadenceScale(unittest.TestCase):
    def test_cadences_are_divided(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "bench", NODE.format(ref="N1", node_id="!0b64122b",
                                                  intervals="{device: 120, position: 600}"),
                          "  cadence_scale: 4\n")
            self.assertEqual(dict(load(str(path)).nodes[0].intervals),
                             {"device": 30, "position": 150})

    def test_a_cadence_that_does_not_divide_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "bench", NODE.format(ref="N1", node_id="!0b64122b",
                                                  intervals="{device: 100}"),
                          "  cadence_scale: 3\n")
            with self.assertRaisesRegex(DeploymentError, "not divisible"):
                load(str(path))


class TestSurveyed(unittest.TestCase):
    """site.surveyed, read for the dashboard's map with the platform's rules."""

    def setUp(self):
        self.nodes = {n.ref: n for n in load(str(TEST_MESH)).nodes}

    def test_a_surveyed_position(self):
        s = self.nodes["N1"].surveyed
        self.assertEqual((s.lat, s.lon, s.alt_m), (-27.1127, -109.3497, 120.5))

    def test_the_planned_desk_position_is_never_read(self):
        self.assertNotEqual((self.nodes["N1"].surveyed.lat, self.nodes["N1"].surveyed.lon),
                            (-27.0, -109.0))

    def test_an_all_null_template_block_is_not_surveyed_yet(self):
        self.assertIsNone(self.nodes["P1"].surveyed)
        self.assertIsNone(self.nodes["GW"].surveyed)          # no site block at all

    def test_bad_surveyed_blocks(self):
        for block, pattern in (("{lat: -27.1, lon: null}", "a number is required"),
                               ("{lat: 0, lon: -109.3}", "looks unset"),
                               ("{lat: -127.1, lon: -109.3}", "out of range"),
                               ("{lat: true, lon: -109.3}", "a number is required"),
                               ("{lat: -27.1, lon: -109.3, alt_m: high}", "alt_m"),
                               ("{}", "a number is required")):
            with self.subTest(block=block), tempfile.TemporaryDirectory() as d:
                nodes = (NODE.format(ref="N1", node_id="!0b64122b", intervals="{}")
                         + f"    site: {{surveyed: {block}}}\n")
                with self.assertRaisesRegex(DeploymentError, pattern):
                    load(str(_write(d, "mesh", nodes)))


class TestStrictOnWhatItReads(unittest.TestCase):
    def assertRejected(self, nodes: str, pattern: str, meta_extra: str = "", name="mesh"):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, name, nodes, meta_extra)
            with self.assertRaisesRegex(DeploymentError, pattern):
                load(str(path))

    def test_a_flow_must_be_absent_not_null_or_zero(self):
        for value in ("null", "0"):
            with self.subTest(value=value):
                self.assertRejected(NODE.format(ref="N1", node_id="!0b64122b",
                                                intervals=f"{{environment: {value}}}"),
                                    "must be ABSENT")

    def test_bad_interval_values(self):
        for intervals, pattern in (("{device: -5}", "positive int"),
                                   ("{device: '120'}", "positive int"),
                                   ("{env: 120}", "unknown flow kind"),
                                   ("null", "expected a mapping")):
            with self.subTest(intervals=intervals):
                self.assertRejected(NODE.format(ref="N1", node_id="!0b64122b",
                                                intervals=intervals), pattern)

    def test_bad_node_id(self):
        self.assertRejected(NODE.format(ref="N1", node_id="!0B64122B", intervals="{}"),
                            "lowercase hex")

    def test_unquoted_node_id_gets_a_hint(self):
        nodes = "  - {ref: N1, function: node, node_id: !0b64122b, intervals: {}}\n"
        self.assertRejected(nodes, "quote it")

    def test_duplicates_would_merge_two_nodes(self):
        two = (NODE.format(ref="N1", node_id="!0b64122b", intervals="{}")
               + NODE.format(ref="N2", node_id="!0b64122b", intervals="{}"))
        self.assertRejected(two, "duplicate node_id")
        named = (NODE.format(ref="N1", node_id="!00000001", intervals="{}")
                 + "    label: N2\n" + NODE.format(ref="N2", node_id="!00000002", intervals="{}"))
        self.assertRejected(named, r"duplicate published name")

    def test_meta_deployment_must_match_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "mesh", NODE.format(ref="N1", node_id="!0b64122b", intervals="{}"))
            path.rename(Path(d) / "other.yaml")
            with self.assertRaisesRegex(DeploymentError, "but the file is other.yaml"):
                load(str(Path(d) / "other.yaml"))

    def test_every_problem_is_reported_at_once(self):
        nodes = (NODE.format(ref="N1", node_id="bad", intervals="{device: 0}")
                 + "  - {ref: N2}\n")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(DeploymentError) as cm:
                load(str(_write(d, "mesh", nodes)))
        self.assertGreaterEqual(len(cm.exception.problems), 4)


if __name__ == "__main__":
    unittest.main()
