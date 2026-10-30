#!/usr/bin/env bash
#
# Builds the dashboard's offline map into this directory: a basemap cut out of
# the Protomaps build of OpenStreetMap (basemap.pmtiles) and elevation and depth
# contours around Rapa Nui (relief.geojson). Run it on a machine with internet
# and commit the result: the field host needs none.
#
# Needs pmtiles (https://github.com/protomaps/go-pmtiles/releases) on PATH, and
# the repository's .venv with tools/requirements.txt installed.
#
# Update: change BUILD (https://maps.protomaps.com/builds/ lists the daily
# builds; old ones are deleted) or a box below, run ./fetch.sh, commit the result.
#
# Licences, credited on the map itself: OpenStreetMap data is ODbL
# (© OpenStreetMap contributors); the terrain grid is GEBCO's (GEBCO Compilation
# Group, 2020), free to use and redistribute, not for navigation.

set -euo pipefail
cd "$(dirname "$0")"
root=$(cd ../../.. && pwd)

BUILD=20261029            # Protomaps basemap build, YYYYMMDD
MAXZOOM=15                # the build's own maximum; the map overzooms past it

# Boxes: SOUTH WEST NORTH EAST
SAN_JOAQUIN="-33.53 -70.66 -33.46 -70.56"     # the campus and around it, Santiago
RAPA_NUI="-27.31 -109.56 -26.95 -109.11"      # the island and some 10 km of sea: the relief
RAPA_NUI_SEA="-27.60 -109.90 -26.65 -108.75"  # wider, so a wide screen never shows the edge

command -v pmtiles >/dev/null || { echo "error: pmtiles is not on PATH (see the top of $0)" >&2; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

ring() { read -r s w n e <<<"$1"; echo "[[[$w,$s],[$e,$s],[$e,$n],[$w,$n],[$w,$s]]]"; }
echo "{\"type\":\"MultiPolygon\",\"coordinates\":[$(ring "$SAN_JOAQUIN"),$(ring "$RAPA_NUI_SEA")]}" \
    > "$tmp/region.geojson"
pmtiles extract "https://build.protomaps.com/$BUILD.pmtiles" "$tmp/basemap.pmtiles" \
    --region="$tmp/region.geojson" --maxzoom=$MAXZOOM

# shellcheck disable=SC2086  # the box is four arguments
(cd "$root" && .venv/bin/python -m tools.relief --bbox $RAPA_NUI --out "$tmp/relief.geojson")

mv "$tmp/basemap.pmtiles" "$tmp/relief.geojson" .
sha256sum basemap.pmtiles relief.geojson > SHA256SUMS
echo "SHA256SUMS written"
