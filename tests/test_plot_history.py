"""tools/plot_history.py without a database: queries are faked, figures are real.

Run: .venv/bin/python -m unittest discover -s tests -t .
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import matplotlib

matplotlib.use("Agg")

import pandas as pd  # noqa: E402

from gateway.deployment import load  # noqa: E402
from tools import plot_history as ph  # noqa: E402
from tools import plotstyle  # noqa: E402

DEP = load(str(Path(__file__).resolve().parent / "fixtures" / "deployments" / "test-mesh.yaml"))


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def _frame(field, values, start="2026-10-27 10:00", step="2min", label="node-1"):
    times = pd.date_range(start, periods=len(values), freq=step)
    return pd.DataFrame({"time": times, "node_id": "!0b64122b", "node_label": label,
                         "topic": "t/node-1/device", field: values})


class TestStyles(unittest.TestCase):
    def test_roles_come_from_the_deployment(self):
        styles = plotstyle.node_styles(DEP.nodes)
        self.assertEqual(styles["node-1"]["color"], plotstyle.ROLE_STEPS["node"][0])
        self.assertEqual(styles["P1"]["color"], plotstyle.ROLE_STEPS["pbx"][0])
        self.assertEqual(styles["GW"], plotstyle.NEUTRAL)


class TestQueries(unittest.TestCase):
    def test_every_series_of_a_grouped_query_is_read_with_its_tags(self):
        body = {"results": [{"series": [
            {"tags": {"node_label": "a"}, "columns": ["time", "rssi"], "values": [[1, -80]]},
            {"tags": {"node_label": "b"}, "columns": ["time", "rssi"], "values": [[2, -90]]},
        ]}]}
        with mock.patch.object(ph.requests, "get", return_value=_Response(200, body)):
            rows = ph._query("SELECT ...")
        self.assertEqual(rows, [{"time": 1, "rssi": -80, "node_label": "a"},
                                {"time": 2, "rssi": -90, "node_label": "b"}])

    def test_refused_credentials_say_which(self):
        with mock.patch.object(ph.requests, "get", return_value=_Response(401, {})):
            with self.assertRaisesRegex(RuntimeError, "INFLUXDB_READ_USER"):
                ph._query("SELECT ...")

    def test_a_query_error_is_raised(self):
        body = {"results": [{"error": "database not found"}]}
        with mock.patch.object(ph.requests, "get", return_value=_Response(200, body)):
            with self.assertRaisesRegex(RuntimeError, "database not found"):
                ph._query("SELECT ...")

    def test_labels_are_quoted_in_queries(self):
        self.assertEqual(ph._quote("it's"), "it\\'s")


class TestFigures(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        plotstyle.apply_paper_style()
        self.styles = plotstyle.node_styles(DEP.nodes)

    def across(self, df, field, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            ph.plot_field_across_nodes(field, df, "UTC", self.out.name, 1, self.styles, **kwargs)
        return sorted(p.name for p in Path(self.out.name).iterdir())

    def test_one_field_across_nodes_as_png_and_pdf(self):
        df = _frame("rssi", [-80.0, -82.0, -81.0, -79.0])
        self.assertEqual(self.across(df, "rssi"), ["all-nodes_rssi.png"])
        self.assertIn("all-nodes_rssi.pdf", self.across(df, "rssi", fmt="pdf"))

    def test_a_real_zero_snr_is_plotted(self):
        """0.0 dB is an ordinary reading from this gateway (D2)."""
        self.assertEqual(self.across(_frame("snr", [0.0, 0.0, 0.0]), "snr"), ["all-nodes_snr.png"])

    def test_drop_zeros_is_only_for_monorepo_data(self):
        self.assertEqual(self.across(_frame("snr", [0.0, 0.0, 0.0]), "snr", drop_zeros=True), [])

    def test_per_node_grid(self):
        df = pd.concat([_frame("rssi", [-80.0, -81.0, -82.0]),
                        _frame("temperature", [20.0, 0.0, 21.0]).assign(topic="t/node-1/environment")])
        with contextlib.redirect_stdout(io.StringIO()):
            ph.plot_node("node-1", df, self.styles["node-1"], "UTC", self.out.name, fmt="pdf")
        self.assertTrue((Path(self.out.name) / "node-1_history.pdf").is_file())

    def test_outages_break_the_line(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0],
                      index=pd.to_datetime(["2026-10-27 10:00", "2026-10-27 10:02",
                                            "2026-10-27 10:04", "2026-10-27 14:00"]))
        self.assertEqual(int(ph._break_at_gaps(s).isna().sum()), 1)

    def test_outages_break_the_line_when_two_flows_share_timestamps(self):
        """Found on a live run: device + environment in the same second made the
        median gap zero, and the line was drawn straight across a 30-min outage."""
        stamps = ["10:00", "10:00", "10:02", "10:02", "10:04", "10:04", "10:40", "10:40"]
        s = pd.Series(range(8), dtype=float,
                      index=pd.to_datetime([f"2026-10-27 {t}" for t in stamps]))
        self.assertEqual(int(ph._break_at_gaps(s).isna().sum()), 1)


class TestCommandLine(unittest.TestCase):
    def test_without_the_database_settings_it_exits_and_says_why(self):
        with mock.patch.object(ph, "INFLUX_DB", ""), mock.patch("sys.argv", ["plot_history"]):
            with self.assertRaises(SystemExit) as cm:
                ph.main()
        self.assertIn("INFLUXDB_DB", str(cm.exception))

    def test_field_names_are_validated(self):
        with mock.patch.object(ph, "INFLUX_DB", "db"), \
                mock.patch("sys.argv", ["plot_history", "--fields", 'rssi" FROM x;']):
            with self.assertRaises(SystemExit) as cm:
                ph.main()
        self.assertIn("not a field name", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
