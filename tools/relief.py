"""
relief.py  –  elevation and depth contours for the dashboard's offline map
=========================================================================
Fetches a terrain grid for one or more boxes and writes its contour lines, land
and sea, as GeoJSON, which the map draws over the basemap without internet:

    python -m tools.relief --bbox -27.31 -109.56 -26.95 -109.11 \\
        --out monitor/static/maps/relief.geojson

A box is SOUTH WEST NORTH EAST in decimal degrees. monitor/static/maps/fetch.sh
runs this with the field sites' boxes.

The grid is GEBCO_2020 (15 arc-seconds, about 450 m), cut out by NOAA's ERDDAP
server: one grid for land and sea, elevation positive up. At that spacing a
line is approximate, and peaks come out a few tens of metres low: the contours
are for reading the terrain around a site, not for navigation or surveying,
as GEBCO says of its own grid. The coastline itself is the basemap's.
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
# Metres, positive above sea level. Land every 50 m up to Rapa Nui's summits
# (Terevaka, 507 m), then wider; the sea down to 2000 m, where the island's
# slopes meet the ocean floor.
LEVELS_M = (-2000, -1500, -1000, -500, -200, -100, 50, 100, 150, 200, 300, 400, 500)
HEADER = "latitude,longitude,elevation"


class ReliefError(Exception):
    pass


def fetch_csv(south: float, west: float, north: float, east: float, *, get=requests.get) -> str:
    query = f"elevation[({south}):1:({north})][({west}):1:({east})]"
    url = f"{ERDDAP}?{quote(query, safe='():')}"
    try:
        r = get(url, timeout=120)
    except requests.RequestException as exc:
        raise ReliefError(f"{url}: {exc}") from exc
    if r.status_code != 200:
        raise ReliefError(f"{url}: HTTP {r.status_code}: {r.text[:200].strip()}")
    return r.text


def parse_csv(text: str):
    """(lats, lons, elevation[lat, lon]) in metres, negative below sea level.

    ERDDAP's CSV is the column names, a row of units, then one cell per row.
    """
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != HEADER:
        raise ReliefError(f"not an ERDDAP elevation grid: starts {lines[:1]!r}")
    rows = lines[2:]
    if not rows:
        raise ReliefError("the server returned no grid cells")
    cells = np.array([[float(v) for v in row.split(",")] for row in rows])
    lats, lons = np.unique(cells[:, 0]), np.unique(cells[:, 1])
    if len(lats) * len(lons) != len(cells):
        raise ReliefError(f"not a full grid: {len(cells)} cells for "
                          f"{len(lats)} x {len(lons)}")
    z = np.full((len(lats), len(lons)), np.nan)
    z[np.searchsorted(lats, cells[:, 0]), np.searchsorted(lons, cells[:, 1])] = cells[:, 2]
    if np.isnan(z).any():
        raise ReliefError(f"{int(np.isnan(z).sum())} cells without an elevation")
    return lats, lons, z


def contours(lats, lons, z, levels_m=LEVELS_M) -> list[dict]:
    """One GeoJSON LineString per contour line, coordinates [lon, lat]."""
    gen = contourpy.contour_generator(lons, lats, z, line_type=contourpy.LineType.Separate)
    return [{"type": "Feature",
             "properties": {"elevation_m": level},
             "geometry": {"type": "LineString", "coordinates": np.round(line, 5).tolist()}}
            for level in levels_m
            for line in gen.lines(level)
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
        except ReliefError as exc:
            sys.exit(f"bbox {box}: {exc}")
        found = contours(lats, lons, z)
        if not found:
            sys.exit(f"bbox {box}: no contour level crossed between "
                     f"{z.min():.0f} and {z.max():.0f} m")
        print(f"bbox {box}: {len(lats)} x {len(lons)} cells, {z.min():.0f} to {z.max():.0f} m, "
              f"{len(found)} lines")
        features += found

    out = Path(args.out)
    out.write_text(json.dumps({"type": "FeatureCollection", "source": SOURCE,
                               "features": features}, separators=(",", ":")))
    print(f"{out}: {len(features)} lines, {out.stat().st_size // 1024} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
