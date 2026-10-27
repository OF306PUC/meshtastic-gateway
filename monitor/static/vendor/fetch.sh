#!/usr/bin/env bash
#
# Downloads the dashboard's browser libraries into this directory, so the
# dashboard works without internet (in the field) and runs no code a CDN could
# change later. Each file is fetched from two independent CDNs and must be
# byte-identical; the SHA-256 of every file goes into SHA256SUMS.
#
# Update: change a version below, run ./fetch.sh, commit the result.
# Map tiles are not covered: they still come from openstreetmap.org.

set -euo pipefail
cd "$(dirname "$0")"

FILES=(
    "chart.js@4.6.1/dist/chart.umd.min.js"
    "chart.js@4.6.1/LICENSE.md"
    "chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"
    "chartjs-adapter-date-fns@3.0.0/LICENSE.md"
    "date-fns@2.19.0/LICENSE.md"   # bundled inside the adapter
    "leaflet@1.9.4/dist/leaflet.js"
    "leaflet@1.9.4/dist/leaflet.css"
    "leaflet@1.9.4/dist/images/marker-icon.png"
    "leaflet@1.9.4/dist/images/marker-icon-2x.png"
    "leaflet@1.9.4/dist/images/marker-shadow.png"
    "leaflet@1.9.4/dist/images/layers.png"
    "leaflet@1.9.4/dist/images/layers-2x.png"
    "leaflet@1.9.4/LICENSE"
    "socket.io-client@4.4.1/dist/socket.io.min.js"
    "socket.io-client@4.4.1/LICENSE"
)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for f in "${FILES[@]}"; do
    pkg=${f%%/*}                       # chart.js@4.6.1
    rel=${f#*/}                        # dist/chart.umd.min.js
    dest="${pkg/@/-}/${rel#dist/}"     # chart.js-4.6.1/chart.umd.min.js
    curl -fsSL "https://cdn.jsdelivr.net/npm/$f" -o "$tmp/a"
    curl -fsSL "https://unpkg.com/$f" -o "$tmp/b"
    if ! cmp -s "$tmp/a" "$tmp/b"; then
        echo "error: $f differs between jsdelivr and unpkg — not copied" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$dest")"
    mv "$tmp/a" "$dest"
    echo "ok  $dest"
done

find . -type f ! -name fetch.sh ! -name SHA256SUMS ! -name README.md -print0 \
    | sort -z | xargs -0 sha256sum > SHA256SUMS
echo "SHA256SUMS written"
