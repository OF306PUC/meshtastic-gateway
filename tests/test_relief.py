"""tools/relief.py without a server: the grid is synthetic, the contours real.

Run: .venv/bin/python -m unittest discover -s tests -t .
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools import relief as rl

LATS = np.round(np.arange(-27.30, -27.00 + 1e-9, 0.01), 2)
LONS = np.round(np.arange(-109.60, -109.20 + 1e-9, 0.01), 2)


def _cone_csv(peak_m=480.0, slope_m_per_deg=20000.0, centre=(-27.15, -109.40)):
    """An island: elevation falls off linearly with distance from the centre,
    from the summit down past the shore to the sea floor."""
    rows = [rl.HEADER, "degrees_north,degrees_east,m"]
    for lat in LATS:
        for lon in LONS:
            r = np.hypot(lat - centre[0], lon - centre[1])
            rows.append(f"{lat},{lon},{peak_m - slope_m_per_deg * r:.1f}")
    return "\n".join(rows) + "\n"


class _Response:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


class TestParse(unittest.TestCase):
    def test_cells_land_where_their_coordinates_say(self):
        lats, lons, z = rl.parse_csv(_cone_csv())
        self.assertEqual(z.shape, (len(LATS), len(LONS)))
        self.assertTrue(np.all(np.diff(lats) > 0) and np.all(np.diff(lons) > 0))
        i, j = np.searchsorted(lats, -27.15), np.searchsorted(lons, -109.40)
        self.assertEqual(z[i, j], 480.0)
        self.assertEqual(z.argmax(), i * len(lons) + j)

    def test_refuses_what_is_not_a_full_grid(self):
        cases = {
            "not an ERDDAP elevation grid": "<html>Service unavailable</html>",
            "no grid cells": f"{rl.HEADER}\ndegrees_north,degrees_east,m\n",
            "not a full grid": "\n".join(_cone_csv().splitlines()[:-1]),
            "cells without an elevation": _cone_csv().replace(",480.0", ",NaN"),
        }
        for why, text in cases.items():
            with self.subTest(why), self.assertRaisesRegex(rl.ReliefError, why):
                rl.parse_csv(text)


class TestContours(unittest.TestCase):
    def test_lines_circle_the_island_at_the_right_height(self):
        lats, lons, z = rl.parse_csv(_cone_csv())
        levels = (-2000, -1000, 100, 400)
        features = rl.contours(lats, lons, z, levels_m=levels)
        self.assertEqual([f["properties"]["elevation_m"] for f in features], list(levels))
        for f, level in zip(features, levels):
            coords = np.array(f["geometry"]["coordinates"])
            self.assertEqual(f["geometry"]["type"], "LineString")
            np.testing.assert_allclose(coords[0], coords[-1])      # closed around the island
            lon, lat = coords[:, 0], coords[:, 1]                  # GeoJSON order
            radius = np.hypot(lat + 27.15, lon + 109.40)
            np.testing.assert_allclose(radius, (480 - level) / 20000, atol=0.002)

    def test_a_level_the_grid_never_reaches_gives_no_line(self):
        lats, lons, z = rl.parse_csv(_cone_csv())
        self.assertEqual(rl.contours(lats, lons, z, levels_m=(-9000, 500)), [])


class TestMain(unittest.TestCase):
    def run_main(self, argv, response):
        urls = []

        def get(url, timeout):
            urls.append(url)
            return response

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rl.main(argv, get=get)
        return code, urls, out.getvalue()

    def test_writes_geojson_for_the_box_it_asked_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.geojson"
            code, urls, out = self.run_main(
                ["--bbox", "-27.30", "-109.60", "-27.00", "-109.20", "--out", str(path)],
                _Response(200, _cone_csv()))
            self.assertEqual(code, 0)
            self.assertEqual(len(urls), 1)
            self.assertIn("elevation%5B(-27.3):1:(-27.0)%5D%5B(-109.6):1:(-109.2)%5D", urls[0])
            data = json.loads(path.read_text())
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertIn("GEBCO", data["source"])
        self.assertEqual({f["properties"]["elevation_m"] for f in data["features"]},
                         {level for level in rl.LEVELS_M if level < 480})
        self.assertIn("lines", out)

    def test_fails_loudly(self):
        cases = {
            "HTTP 503": _Response(503, "Service Temporarily Unavailable"),
            "no contour level crossed": _Response(200, _cone_csv(peak_m=20.0, slope_m_per_deg=0.0)),
        }
        for why, response in cases.items():
            with self.subTest(why), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "b.geojson"
                with self.assertRaisesRegex(SystemExit, why):
                    self.run_main(["--bbox", "-27.30", "-109.60", "-27.00", "-109.20",
                                   "--out", str(path)], response)
                self.assertFalse(path.exists())

    def test_refuses_a_box_in_the_wrong_order(self):
        with self.assertRaisesRegex(SystemExit, "SOUTH WEST NORTH EAST"):
            self.run_main(["--bbox", "-27.00", "-109.60", "-27.30", "-109.20", "--out", "x"],
                          _Response(200, _cone_csv()))


if __name__ == "__main__":
    unittest.main()
