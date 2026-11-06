# Future work

Features asked for and not built yet. Each entry says how urgent it is, which
deployment it is for, and what exists today. Detailed designs live in
`docs/architecture/`.

---

## 1. Sending to one node, confirmed by its ACK

- **Asked:** 2026-11-05. **Urgent.** **Not for Rapa Nui:** `sasipa/rapa-nui`
  stays receive-only.
- **Goal:** the gateway sends a message addressed to one node and learns from
  the ROUTING_APP acknowledgement whether that node received it.
- **Today:** the gateway never transmits. When a message is addressed to the
  gateway, its radio ACKs it without involving the computer. A ROUTING_APP
  that reaches the receiver is counted, not published or stored.
- **Design, firmware facts and open decisions:**
  [architecture/acknowledged-sends.md](architecture/acknowledged-sends.md).

## 2. A live PDR view, per cadence

- **Asked:** 2026-11-05.
- **Goal:** the dashboard shows each flow's PDR as it is computed. A flow is
  one node's `device`, `environment` or `position` packets, each with the
  cadence the deployment file declares for it.
- **Today:** the data exists, but no page shows it.
  - The receiver estimates the PDR of every flow against its cadence
    ([architecture/pdr-cadence-tracker.md](architecture/pdr-cadence-tracker.md)).
  - Each telemetry and position payload carries the PDR block: `pdr`,
    `pdr_window`, `pdr_window_slots`, `pdr_window_filled` and `missed_est`,
    among others. They are stored in the `telemetry` measurement.
  - When a flow falls silent, the sweep publishes
    `{prefix}/<node>/pdr`, stored in the `pdr` measurement with the tags
    `node_label`, `flow` and `source`.
  - The dashboard reads none of it. The live feed subscribes only to
    `position`, `device`, `environment` and `message`, and no API returns
    PDR. `tools/plot_history.py` leaves the PDR block out on purpose.
- **To build:**
  1. **An API for the PDR history.** It returns each flow's PDR over time,
     with the flow's cadence from the deployment file.
  2. **Live updates.** The monitor subscribes to `{prefix}/+/pdr` as well, and
     pushes the PDR block of each telemetry and position payload.
  3. **A view.** It shows one row or chart per flow, with the cadence beside
     it.
  4. **Tests,** as for the other APIs: input validation, and a database
     failure answering 503, not an empty list.
- **Decisions to take:**
  - **Which figure leads.** `pdr` counts every slot since the receiver first
    heard the flow, and starts over when the receiver restarts. `pdr_window`
    covers only the last slots that fit in `PDR_WINDOW_SEC` (or
    `PDR_WINDOW_SEC_<FLOW>`), 3600 s by default.
  - **What a null means.** `pdr` is null until two slots are measured. The
    view must say "not measured yet", not draw a zero or a gap.
  - **Reboots and early packets.** A reboot re-anchors the flow and its
    downtime is not counted as loss. A packet early inside its cadence
    (`cadence_violated`) makes the measurement invalid. The view should
    show both, not hide them.
  - **Where it lives.** Choose between a page of its own across nodes and a
    chart on each node's dashboard.
