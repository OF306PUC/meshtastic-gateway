"""Start-up checks: misconfigurations that would otherwise only show as bad data."""
from __future__ import annotations

from gateway.config import Config
from gateway.deployment import Deployment

__all__ = ["warnings"]


def warnings(dep: Deployment, cfg: Config, my_id: str | None, my_role: str | None) -> list[str]:
    out = []
    me = dep.known_nodes().get(my_id) if my_id else None
    if me is None:
        out.append(f"this radio ({my_id}) is not in {dep.path.name}: is the gateway "
                   f"listening to the mesh the file describes? (G10)")
    elif me.function != "gateway":
        out.append(f"this radio is {me.ref} in {dep.path.name}, declared as "
                   f"function {me.function!r}, not 'gateway'")
    if my_role != "CLIENT_MUTE":
        out.append(f"this radio's role is {my_role}, not CLIENT_MUTE: if it rebroadcasts, "
                   f"it contaminates its own measurement (G6). Provision it from the platform")
    cadences = [s for n in dep.nodes if n.node_id for s in n.intervals.values()]
    if cadences and cfg.sweep_interval_sec >= min(cadences):
        out.append(f"PDR_SWEEP_INTERVAL_SEC={cfg.sweep_interval_sec} is not below the "
                   f"shortest cadence ({min(cadences)} s): silence would be detected late")
    return out
