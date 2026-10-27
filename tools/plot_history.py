"""
plot_history.py  –  LoRa TestBed historical analysis
=====================================================
Queries InfluxDB for the last N days and produces one PNG per node:

    temperature  |  humidity        (10-min MA)
    RSSI         |  SNR             (10-min MA)
    battery      |  voltage         (10-min MA)
    hops (step)  |  –

Run from the repository root, with the database name from .env, the
read-only InfluxDB account from secrets/web.env, and the deployment that
names the nodes:

    set -a; . ./.env; . ./secrets/web.env; set +a
    export MESH_DEPLOYMENT=<name>             # or --deployment <name>
    python -m tools.plot_history

Two modes.

Per node (the default) — one figure per node with the full grid:

    python -m tools.plot_history                    # last 3 days
    python -m tools.plot_history --days 4
    python -m tools.plot_history --out /tmp/plots --format pdf   # vector, for a paper

Across nodes — one field at a time, every node on the same axes, for comparing
links rather than reading one node:

    python -m tools.plot_history --fields rssi              # RSSI of all nodes
    python -m tools.plot_history --fields rssi snr hop      # one figure per field
    python -m tools.plot_history --days 4 --fields rssi --export rssi.csv
    python -m tools.plot_history --export all.csv           # data only, default field set

The CSV carries time / node_id / node_label / topic alongside the values, so a
row can be traced back to a node and a flow. node_id is included because
node_label is only a readable name and the two have disagreed before.

Ported from the monorepo's src/tools/plot_history.py. Node colours come from the
deployment file's roles instead of a roster in the code, and 0.0 readings are
kept by default: the gateway publishes them only when they are real (an SNR of
0.0 dB is an ordinary reading).
"""

import argparse
import datetime
import os
import re
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import requests

from gateway.deployment import DeploymentError, load
from tools import plotstyle

# ── InfluxDB connection ───────────────────────────────────────────────────────

# From .env and secrets/web.env: the database Telegraf writes to, read with the
# read-only account. No admin fallback: the database requires authentication.
INFLUX_URL  = os.environ.get("DB_HOST") or "http://localhost:8086"
INFLUX_DB   = os.environ.get("INFLUXDB_DB", "")
INFLUX_USER = os.environ.get("INFLUXDB_READ_USER", "")
INFLUX_PASS = os.environ.get("INFLUXDB_READ_USER_PASSWORD", "")

if not INFLUX_URL.startswith("http"):
    INFLUX_URL = f"http://{INFLUX_URL}:8086"

# ── Style ─────────────────────────────────────────────────────────────────────

# Series identity comes from plotstyle.node_styles: hue = role (the node's
# function in the deployment file), line style + marker = the node within its
# role. Nothing here hardcodes a colour or a node.
# What counts as an outage worth marking on a figure. This was 120 s — exactly
# one missed device slot — which shaded every single dropped packet: node-1 alone
# has hundreds, and the bands merged into a solid wash that hid the series they
# were annotating. Ordinary per-packet loss is already legible as sparse raw
# points; shading is for a gap long enough to read as the node being away.
GAP_THRESHOLD_S = 900

# Figure geometry, in inches, at IEEE double-column width. The paper style sets
# an 8 pt base font, which only reads correctly against a canvas of about this
# size; on the 14-inch canvases this script used before, the type came out tiny.
FIGSIZE_FIELD = (7.16, 3.6)     # one field, every node overlaid
FIGSIZE_GRID  = (7.16, 8.6)     # the 4x2 per-node grid

# Default set for --export when no --fields is given: link metrics, sensor
# readings and power. Deliberately not "every field in the measurement" — that
# would pull in the PDR block, which rides inside the telemetry payloads and
# needs different handling (a null `pdr` means "not enough slots measured yet",
# not a missing sample, and a CSV cannot tell those apart).
_ALL_EXPORT_FIELDS = ["rssi", "snr", "hop", "temperature", "humidity",
                      "battery_level", "voltage", "channel_util",
                      "air_util_tx", "uptime_seconds"]


# ── InfluxDB helpers ──────────────────────────────────────────────────────────

def _query(q: str) -> list[dict]:
    """
    Runs an InfluxQL query and returns every row from EVERY series.

    A GROUP BY returns one series per tag combination, and each series carries
    its tag values in `tags` rather than as columns. An earlier version read
    series[0] only, so any grouped query silently returned the first node and
    dropped the rest — which is why this tool used to query one node at a time.
    The tag values are merged in as columns so a grouped result reads like a
    flat table.
    """
    resp = requests.get(
        f"{INFLUX_URL}/query",
        params={"db": INFLUX_DB, "q": q, "epoch": "s"},
        auth=(INFLUX_USER, INFLUX_PASS),
        timeout=60,
    )
    if resp.status_code == 401:
        raise RuntimeError("InfluxDB refused the credentials: set INFLUXDB_READ_USER and "
                           "INFLUXDB_READ_USER_PASSWORD (secrets/web.env)")
    resp.raise_for_status()
    payload = resp.json()

    rows = []
    for result in payload.get("results", []):
        if "error" in result:
            raise RuntimeError(f"InfluxDB rejected the query: {result['error']}")
        for series in result.get("series", []):
            cols = series["columns"]
            tags = series.get("tags") or {}
            for values in series.get("values", []):
                row = dict(zip(cols, values))
                row.update(tags)        # node_label etc. become ordinary columns
                rows.append(row)
    return rows


def fetch_nodes(days: int) -> list[str]:
    rows = _query(
        f"SHOW TAG VALUES FROM telemetry "
        f"WITH KEY = node_label WHERE time > now() - {days}d"
    )
    return sorted({r["value"] for r in rows})


def fetch_field(field: str, days: int) -> pd.DataFrame:
    """
    One field for EVERY node, in a single query.

    Returns a frame with time / node_id / node_label / topic / <field>. Grouping
    by both tags keeps node_id in the result: node_label is the readable name but
    node_id is the identity, and the two have disagreed before (see
    project-overview § Known constraints), so an export that carries only the
    label cannot be checked against anything.
    """
    rows = _query(
        f'SELECT "{field}" FROM telemetry '
        f'WHERE time > now() - {days}d '
        f'GROUP BY "node_id","node_label","topic" '
        f'ORDER BY time ASC'
    )
    rows = [r for r in rows if r.get(field) is not None]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time"] = _to_local(df["time"])
    return df.sort_values("time").reset_index(drop=True)


def fetch_fields(fields: list[str], days: int) -> pd.DataFrame:
    """
    Several fields for every node, joined on (time, node_id, topic).

    Queried one field at a time rather than as `SELECT a,b,c`: a single query
    would return a row for every timestamp where ANY of them exists, padding the
    rest with nulls, and those nulls are indistinguishable in a CSV from a metric
    the node genuinely does not report. Per-field queries keep absence honest.
    """
    frames = []
    for field in fields:
        df = fetch_field(field, days)
        if df.empty:
            print(f"[WARN] no '{field}' data in the last {days} days")
            continue
        frames.append(df.set_index(["time", "node_id", "node_label", "topic"]))
    if not frames:
        return pd.DataFrame()
    out = frames[0]
    for extra in frames[1:]:
        out = out.join(extra, how="outer")
    return out.reset_index().sort_values("time").reset_index(drop=True)


def fetch_node_data(node_label: str, days: int) -> pd.DataFrame:
    rows = _query(
        f"SELECT * FROM telemetry "
        f"WHERE node_label = '{_quote(node_label)}' AND time > now() - {days}d "
        f"ORDER BY time ASC"
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time"] = _to_local(df["time"])
    df.sort_values("time", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _quote(value: str) -> str:
    """A tag value inside an InfluxQL string literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


# ── Time helpers ──────────────────────────────────────────────────────────────

def _to_local(series: pd.Series) -> pd.Series:
    now = datetime.datetime.now().astimezone()
    return (
        pd.to_datetime(series, unit="s", utc=True)
        .dt.tz_convert(datetime.timezone(now.utcoffset()))
        .dt.tz_localize(None)
    )


def _tz_label() -> str:
    return datetime.datetime.now().astimezone().tzname()


def _session_str(times: pd.Series) -> str:
    t0, t1 = times.min(), times.max()
    dur = (t1 - t0).total_seconds()
    return (
        f"{t0.strftime('%Y-%m-%d  %H:%M')} – {t1.strftime('%Y-%m-%d %H:%M')}  "
        f"({int(dur // 3600)}h {int((dur % 3600) // 60):02d}m)"
    )


# ── Moving average ────────────────────────────────────────────────────────────

def _smooth(src: pd.DataFrame, col: str) -> pd.Series:
    """10-minute time-based rolling mean; index is the original datetime."""
    s = src.set_index("time")[col].dropna()
    if s.empty:
        return s
    return s.rolling("10min").mean()


# ── Axis helpers ──────────────────────────────────────────────────────────────

def _fmt_xaxis(ax, tz_label: str, show_label: bool = True):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    if show_label:
        ax.set_xlabel(f"Time ({tz_label})", fontsize=9)


def _find_gaps(times: pd.Series):
    diffs = times.diff()
    return [
        (times.iloc[i - 1], times.iloc[i])
        for i in range(1, len(times))
        if diffs.iloc[i].total_seconds() > GAP_THRESHOLD_S
    ]


def _shade_gaps(axes, gaps, colour):
    """Shades outage spans. No edge lines: two dashed rules per gap turned into
    the dominant ink on the figure as soon as there was more than a handful."""
    for start, end in gaps:
        for ax in axes:
            ax.axvspan(start, end, color=colour, alpha=0.10, linewidth=0)


# ── Per-node figure ───────────────────────────────────────────────────────────

def plot_node(label: str, df: pd.DataFrame, style: dict, tz_label: str, out_dir: str,
              fmt: str = "png", drop_zeros: bool = False):
    # Split by topic
    env   = df[df["topic"].str.endswith("/environment")].copy() if "topic" in df else pd.DataFrame()
    telem = df[df["topic"].str.endswith("/device")].copy()      if "topic" in df else pd.DataFrame()

    if df.empty:
        print(f"[SKIP] No data for {label}")
        return

    colour = style["color"]
    fig, axes = plt.subplots(4, 2, figsize=FIGSIZE_GRID, sharex=True)
    ax_temp, ax_hum, ax_rssi, ax_snr, ax_bat, ax_volt, ax_hop, ax_empty = axes.flat
    ax_empty.set_visible(False)

    fig.suptitle(
        f"{label}  –  Historical Analysis\n{_session_str(df['time'])}",
        fontsize=13, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94], h_pad=1.8, w_pad=1.6)

    visible_axes = [ax for ax in axes.flat if ax.get_visible()]
    if not telem.empty:
        _shade_gaps(visible_axes, _find_gaps(telem["time"]), colour)

    def _plot(ax, src, col, title, ylabel, ylim=None):
        ax.set_title(title, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.4)
        if ylim:
            ax.set_ylim(*ylim)
        if not src.empty and col in src.columns:
            valid = src[src[col].notna()]
            if drop_zeros and col in _ZERO_IS_FAKE:
                valid = valid[valid[col] != 0.0]
            if not valid.empty:
                # Raw samples as points only, matching the cross-node figures:
                # a connecting line here would draw a trend through an outage.
                ax.plot(valid["time"], valid[col], color=colour, linestyle="none",
                        alpha=0.25, marker=".", markersize=1.5)
                ma = _smooth(valid, col)
                ax.plot(ma.index, ma.values, color=colour, linewidth=1.2,
                        linestyle=style["linestyle"])
            else:
                ax.text(0.5, 0.5, "no data", transform=ax.transAxes,
                        ha="center", va="center", color="grey", fontsize=10)

    def _step_plot(ax, src, col, title, ylabel):
        ax.set_title(title, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
        if not src.empty and col in src.columns:
            valid = src[src[col].notna()]
            if not valid.empty:
                ax.step(valid["time"], valid[col],
                        color=colour, linewidth=1.2, where="post")
            else:
                ax.text(0.5, 0.5, "no data", transform=ax.transAxes,
                        ha="center", va="center", color="grey", fontsize=10)

    _plot(ax_temp, env,   "temperature",   "Temperature",       "°C")
    _plot(ax_hum,  env,   "humidity",      "Relative Humidity", "%",   (0, 100))
    _plot(ax_rssi, telem, "rssi",          "RSSI",              "dBm")
    _plot(ax_snr,  telem, "snr",           "SNR",               "dB")
    _plot(ax_bat,  telem, "battery_level", "Battery Level",     "%",   (0, 100))
    _plot(ax_volt, telem, "voltage",       "Voltage",           "V")
    _step_plot(ax_hop, telem, "hop",       "Hops to Gateway",   "hops")

    for ax in axes.flat:
        if ax.get_visible():
            _fmt_xaxis(ax, tz_label, show_label=(ax in axes[-1]))

    out = os.path.join(out_dir, f"{label}_history.{fmt}")
    fig.savefig(out, bbox_inches="tight")
    print(f"Saved → {out}")


# ── Cross-node comparison ─────────────────────────────────────────────────────

# Fields that the MONOREPO's gateway, before its omit-not-zero fix, published as
# a fake 0.0 when absent. Only --drop-zeros filters them, for data recorded back
# then: this gateway publishes 0.0 only when it was measured — an SNR of 0.0 dB
# is an ordinary reading. `hop` is never filtered: 0 hops means "heard directly".
_ZERO_IS_FAKE = {"rssi", "snr", "voltage", "temperature", "humidity",
                 "latitude", "longitude"}


def _break_at_gaps(s: pd.Series) -> pd.Series:
    """
    Inserts NaN where samples are far apart, so the line breaks instead of
    spanning the gap.

    Without this a plot draws a straight segment across an outage — the tool
    would be asserting a trend through hours in which nothing was received. The
    threshold adapts to each series' own cadence rather than using one constant,
    because device telemetry arrives every 120 s and position every 600 s, and a
    fixed threshold either breaks the slow flow constantly or never breaks the
    fast one.
    """
    if len(s) < 3:
        return s
    dt = s.index.to_series().diff()
    # Positive gaps only: two flows of one node (device and environment) often
    # share a timestamp, and a median of zero would disable every break.
    median = dt[dt > pd.Timedelta(0)].median()
    if pd.isna(median) or median.total_seconds() <= 0:
        return s
    limit = max(median * 5, pd.Timedelta(seconds=300))
    breaks = s.index[dt > limit]
    if len(breaks) == 0:
        return s
    # A NaN just before each resumption is what splits the line.
    holes = pd.Series(float("nan"),
                      index=[t - pd.Timedelta(microseconds=1) for t in breaks])
    return pd.concat([s, holes]).sort_index()


def plot_field_across_nodes(field: str, df: pd.DataFrame, tz_label: str,
                            out_dir: str, days: int, styles: dict, fmt: str = "png",
                            drop_zeros: bool = False):
    """One figure, one field, every node overlaid so they can be compared."""
    if df.empty or field not in df.columns:
        print(f"[SKIP] no data for '{field}'")
        return

    step = field == "hop"        # hops are discrete; a line implies interpolation
    fig, ax = plt.subplots(figsize=FIGSIZE_FIELD)

    plotted = 0
    for label, grp in sorted(df.groupby("node_label")):
        s = grp[["time", field]].dropna()
        if drop_zeros and field in _ZERO_IS_FAKE:
            s = s[s[field] != 0.0]
        if s.empty:
            continue
        style  = styles.get(label, plotstyle.NEUTRAL)
        colour = style["color"]
        node_id = grp["node_id"].dropna().iloc[0] if "node_id" in grp else "?"
        legend = f"{label} ({node_id})   n={len(s)}"

        if step:
            broken = _break_at_gaps(s.set_index("time")[field])
            ax.step(broken.index, broken.values, where="post",
                    color=colour, linestyle=style["linestyle"],
                    linewidth=1.2, label=legend)
        else:
            # Raw samples as points only — no connecting line, so an outage looks
            # like absence rather than a trend.
            ax.plot(s["time"], s[field], color=colour, linestyle="none",
                    alpha=0.15, marker=".", markersize=1.5)
            ma = _break_at_gaps(_smooth(s, field))
            # The role hue is shared by three nodes, so line style and marker are
            # what separate them. On these dense, oscillating series the dash
            # pattern is largely swamped, which leaves the marker doing the real
            # work — hence a marker bigger than the paper default and a stride
            # that puts enough of them on the curve to be followed.
            ax.plot(ma.index, ma.values, linewidth=1.2, label=legend,
                    markersize=3.8,
                    markevery=plotstyle.markevery(len(ma), target=22), **style)
        plotted += 1

    if plotted == 0:
        print(f"[SKIP] '{field}' had no plottable values")
        plt.close(fig)
        return

    ax.set_title(f"{field}  –  all nodes, last {days} days\n{_session_str(df['time'])}",
                 fontsize=13, fontweight="bold")
    ax.set_ylabel(field, fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.4)
    if field == "hop":
        ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0)
    _fmt_xaxis(ax, tz_label)
    fig.tight_layout()

    out = os.path.join(out_dir, f"all-nodes_{field}.{fmt}")
    fig.savefig(out, bbox_inches="tight")
    print(f"Saved → {out}")


def export_csv(df: pd.DataFrame, path: str):
    """Writes the queried frame as-is, so what was plotted is what was exported."""
    if df.empty:
        print("[SKIP] nothing to export")
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    nodes = sorted(df["node_label"].dropna().unique()) if "node_label" in df else []
    print(f"Exported {len(df)} rows ({', '.join(nodes)}) → {out}")


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(nodes: list[str], data: dict[str, pd.DataFrame], days: int):
    print(f"\n── Last {days} days ──────────────────────────────────────────────────")
    for label in nodes:
        df = data[label]
        if df.empty:
            print(f"  {label}  |  no data")
            continue
        n_env   = len(df[df["topic"].str.endswith("/environment")]) if "topic" in df else 0
        n_dev   = len(df[df["topic"].str.endswith("/device")])      if "topic" in df else 0
        rssi_str = ""
        if "rssi" in df.columns:
            r = df["rssi"].dropna()
            r = r[r != 0.0]
            if not r.empty:
                rssi_str = f"  |  RSSI {r.min():.0f} – {r.max():.0f} dBm"
        print(
            f"  {label}  |  {n_dev} device, {n_env} env packets"
            f"{rssi_str}"
            f"  |  {_session_str(df['time'])}"
        )
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Plot and export LoRa TestBed history from InfluxDB",
        epilog=(
            "examples:\n"
            "  %(prog)s                              per-node grids, last 3 days\n"
            "  %(prog)s --days 4                     same, 4 days\n"
            "  %(prog)s --fields rssi                RSSI of every node on one figure\n"
            "  %(prog)s --fields rssi snr hop        one figure per field\n"
            "  %(prog)s --fields rssi --export rssi.csv\n"
            "  %(prog)s --export all.csv --fields rssi snr hop battery_level\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days",  type=int, default=3,  help="How many days back to query (default: 3)")
    parser.add_argument("--out",   default=".",          help="Output directory for figures (default: .)")
    parser.add_argument("--format", default="png", choices=("png", "pdf", "svg"),
                        help="Figure format; pdf/svg are vector, for a paper (default: png)")
    parser.add_argument("--deployment", default=os.environ.get("MESH_DEPLOYMENT"),
                        help="The deployment whose roles colour the nodes "
                             "(or MESH_DEPLOYMENT); without it every node is grey")
    parser.add_argument("--show",  action="store_true",  help="Open interactive matplotlib window after saving")
    parser.add_argument("--fields", nargs="+", metavar="FIELD",
                        help="Compare these fields across ALL nodes: one figure per "
                             "field with every node overlaid. Without this, the "
                             "per-node grids are produced as before.")
    parser.add_argument("--export", metavar="FILE.csv",
                        help="Write the queried rows to CSV (time, node_id, "
                             "node_label, topic, values). Uses --fields when given, "
                             "otherwise every field.")
    parser.add_argument("--drop-zeros", action="store_true",
                        help="Drop 0.0 readings of rssi, snr, voltage, temperature, "
                             "humidity, latitude and longitude. Only for data the "
                             "monorepo's gateway recorded before its omit-not-zero fix, "
                             "which published absent metrics as 0.0. `hop` is never "
                             "filtered — 0 hops is real.")
    args = parser.parse_args()

    if not INFLUX_DB:
        sys.exit("INFLUXDB_DB is not set: load the settings first "
                 "(set -a; . ./.env; . ./secrets/web.env; set +a)")
    bad = [f for f in (args.fields or []) if not re.fullmatch(r"[a-z_]+", f)]
    if bad:
        sys.exit(f"not a field name: {bad}")
    styles = {}
    if args.deployment:
        try:
            styles = plotstyle.node_styles(load(args.deployment).nodes)
        except DeploymentError as exc:
            sys.exit(f"deployment: {exc}")
    else:
        print("[WARN] no deployment (--deployment or MESH_DEPLOYMENT): every node is grey")

    os.makedirs(args.out, exist_ok=True)
    plotstyle.apply_paper_style()
    tz_label = _tz_label()
    print(f"Querying InfluxDB at {INFLUX_URL} / db={INFLUX_DB} ...")

    # ── Cross-node mode: one field at a time, every node together ────────────
    if args.fields or args.export:
        fields = args.fields or _ALL_EXPORT_FIELDS
        df = fetch_fields(fields, args.days)
        if df.empty:
            print(f"No data for {fields} in the last {args.days} days.")
            return
        nodes = sorted(df["node_label"].dropna().unique())
        print(f"Found nodes: {nodes}\n")
        if args.export:
            export_csv(df, args.export)
        if args.fields:
            for field in args.fields:
                plot_field_across_nodes(field, df, tz_label, args.out, args.days,
                                        styles, args.format, args.drop_zeros)
        if args.show:
            plt.show()
        return

    # ── Default: one grid per node ───────────────────────────────────────────
    nodes = fetch_nodes(args.days)
    if not nodes:
        print(f"No nodes found in the last {args.days} days.")
        return

    print(f"Found nodes: {nodes}\n")
    data = {label: fetch_node_data(label, args.days) for label in nodes}

    print_summary(nodes, data, args.days)

    for label in nodes:
        plot_node(label, data[label], styles.get(label, plotstyle.NEUTRAL), tz_label,
                  args.out, args.format, args.drop_zeros)

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
