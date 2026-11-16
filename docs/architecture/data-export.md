# Exporting the stored data

The engineers at SASIPA's centralizer, where the gateway host is, take the
data the gateway has stored and send it over the internet. This is a proposal:
nothing in it is built ([future-work.md](../future-work.md) §4).

---

## 1. What exists today

- **Everything published is stored.** Telegraf writes every payload to
  InfluxDB: `telemetry`, `pdr`, `message`, `nodeinfo` and `neighbor`
  ([design.md](../design.md) §2.5). The database has no retention policy:
  nothing is deleted.
- **One copy, on the host's SD card** (the `influxdb_data` volume). A card
  that fails loses everything not copied elsewhere.
- **Only the dashboard reaches it from the network**, behind the login (G13);
  InfluxDB listens on the host's localhost. `tools/plot_history.py --export`
  writes a CSV, but it runs on the host, over SSH, in a Python environment
  with matplotlib and pandas, and it exports telemetry fields only: not a tool
  for the engineers.
- **The host has no internet.** It boots as its own WiFi access point and has
  no Ethernet ([field-hotspot.md](../field-hotspot.md)). Joining another
  network is done by hand and lasts until the next boot.
- **Its clock is set by hand.** With no internet and no battery-backed clock,
  the host boots at the time it was switched off, and until someone sets it
  from a laptop (field-hotspot.md §4) every record lands in the past. An
  export is only as good as those timestamps.
- **Two points of one node in the same second overwrite each other**: the time
  key, `received_at`, is in whole seconds (open since 2026-10-27,
  [session-log.md](../session-log.md)). An export carries what is stored,
  merged points included.

## 2. The proposal

Two phases. The first works with the host as it is today. The second needs
internet at the centralizer, and takes the person out of the loop.

### 2.1 Phase 1: download from the dashboard, send from anywhere

```
laptop ── WiFi meshtastic-gw ──► http://10.42.0.1/export ──► <mesh>_<from>_<to>.zip
laptop, later, on any network with internet ──► shared folder (or email) ──► you
```

The engineer joins the host's WiFi as for the dashboard, logs in, picks a
range of dates and downloads one ZIP. They send it from any network with
internet: the host never needs it.

| File in the ZIP | What it holds |
|---|---|
| `telemetry.csv` | Every `device`, `environment` and `position` point, PDR block included |
| `pdr.csv` | The sweep's PDR snapshots, for flows gone silent |
| `nodeinfo.csv`, `neighbor.csv` | What each node says it is; the radios each node hears |
| `messages.csv` | As the Messages page shows them: a PBX frame's phone numbers masked |
| `deployment.yaml` | The deployment file the data was measured against: names, cadences |
| `manifest.json` | The range asked, the rows and SHA-256 of each file, the deployment's SHA-256, the host's clock and the laptop's at export time |
| `README.txt` | How to read the columns (below) |

One row per stored point, its tags and fields as columns, with the names of
design.md §2 (G1). `time` in UTC, ISO 8601: Rapa Nui is UTC−6 (UTC−5 in
summer), and the files never mix the two.

**Rules it keeps:**

- **No new door.** The page sits behind the same login and reads with the
  dashboard's read-only InfluxDB account: no new port, container, account or
  credential (G11, G13).
- **It never shows more than the dashboard** (G12): phone numbers masked by
  `for_browser()`, as on the Messages page.
- **It fails loudly.** A query that fails stops the download with the reason,
  as the APIs answer 503: never a ZIP with an empty file. The manifest counts
  the rows of each file, so "no data in that range" cannot pass for "lost on
  the way".
- **Omit, never zero** (G2) survives in a CSV only as an empty cell.
  `README.txt` says so, and that an empty `pdr` means "not measured yet"
  (fewer than two slots): the ambiguity that keeps the PDR block out of
  `plot_history.py --export`.
- **Bounded on a Raspberry Pi.** One day of one measurement per query, written
  into the ZIP as it streams: a long range never holds the whole history in
  memory.
- **The clock is checked first.** The page compares the host's clock with the
  laptop's and, off by more than a minute, says so before anything is
  downloaded. Data stored before the clock was set sits in the past, and a
  range of dates would miss it or misplace it.

**Size.** At the cadences of `rapa-nui.yaml`, with every packet arriving: some
6,800 telemetry points a day (device 6 × 720, environment 3 × 720, position
6 × 24 and 2 × 96). At roughly 250 bytes per CSV row that is about 1.7 MB a
day and 50 MB a month, which a ZIP compresses several times over: in the
order of 5–10 MB a month. An estimate, to measure once built. A month fits in
an email (25 MB on Gmail); a shared folder has no such limit.

**How it reaches you.** A shared folder you own (Google Drive or OneDrive),
where the engineers upload each ZIP: no size limit, and the files stay
together with their dates. Email works for a month or less.

**Overlap.** Two exports may cover the same days: the same point appears in
both, with the same time and tags, which is a point's identity in InfluxDB.
A tool on your side, `tools/import_export.py`, merges ZIPs into one dataset
and drops the repeats, or loads them into a local InfluxDB, so that
`plot_history.py` and the dashboard work on your copy as they do on the host.

### 2.2 Phase 2: the host uploads by itself

It needs internet at the centralizer **beside** the access point: an Ethernet
cable from SASIPA's network, or a USB WiFi adapter, while `wlan0` stays the
access point (field-hotspot.md, "Good to know"). Then:

- A daily timer on the host builds the same ZIP and uploads it to the same
  shared folder (rclone covers Google Drive, OneDrive, S3 and SFTP). The
  export page stays, for a range on demand.
- Only outbound connections: no port opens toward the host, and G13 holds.
  The destination's credential lives in `secrets/`, never in git (G9).
- The host gets NTP: the clock stops depending on someone with a laptop.
- An upload that fails is retried, and shows on the dashboard ("last upload:
  3 days ago"), not only in a log nobody reads.

Remote access to the host (a VPN) would let you fetch the data yourself, but
it opens the host to the internet: a larger decision, outside this proposal.

### 2.3 A copy that survives the SD card

Every export sent is also an off-site copy of the days it covers. To restore
the database as it was, InfluxDB's own `influxd backup -portable`, run on the
host with the admin account (maintenance only, design.md §2.6), can write a
weekly backup to a USB drive left plugged in. Independent of the export, and
optional.

## 3. Decisions to take

1. **Where the files go:** a shared folder you own (proposed), or email.
2. **Messages across the internet.** Masked numbers and the text, as the
   dashboard shows them (the proposal's default); or no messages in the
   export: the text of real people's messages would leave the island in a
   file.
3. **Format:** CSV, read by Excel and pandas (proposed); or InfluxDB line
   protocol, which restores into InfluxDB exactly but is unreadable without
   tools.
4. **How often, and who.** For instance every week, the last 8 days (a day of
   overlap), by a named engineer.
5. **Phase 2:** is there an Ethernet port, or room for a USB adapter, at the
   centralizer?
6. **The engineers' guide**, in Spanish: join the WiFi, set the clock, export,
   upload. A page in `docs/`, or printed beside the host.

## 4. What to build, phase 1

1. `InfluxDBConnector`: the rows of one measurement over one day, every field
   and tag, with the read account.
2. `/export`, the page: the range, the clock check, the rows per measurement
   before downloading. `/api/export?from=&to=`, the ZIP, streamed, over a
   bounded range.
3. Masking with `for_browser()`; the CSV columns pinned by a golden test, as
   the payloads are (G1).
4. Tests, as for the other APIs: dates validated, a database failure answers
   503 and sends no ZIP, numbers masked, row counts in the manifest.
5. On your side, `tools/import_export.py`.
6. The engineers' guide.

It touches the `web` service only, with no new dependency (`zipfile` and `csv`
are in Python's standard library), so the host rebuilds it without internet:
`docker compose up -d --build web`.
