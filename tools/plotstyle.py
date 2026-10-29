"""IEEE-paper plotting style, and the identity of each node on a figure.

Ported from the monorepo's src/tools/plotstyle.py (the node half; its radio
preset styles belong to the platform's analysis). Style: white surface, boxed
axes with inward ticks, serif type, thin lines, sparse open markers, dotted grid.

Node identity uses composite encoding: hue carries the node's ROLE (its
`function` in the deployment file: sensor nodes blue, pbx radios orange), and
lightness + line style + marker separate the members of a role. The monorepo
hardcoded its five nodes here; the roster now comes from the deployment.

Palette validated with the dataviz skill's validate_palette.js (light surface,
--pairs all): blue vs orange scores all-pairs CVD ΔE 24.7 and clears 3:1 on
white. Two accepted shortfalls inside the blue steps: #184f95 vs #2a78d6 is ΔE
14.7 against a 15 floor, and #6da7ec sits at 2.44:1 on white — legal only
because line style, marker and a legend entry carry identity alongside colour.
Do not drop those channels.
"""
from __future__ import annotations

import matplotlib.pyplot as plt

# Chrome / ink (dataviz reference palette, light mode).
SURFACE = "#ffffff"
GRID = "#8f8e88"
MUTED = "#898781"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"

LINE_STYLES = ["-", "--", "-.", ":"]
MARKERS = ["x", "s", "*", "D"]

# Lightness steps per role, one per member. Line style and marker alone proved
# too weak on dense, oscillating telemetry: the dash pattern is swamped once the
# line changes direction every few pixels. Lightness survives that.
ROLE_STEPS: dict[str, list[str]] = {
    "node": ["#6da7ec", "#2a78d6", "#184f95"],   # sensor nodes: blue 300/450/600
    "pbx": ["#eb6834", "#a8410f"],               # PBX radios: orange + a darker step
}

NEUTRAL = dict(color=INK_SECONDARY, linestyle="-", marker="o",
               markerfacecolor="white", markeredgecolor=INK_SECONDARY)


def node_styles(nodes) -> dict[str, dict]:
    """{published name: ax.plot kwargs} for deployment nodes, in file order.

    A role outside ROLE_STEPS (gateway, receiver, access) gets the neutral style, as does
    any name the caller looks up that is not here: a node still plots.
    """
    styles, seen = {}, {}
    for node in nodes:
        steps = ROLE_STEPS.get(node.function)
        if steps is None:
            styles[node.name] = dict(NEUTRAL)
            continue
        idx = seen[node.function] = seen.get(node.function, -1) + 1
        hue = steps[idx % len(steps)]
        styles[node.name] = dict(color=hue, linestyle=LINE_STYLES[idx % len(LINE_STYLES)],
                                 marker=MARKERS[idx % len(MARKERS)], markerfacecolor="white",
                                 markeredgecolor=hue, markeredgewidth=0.7)
    return styles


def markevery(n_points: int, target: int = 12) -> int:
    """Marker stride that puts about `target` markers on a curve.

    A telemetry series carries thousands of points, where a marker per point is
    a solid band that hides the line instead of identifying it.
    """
    return max(1, n_points // max(1, target))


def apply_paper_style() -> None:
    """IEEE-paper matplotlib defaults: white surface, boxed axes, inward ticks."""
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "font.size": 8,
        "axes.labelsize": 10.5,
        "axes.titlesize": 12,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 6,
        # boxed axes: black frame
        "axes.edgecolor": "black",
        "axes.linewidth": 0.8,
        "axes.facecolor": SURFACE,
        "figure.facecolor": SURFACE,
        "axes.spines.top": True,
        "axes.spines.right": True,
        # inward ticks, minor ticks on
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK_SECONDARY,
        "ytick.labelcolor": INK_SECONDARY,
        "xtick.minor.visible": True,
        "ytick.minor.visible": True,
        # dotted recessive grid
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.4,
        "grid.linestyle": ":",
        # ink
        "text.color": INK_PRIMARY,
        "axes.labelcolor": INK_PRIMARY,
        # marks / legend / output
        "lines.linewidth": 1.2,
        "lines.markersize": 2.2,
        "legend.frameon": True,
        "legend.framealpha": 0.9,
        "legend.edgecolor": "0.7",
        "figure.dpi": 150,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        # Vector output keeps text as text (Type 42), as IEEE PDF checks require.
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
