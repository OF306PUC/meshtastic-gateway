# Design: boundary, published contract, invariants

What the gateway is responsible for, what it promises to the systems that read
its data, and the rules a change must not break. The reasons behind each rule
are kept with it: most of them were learned from a silent failure.

> **The platform configures the mesh. The gateway decodes what the mesh sends,
> decides what it *means over time*, and where it goes.**

The code was ported from the `meshtastic-testbed-platform` monorepo
(`src/gateway/`, `monitor/`, `telegraf/`, `mqtt/`, `src/tools/`); the decoder
was forked from `meshtastic-platform`'s `decode/`. The chronology is in
[`session-log.md`](session-log.md).

---

## 1. The boundary with `meshtastic-platform`

| Belongs to the platform | Belongs to the gateway |
|---|---|
| Radio profile, registry validation, regulatory limits, provisioning, inspection | Its own `decode()` (pure: no clock, no I/O) and everything that needs a clock, a socket or a disk |
| Its own `decode()`, for the channel-study receiver | PDR, deduplication, MQTT, Telegraf, InfluxDB, the dashboard |
| What a radio is *configured* with | What a reception is *called* on the wire and in the database |

**No code dependency, by decision (2026-10-26).**

- **The gateway owns its decoder.** `gateway/decode.py` is a fork of the
  platform's, so the gateway can adapt it. The two copies are **not** kept in
  sync: a fix in one is not a fix in the other.
- **Configured by data.** Each container runs one entry point; its settings
  come from `deployments/` (the mesh) and `.env` (everything else: topic
  prefix, PDR window and sweep). Nothing gateway-specific goes into a
  deployment file: it must stay byte-identical to the platform's copy, whose
  loader rejects unknown keys.
- **Paired only through deployment membership.** The same deployment file
  lives in both repositories, kept identical by hand (G10,
  [`deployments/README.md`](../deployments/README.md)). The platform lists this
  repository as a submodule for reference only.
- Rejected: installing the platform (it is not installable), `sys.path` /
  `PYTHONPATH` tricks, holding the platform as a submodule or copying it from a
  checkout, fetching it at build time (one decoder, but not adaptable).

`tests/test_hard_rules.py` enforces it: no `meshtastic_platform` import and no
`sys.path` manipulation anywhere here. The platform has the mirror rule: no
mention of MQTT, InfluxDB, Telegraf or Docker in its sources.

---

## 2. The published contract

The gateway's most important asset: Telegraf, InfluxDB and the dashboard read
these names. A renamed field is dropped downstream **without an error**. The
names were captured from the running monorepo code, and the golden tests
(`tests/test_payload_golden.py`) pin them.

### 2.1 Fields

| Payload | Fields |
|---|---|
| `environment` | `node_id, node_label, temperature, humidity, rssi, snr, hop, channel, device_ts, received_at` |
| `device` | `node_id, node_label, battery_level, voltage, channel_util, air_util_tx, uptime_seconds, rssi, snr, hop, channel, device_ts, received_at` |
| `position` | `node_id, node_label, latitude, longitude, altitude, rssi, snr, hop, channel, device_ts, received_at` |
| `message` | `node_id, node_label, portnum, pkt_id, src_id, dst_id, fw_ver, content_len, payload_len, malformed, rssi, snr, hop, channel, received_at` |
| PDR, on the three telemetry payloads and the `pdr` topic | `pdr, pdr_window, pdr_window_slots, pdr_window_filled, rx_count, missed_est, missed_now, early_count, cadence_violated, gap_s` (the `pdr` topic adds `node_label, flow, source`) |

The field is **`humidity`**, not the protobuf's `relativeHumidity`.

A message is shaped differently, on purpose:

| Difference from telemetry | Why |
|---|---|
| No `device_ts` | A message has no device timestamp, only `received_at` |
| No PDR fields | Phone traffic is aperiodic: there is no cadence to measure against |
| `pkt_id` present | The only handle for joining a transmit record to a receive record |
| `src_id` / `dst_id` are strings | Phone numbers without country code, a big-endian uint32 on the wire, in decimal: `"123456789"` logs as `+56123456789` |
| `dst_id` is `null` on broadcast, not absent | It is a Telegraf tag; omission would change the series (G3b) |
| `malformed` is `0` or `1` | An integer boolean (2.2) |
| `content_len` ≠ `payload_len` | The text vs the whole LoRa payload, frame header included: 9 bytes routed (`PRIVATE_APP`), 5 broadcast (`TEXT_MESSAGE_APP`) |

The text of a message is logged to the receiver's terminal (`[MSG]` lines,
control characters escaped) and never published unless `capture_content`.

### 2.2 Two rules that look like bugs and are not

- **Omit, never zero (G2).** An absent metric is left out of the payload, not
  published as `0`: `humidity` is absent when the node has no sensor. A `0`
  would be indistinguishable from a real zero reading.
- **Booleans publish as integers (G3).** `cadence_violated` and `malformed`
  are `0` or `1`. Telegraf's JSON parser drops `true`/`false` without an error.

### 2.3 Deliberate departures from the monorepo's values

Names are unchanged; three values differ on purpose, so on these fields data
recorded before and after the port is not comparable.

| Field | Monorepo | Gateway | Why |
|---|---|---|---|
| `hop` (D1) | `None` when `hopLimit` is absent | `hopStart` | protobuf3 omits a zero: the packet used every hop. With `hop_limit: 1`, every relayed packet |
| `snr` (D2) | `None` when `rxSnr` is absent | `0.0` | Same reason: 0.0 dB is an ordinary reading. Still `None` without RSSI |
| `device_ts` | The host clock when the node sent no time | The flow's previous `device_ts`, or omitted | The host clock passed for the node's (G3c) |

Checked against the monorepo's running `MeshReceiver`: these are the only
differences (37 payload cases, and a 24-event replay with PDR, reboots and
sweeps).

### 2.4 Topics

```
{prefix}/{node_label}/position
{prefix}/{node_label}/device
{prefix}/{node_label}/environment
{prefix}/{node_label}/message
{prefix}/{node_label}/pdr
```

`{prefix}` is `MQTT_TOPIC_PREFIX` in `.env`: required, never defaulted (two
deployments under one prefix interleave silently), letters, digits, `.`, `_`
and `-` only, because Telegraf's config and the broker ACL substitute it.
`node_label` is the deployment's `label`, or `ref` when there is none.

### 2.5 Measurements

Telegraf maps topics to measurements. Changing a topic without changing
Telegraf loses data silently: the broker accepts the publish and nothing
consumes it (G4).

| Measurement | From topics | Tags |
|---|---|---|
| `telemetry` | `position`, `device`, `environment` | `node_id`, `node_label` |
| `pbx_message` | `message` | `node_id`, `node_label`, `portnum`, `channel`, `src_id`, `dst_id` |
| `pdr` | `pdr` | `node_label`, `flow`, `source` |

Tags are not fields: a tag is an indexed dimension, and promoting a field to a
tag changes the schema in a way that cannot be undone in place. `received_at`
is the time key everywhere.

### 2.6 Accounts and ports

The layout is drawn in [`diagrams/port-architecture.png`](diagrams/port-architecture.png).

| Account | May |
|---|---|
| MQTT `gateway` | write `{prefix}/#` |
| MQTT `telegraf` | read `{prefix}/#` |
| MQTT `monitor` | read `{prefix}/+/position`, `device`, `environment` only: messages hold phone numbers, and the live feed reaches every browser (G12) |
| InfluxDB write account | Telegraf's writes |
| InfluxDB read account | the dashboard and `tools/plot_history.py` |
| InfluxDB admin | maintenance only |
| Dashboard login | the proxy's basic auth |

- **Only the proxy is reachable from the network (G13).** The dashboard (5000),
  InfluxDB (8086) and the broker (1883) listen on the host's localhost only.
  Plain HTTP: offline there is no certificate a browser would trust, so the
  field WiFi's WPA2 protects the login.
- **One run creates every credential (G5).** `mqtt/init-credentials.sh` writes
  `mqtt/pwfile` and `secrets/<service>.env` together, each container receiving
  only its own (G9), and refuses to overwrite either. If the two disagree,
  every container starts, the dashboard renders, and no data arrives: `rc=5` /
  `not authorised` in the broker log. That is the first entry of
  [`troubleshooting.md`](troubleshooting.md).
- The ACL is rendered from `mqtt/aclfile.template` at every broker start, from
  the same `MQTT_TOPIC_PREFIX`. The broker drops a publish its ACL forbids
  **without logging it**.

---

## 3. The PDR estimator

`gateway/pdr.py` (`CadencePdrTracker`) was ported unchanged; its design is
explained in [`architecture/pdr-cadence-tracker.md`](architecture/pdr-cadence-tracker.md)
(in Spanish, deliberately). The invariants that look like simplifications
waiting to happen, and are not (G7):

| Invariant | Why it exists |
|---|---|
| Monotonic clock for every `dt` | An NTP step on the host would fabricate losses on every flow at once |
| `round()`, not `floor()`, for slot counting | Firmware jitter is symmetric around the cadence; `floor` turns every late packet into a loss |
| `sweep()` charges losses during silence | Otherwise a dead node freezes its PDR at the last good value |
| `charged` prevents double counting | `sweep()` bills provisionally; `observe()` charges only the difference |
| `reanchor()` on a falling `uptimeSeconds`, with the `restart` flag | A reboot is not a radio loss, and its own packet is not an early arrival (regression test) |
| `pdr` is `None` after one packet | One sample carries no delivery information |
| Deduplication is measurement, not decoding | A counted rebroadcast inflates the ratio; `decode()` must not deduplicate |
| A flow with no declared cadence is not measured | Measuring against a cadence a node never had fabricates 100 % loss |

`cadence_violated` / `early_count` is the model's own alarm: `pdr` cannot
exceed 1 by construction, so a wrong cadence shows up as early arrivals. The
usual cause is smart position broadcast left on; the measurement is invalid
until it is fixed.

---

## 4. The receiver

```python
decoded = decode(packet, known_nodes=nodes)      # nodes from deployments/
if not decoded.known:                           # count, warn once, do not publish
    ...
if decoded.packet_id in seen:                   # dedup is gateway policy
    return
for flow in decoded.flows:                      # 'device' | 'environment' | 'position'
    pdr = tracker.observe((label, flow), interval, window, time.monotonic())
    publish(label, flow, to_payload(decoded, flow, label, received_at, pdr,
                                    held_device_ts=last_device_ts[(node_id, flow)]))
```

- `to_payload()` is where the field-name contract lives: pure, `DecodedPacket
  -> dict`, no clock, no I/O.
- Messages skip the PDR step: decode → dedup → `to_message_payload()` → publish.
- **The first 10 s after start-up are published but not scored.** Opening the
  serial port restarts the radio, which then hands over, at once, the packets
  it held while nothing was connected: their arrival times say nothing about
  the cadence, and scored they raise a false `cadence_violated` (seen on the
  office bench, 2026-10-27). The report counts them (`pdr_unscored_at_startup`).
- The gateway radio stays `CLIENT_MUTE` (G6): if it rebroadcasts, it
  contaminates its own measurement. The platform provisions it and its
  inspector checks it; the receiver warns at start if it is not.

---

## 5. Invariants

| # | Invariant | How it is checked |
|---|---|---|
| G1 | Published field names unchanged | `tests/test_payload_golden.py` |
| G2 | Omit-not-zero for absent metrics | `tests/test_payload_contract.py::TestOmitNotZero` |
| G3 | Booleans publish as integers | `TestBooleanFieldsArePublishedAsIntegers` |
| G3b | `dst_id` is `null` on broadcast, not omitted | `TestBroadcastMessageFrame` |
| G3c | `device_ts` is never the host clock | `TestDeviceTs` |
| G4 | Topics, Telegraf and the ACL agree on the prefix and the kinds | `tests/test_infrastructure.py` |
| G5 | `mqtt/pwfile` and `secrets/` from one run of `init-credentials.sh` | `rc=5` / `not authorised` in the broker log; the script refuses partial runs |
| G6 | Gateway radio in `CLIENT_MUTE` | The platform's inspector; the receiver's start-up warning |
| G7 | `CadencePdrTracker` tests pass unchanged | `tests/test_pdr_tracker.py`, `restart` regression included |
| G8 | No import of the platform's code | `tests/test_hard_rules.py` |
| G9 | No secrets in git; each container gets only its own credentials | `.gitignore`; `TestCredentialsPerService` |
| G10 | Each deployment file identical to the platform's copy | Same SHA-256; the receiver prints it at start and warns on unknown senders, undeclared flows and `cadence_violated` |
| G11 | InfluxDB requires authentication; least-privilege accounts | `TestHardening` |
| G12 | The live feed carries telemetry only, never messages | `TestHardening`, `test_acl_rules` |
| G13 | Only the proxy is reachable from the network, behind a login | `TestHardening` |

> **This system's failure mode is silence**: containers up, dashboard
> rendering, tools exiting zero, no data. Every component must **fail loudly or
> report what it discarded**. `DecodeStats` and `_extra()` in
> `gateway/decode.py` are the pattern: unknown fields are counted and kept.

---

## 6. Decided out, and deferred

- **No PBX-site collectors** (2026-10-26). `node_logd` / `pbx_logd`, the `pbx`
  topic, the `pbx_health` measurement and the `p1`/`p2` broker accounts are not
  part of this implementation. What that gives up: without them a low message
  delivery cannot be split into a BLE loss, a UART handoff loss and an
  over-the-air loss.
- **Where the PBX radio belongs is deferred.** The platform now has a `pbx`
  function and configures only that radio's mesh membership; its link to the
  PBX belongs to the PBX project. The gateway keeps `pbx_message` (the frames
  it hears) and does not provision PBX radios.
- **The offline map covers two boxes** (2026-10-29): San Joaquín and Rapa Nui,
  cut into `monitor/static/maps/` by its `fetch.sh` (an OpenStreetMap basemap
  from Protomaps; GEBCO 2020 depth contours around Rapa Nui). Elsewhere the map
  is blank, markers still placed: a new site means a new box in `fetch.sh` and
  a re-run. GEBCO's 450 m grid makes the contours near the coast approximate.
