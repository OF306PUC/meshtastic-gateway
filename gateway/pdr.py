"""Packet delivery ratio per flow, inferred from a known broadcast cadence.

Ported unchanged from the monorepo's src/gateway/mesh_receiver.py. Read
docs/architecture/pdr-cadence-tracker.md before changing it: every invariant
here has a regression test, and most look like simplifications waiting to happen.
"""
import collections
import threading


class CadencePdrTracker:
    """
    Packet-delivery-ratio estimator for flows with a KNOWN broadcast cadence.

    No sequence numbers involved: losses are inferred from inter-arrival gaps
    against the configured interval T.  On each on-schedule reception:

        slots  = round(dt / T)          # nominal intervals the gap spans
        missed = max(0, slots - 1)

    State is per flow — a (node_label, kind) pair with kind in
    ("device", "environment", "position").

    Accuracy and limitations, stated on purpose:

    * ±1 packet per gap.  The firmware defers broadcasts under channel
      congestion, so T is nominal, not exact.
    * A powered-off node inflates `missed`.  Reboots are detected from
      deviceMetrics.uptimeSeconds by the caller, which then re-anchors the
      flow so the downtime gap is not charged as radio loss.
    * `pdr` is None until at least one gap has been observed — a single packet
      carries no delivery information, and reporting 1.0 there would be a lie.
    """

    MIN_WINDOW_SLOTS = 3

    def __init__(self):
        self._flows = {}
        self._lock  = threading.Lock()

    # Public API:
    def observe(self, flow: tuple, interval: int, window_sec: int, now: float) -> dict:
        """
        Records one reception on `flow`.  `now` MUST come from time.monotonic():
        wall-clock deltas would turn an NTP step on the host into phantom losses
        across every flow at once.

        Returns a snapshot dict ready to merge into the outgoing MQTT payload.
        """
        with self._lock:
            f = self._flows.get(flow)
            if f is None:
                f = self._flows[flow] = self._new_flow(interval, window_sec, now)
                return self._snapshot(f, gap_s=None, missed_now=0)

            dt = now - f["last"]

            if f["restart"]:
                # First packet after a reboot: it starts a new cadence grid, so
                # it is scored as neither early nor late whatever dt says.
                f["restart"] = False
                f["rx"]     += 1
                f["last"]    = now
                f["charged"] = 0
                f["recent"].append(1)
                return self._snapshot(f, gap_s=round(dt, 1), missed_now=0)

            slots = round(dt / f["interval"])

            if slots == 0:
                # Arrived inside a single nominal interval: an extra broadcast
                # the cadence model does not predict.
                f["early"] += 1
                return self._snapshot(f, gap_s=round(dt, 1), missed_now=0)

            missed_now   = max(0, slots - 1 - f["charged"])
            f["rx"]     += 1
            f["missed"] += missed_now
            f["last"]    = now
            f["charged"] = 0
            f["recent"].extend([0] * missed_now)
            f["recent"].append(1)
            return self._snapshot(f, gap_s=round(dt, 1), missed_now=missed_now)

    def sweep(self, now: float) -> list:
        """
        Charges provisional losses for flows that have gone quiet.

        Returns [(flow, snapshot)] for the flows that changed.
        """
        changed = []
        with self._lock:
            for flow, f in self._flows.items():
                due = max(0, round((now - f["last"]) / f["interval"]) - 1)
                if due > f["charged"]:
                    delta        = due - f["charged"]
                    f["missed"] += delta
                    f["charged"] = due
                    f["recent"].extend([0] * delta)
                    changed.append((flow, self._snapshot(
                        f, gap_s=round(now - f["last"], 1), missed_now=delta)))
        return changed

    def reanchor(self, flow: tuple, now: float):
        """
        Refunds losses charged during a gap that was NOT a radio loss (the node
        was down) and restarts the cadence grid at `now`.
        """
        with self._lock:
            f = self._flows.get(flow)
            if f is None:
                return
            f["missed"] -= f["charged"]
            for _ in range(f["charged"]):
                if f["recent"] and f["recent"][-1] == 0:
                    f["recent"].pop()      # sweep() appended these at the tail
            f["charged"] = 0
            f["last"]    = now
            f["restart"] = True

    # Internals:
    def _new_flow(self, interval: int, window_sec: int, now: float) -> dict:
        slots = max(self.MIN_WINDOW_SLOTS, round(window_sec / interval))
        return {
            "interval":     interval,
            "window_slots": slots,
            "last":         now,
            "rx":           1,    # on-schedule receptions
            "missed":       0,    # inferred losses
            "early":        0,    # off-cadence extra receptions
            "charged":      0,    # losses sweep() already billed for this gap
            "restart":      False,  # next reception starts a new grid (post-reboot)
            "recent":       collections.deque([1], maxlen=slots),
        }

    @staticmethod
    def _snapshot(f: dict, gap_s, missed_now: int) -> dict:
        slots  = f["rx"] + f["missed"]
        window = f["recent"]
        return {
            "pdr":               round(f["rx"] / slots, 4) if slots >= 2 else None,
            "pdr_window":        round(sum(window) / len(window), 4) if window else None,
            "pdr_window_slots":  f["window_slots"],
            "pdr_window_filled": len(window),
            "rx_count":          f["rx"],
            "missed_est":        f["missed"],
            "missed_now":        missed_now,
            "early_count":       f["early"],
            "cadence_violated":  int(f["early"] > 0),
            "gap_s":             gap_s,
        }
