"""
bathymetry.py  –  depth contours for the dashboard's offline map
================================================================
Fetches a depth grid for one or more boxes and writes its contour lines as
GeoJSON, which the map draws over the basemap without internet:

    python -m tools.bathymetry --bbox -27.50 -109.80 -26.80 -108.90 \\
        --out monitor/static/maps/bathymetry.geojson

A box is SOUTH WEST NORTH EAST in decimal degrees. monitor/static/maps/fetch.sh
runs this with the field sites' boxes.

The grid is GEBCO_2020 (15 arc-seconds, about 450 m), cut out by NOAA's ERDDAP
server. At that spacing a line near the coast is approximate: the contours are
for reading the sea floor around a site, not for navigation, as GEBCO says of
its own grid.
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

import contourpy
import numpy as np
import requests

ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/GEBCO_2020.csv"
SOURCE = "GEBCO Compilation Group (2020) GEBCO 2020 Grid, via NOAA ERDDAP"
LEVELS_M = (100, 200, 500, 1000, 1500, 2000, 2500, 3000)   # depths, positive down
HEADER = "latitude,longitude,elevation"


class BathymetryError(Exception):
    pass


def fetch_csv(south: float, west: float, north: float, east: float, *, get=requests.get) -> str:
    query = f"elevation[({south}):1:({north})][({west}):1:({east})]"
    url = f"{ERDDAP}?{quote(query, safe='():')}"
    try:
        r = get(url, timeout=120)
    except requests.RequestException as exc:
        raise BathymetryError(f"{url}: {exc}") from exc
    if r.status_code != 200:
        raise BathymetryError(f"{url}: HTTP {r.status_code}: {r.text[:200].strip()}")
    return r.text


def parse_csv(text: str):
    """(lats, lons, elevation[lat, lon]) in metres, negative below sea level.

    ERDDAP's CSV is the column names, a row of units, then one cell per row.
    """
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != HEADER:
        raise BathymetryError(f"not an ERDDAP elevation grid: starts {lines[:1]!r}")
    rows = lines[2:]
    if not rows:
        raise BathymetryError("the server returned no grid cells")
    cells = np.array([[float(v) for v in row.split(",")] for row in rows])
    lats, lons = np.unique(cells[:, 0]), np.unique(cells[:, 1])
    if len(lats) * len(lons) != len(cells):
        raise BathymetryError(f"not a full grid: {len(cells)} cells for "
                              f"{len(lats)} x {len(lons)}")
    z = np.full((len(lats), len(lons)), np.nan)
    z[np.searchsorted(lats, cells[:, 0]), np.searchsorted(lons, cells[:, 1])] = cells[:, 2]
    if np.isnan(z).any():
        raise BathymetryError(f"{int(np.isnan(z).sum())} cells without a depth")
    return lats, lons, z


def contours(lats, lons, z, levels_m=LEVELS_M) -> list[dict]:
    """One GeoJSON LineString per contour line, coordinates [lon, lat]."""
    gen = contourpy.contour_generator(lons, lats, z, line_type=contourpy.LineType.Separate)
    return [{"type": "Feature",
             "properties": {"depth_m": depth},
             "geometry": {"type": "LineString", "coordinates": np.round(line, 5).tolist()}}
            for depth in levels_m
            for line in gen.lines(-depth)
            if len(line) >= 2]


def main(argv=None, *, get=requests.get) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bbox", nargs=4, type=float, action="append", required=True,
                        metavar=("SOUTH", "WEST", "NORTH", "EAST"))
    parser.add_argument("--out", required=True, metavar="FILE.geojson")
    args = parser.parse_args(argv)

    features = []
    for south, west, north, east in args.bbox:
        box = f"{south} {west} {north} {east}"
        if not (south < north and west < east):
            sys.exit(f"bbox {box}: expected SOUTH WEST NORTH EAST")
        try:
            lats, lons, z = parse_csv(fetch_csv(south, west, north, east, get=get))
        except BathymetryError as exc:
            sys.exit(f"bbox {box}: {exc}")
        found = contours(lats, lons, z)
        if not found:
            sys.exit(f"bbox {box}: no depth reaches {LEVELS_M[0]} m — is the box at sea?")
        deepest = int(-z.min())
        print(f"bbox {box}: {len(lats)} x {len(lons)} cells, deepest {deepest} m, "
              f"{len(found)} lines")
        features += found

    out = Path(args.out)
    out.write_text(json.dumps({"type": "FeatureCollection", "source": SOURCE,
                               "features": features}, separators=(",", ":")))
    print(f"{out}: {len(features)} lines, {out.stat().st_size // 1024} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
