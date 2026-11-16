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

## 3. N1 and N3: environment sensor out of service

- **Reported:** 2026-11-10, in `sasipa/rapa-nui`. **To design:** what failed,
  and where the gateway should learn that a sensor is out of service.
- **Known:** the SHT4X of N1 (`!0b64122b`) and of N3 (`!32fe0d4e`) does not
  work. That leaves N2 as the only node with temperature and humidity not
  reported broken. How they fail is not recorded yet: no environment packets
  at all, or packets with wrong readings.
- **Today:**
  - Their dashboards show no temperature or humidity charts, and say why:
    `MONITOR_ENVIRONMENT_OUT_OF_SERVICE=N1,N3` in the host's `.env`, read by
    the `web` container. `.env` is not in git: the line is added by hand on
    each host.
  - Nothing else changes. The deployment file still gives both nodes an
    SHT4X and a 120 s `environment` cadence: it is the platform's, and stays
    identical here (G10). So:
    - whatever environment packets they send is still published and stored,
      and `tools/plot_history.py` still plots it;
    - if they send none, a receiver that heard the flow since it started
      charges a missed packet every 120 s: a `[PDR] N1/environment silent`
      line and a falling `pdr` in the `pdr` measurement. After a restart, a
      flow never heard is not measured, and stays quiet.
- **To decide:**
  1. **What failed:** the sensor, its Grove cable, or the firmware not finding
     it at boot. The node's serial log at boot lists the I2C devices the
     firmware found; the file puts the SHT4X at `0x44`.
  2. **Where "out of service" belongs:**

     | Option | Gives | Costs |
     |---|---|---|
     | The platform's file drops `environment` from the two nodes' `intervals` and the SHT4X from their `sensors`; copied here | One description of the mesh. The charts go with no setting, and the receiver stops measuring a flow that does not exist | The file no longer records that the hardware is mounted. Check what the platform's `provision` and `inspect` do with a node that loses its `environment` flow |
     | A status on the sensor in the platform's schema (`status: faulty`), read by the gateway | Keeps the record that the sensor is mounted, and why its data is missing | A schema change in the platform, whose loader rejects unknown keys |
     | Keep it in `.env`, as today | Changed on site in a minute | One host only, not in git; the receiver still measures the flow |

  3. **When a sensor is fixed or replaced:** take its ref out of
     `MONITOR_ENVIRONMENT_OUT_OF_SERVICE` and run `docker compose up -d web`.
     The charts come back, with every point stored meanwhile.

## 4. The stored data, exported by SASIPA's engineers

- **Asked:** 2026-11-10, for `sasipa/rapa-nui`.
- **Goal:** the engineers at SASIPA's centralizer, where the gateway host is,
  take the data it has stored and send it over the internet.
- **Today:** the data is in InfluxDB on the host's SD card, one copy. Only the
  dashboard reaches it from the network, the host has no internet, and
  `tools/plot_history.py --export` runs on the host, over SSH.
- **Proposal, steps and decisions:**
  [architecture/data-export.md](architecture/data-export.md).
