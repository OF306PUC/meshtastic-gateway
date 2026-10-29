"""The gateway's reader for deployments/*.yaml: only what the gateway uses.

Same file format as meshtastic-platform's deployments/, read independently
(docs/design.md §1). The platform validates the whole file; this reader
is strict about the fields it reads and ignores the rest. Its semantics match
the platform's: a node publishes under `label`, or `ref` when there is none; a
flow absent from `intervals` is one the node does not emit; cadences are
divided by meta.cadence_scale; site.surveyed and site.planned (for the
dashboard's map) are all-null until filled in, and never confused: planned is
where a node should go, surveyed where it was measured on site. `sha256` is the
hash of the file's bytes, the same one the platform records, so the two copies
can be compared (G10).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from gateway.decode import FLOW_KINDS

__all__ = ["ENV_DEPLOYMENT", "ENV_DEPLOYMENTS_DIR", "Deployment", "DeploymentError",
           "Node", "Position", "deployments_dir", "load", "parse"]

ENV_DEPLOYMENT = "MESH_DEPLOYMENT"
ENV_DEPLOYMENTS_DIR = "MESH_DEPLOYMENTS_DIR"
_NODE_ID = re.compile(r"^![0-9a-f]{8}$")


class DeploymentError(Exception):
    def __init__(self, where: Any, problems: list[str]):
        self.problems = problems
        super().__init__(f"{where}:\n  - " + "\n  - ".join(problems))


@dataclass(frozen=True)
class Position:
    """A point from the file, planned or surveyed. A record only: never written to a radio."""
    lat: float
    lon: float
    alt_m: float | None


@dataclass(frozen=True)
class Node:
    ref: str
    name: str                          # the published name: label, or ref
    function: str
    node_id: str | None
    intervals: Mapping[str, int]       # EFFECTIVE cadences, cadence_scale applied
    surveyed: Position | None = None   # site.surveyed: measured on site
    planned: Position | None = None    # site.planned: chosen at a desk, not a measurement


@dataclass(frozen=True)
class Deployment:
    name: str
    path: Path
    sha256: str
    cadence_scale: int
    nodes: tuple[Node, ...]

    def known_nodes(self) -> dict[str, Node]:
        """{node_id: Node} for every node whose id has been recorded."""
        return {n.node_id: n for n in self.nodes if n.node_id}


def deployments_dir(environ: Mapping[str, str] = os.environ) -> Path:
    return Path(environ.get(ENV_DEPLOYMENTS_DIR)
                or Path(__file__).resolve().parents[1] / "deployments")


def _resolve(ref: str | None, environ: Mapping[str, str]) -> Path:
    ref = ref or environ.get(ENV_DEPLOYMENT)
    if not ref:
        raise DeploymentError("deployment", [f"none selected: set {ENV_DEPLOYMENT} (.env). "
                                             f"Nothing defaults to a mesh"])
    path = Path(ref) if ref.endswith((".yaml", ".yml")) else deployments_dir(environ) / f"{ref}.yaml"
    if not path.is_file():
        here = sorted(p.stem for p in path.parent.glob("*.yaml") if not p.stem.startswith("_"))
        raise DeploymentError(path, [f"no such deployment file (available in {path.parent}: "
                                     f"{', '.join(here) or 'none'})"])
    return path


def load(ref: str | None = None, environ: Mapping[str, str] = os.environ) -> Deployment:
    """A deployment by name (deployments/<name>.yaml, or <folder>/<name>) or by YAML path."""
    path = _resolve(ref, environ)
    blob = path.read_bytes()
    try:
        data = yaml.safe_load(blob)
    except yaml.YAMLError as exc:
        hint = (" — a node id starts with '!', which YAML reads as a tag: quote it"
                if "!" in str(exc) else "")
        raise DeploymentError(path, [f"not valid YAML{hint}: {exc}"]) from None
    return parse(data, path=path, sha256=hashlib.sha256(blob).hexdigest())


def parse(data: Any, *, path: Path, sha256: str) -> Deployment:
    problems: list[str] = []
    if not isinstance(data, dict):
        raise DeploymentError(path, ["expected a mapping with meta, radio and nodes"])

    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    name = meta.get("deployment")
    if not isinstance(name, str) or not name:
        problems.append("meta.deployment: required")
    elif path.stem != name:
        problems.append(f"meta.deployment is {name!r} but the file is {path.name}")
    scale = meta.get("cadence_scale", 1)
    if not isinstance(scale, int) or isinstance(scale, bool) or scale < 1:
        problems.append(f"meta.cadence_scale: must be an int >= 1, got {scale!r}")
        scale = 1

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        problems.append("nodes: expected a non-empty list")
        raw_nodes = []
    nodes = [n for i, raw in enumerate(raw_nodes)
             if (n := _node(raw, f"nodes[{i}]", scale, problems)) is not None]

    for what, values in (("ref", [n.ref for n in nodes]),
                         ("published name (label or ref)", [n.name for n in nodes]),
                         ("node_id", [n.node_id for n in nodes if n.node_id])):
        dupes = sorted({v for v in values if values.count(v) > 1})
        if dupes:
            problems.append(f"duplicate {what}: {dupes}")

    if problems:
        raise DeploymentError(path, problems)
    return Deployment(name=name, path=path, sha256=sha256, cadence_scale=scale,
                      nodes=tuple(nodes))


def _node(raw: Any, where: str, scale: int, problems: list[str]) -> Node | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: expected a mapping")
        return None
    ref = raw.get("ref")
    if not isinstance(ref, str) or not ref:
        problems.append(f"{where}.ref: required")
        return None
    where = f"node {ref}"
    label = raw.get("label")
    if label is not None and (not isinstance(label, str) or not label):
        problems.append(f"{where}.label: must be a non-empty string or absent")
        label = None
    node_id = raw.get("node_id")
    if node_id is not None and (not isinstance(node_id, str) or not _NODE_ID.match(node_id)):
        problems.append(f"{where}.node_id: expected '!' + 8 lowercase hex digits, got {node_id!r}")
        node_id = None
    function = raw.get("function")
    if not isinstance(function, str) or not function:
        problems.append(f"{where}.function: required")
    site = raw.get("site")
    if site is not None and not isinstance(site, dict):
        problems.append(f"{where}.site: expected a mapping or null")
        site = None
    return Node(ref=ref, name=label or ref, function=function or "", node_id=node_id,
                intervals=_intervals(raw.get("intervals"), f"{where}.intervals", scale, problems),
                surveyed=_position((site or {}).get("surveyed"), f"{where}.site.surveyed", problems),
                planned=_position((site or {}).get("planned"), f"{where}.site.planned", problems))


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _position(raw: Any, where: str, problems: list[str]) -> Position | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append(f"{where}: expected a mapping")
        return None
    if raw and all(v is None for v in raw.values()):
        return None                    # the template block, not filled in yet
    ok = True
    for key, limit in (("lat", 90), ("lon", 180)):
        value = raw.get(key)
        if not _number(value):
            problems.append(f"{where}.{key}: a number is required once the block is "
                            f"filled in, got {value!r}")
            ok = False
        elif not -limit <= value <= limit:
            problems.append(f"{where}.{key}: out of range: {value!r}")
            ok = False
        elif value == 0:
            problems.append(f"{where}.{key}: is 0 — looks unset")
            ok = False
    alt = raw.get("alt_m")
    if alt is not None and not _number(alt):
        problems.append(f"{where}.alt_m: must be a number or null, got {alt!r}")
        ok = False
    if not ok:
        return None
    return Position(float(raw["lat"]), float(raw["lon"]), float(alt) if alt is not None else None)


def _intervals(raw: Any, where: str, scale: int, problems: list[str]) -> dict[str, int]:
    if not isinstance(raw, dict):
        problems.append(f"{where}: expected a mapping of flow -> seconds "
                        f"({{}} for a node that broadcasts no measured flow)")
        return {}
    out = {}
    for kind, secs in raw.items():
        if kind not in FLOW_KINDS:
            problems.append(f"{where}: unknown flow kind {kind!r} (expected one of {FLOW_KINDS})")
        elif secs is None or secs == 0:
            problems.append(f"{where}.{kind}: is {secs!r}. A flow the node does not emit must "
                            f"be ABSENT: measuring it would fabricate 100 % loss")
        elif not isinstance(secs, int) or isinstance(secs, bool) or secs < 0:
            problems.append(f"{where}.{kind}: must be a positive int (seconds), got {secs!r}")
        elif secs % scale:
            problems.append(f"{where}.{kind}: {secs} s is not divisible by cadence_scale {scale}")
        else:
            out[kind] = secs // scale
    return out
