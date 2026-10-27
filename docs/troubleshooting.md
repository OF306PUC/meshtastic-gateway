# Troubleshooting

Organised by **symptom**, because that is what you have when you arrive here.

Almost everything in this catalogue is a *quiet* failure: the containers stay up,
the dashboard renders, the tool exits zero, and nothing is obviously broken. A
mesh testbed has many places where the honest outcome is "no data", and "no
data" looks identical whether the cause is a wrong password, a wrong topic
prefix or a genuinely silent radio. Each entry says how to tell the difference.

| Symptom | Section |
|---|---|
| Containers up, dashboard renders, no data at all | [Nothing arrives and nothing errors](#nothing-arrives-and-nothing-errors) |
| The broker shows traffic, InfluxDB stays empty | [Published, never stored](#published-never-stored) |
| Credentials need to change, or no longer belong together | [Rotating the credentials](#rotating-the-credentials) |
| `gateway-receiver` keeps restarting | [The gateway restarts in a loop](#the-gateway-restarts-in-a-loop) |
| `WARNING` lines in the gateway log | [Drift warnings](#drift-warnings) |
| Map says `Error loading nodes`, or the dashboard `History unavailable` | [The dashboard cannot query InfluxDB](#the-dashboard-cannot-query-influxdb) |
| The dashboard rejects every password, or the proxy will not start | [The dashboard login](#the-dashboard-login) |
| Dashboard loads, never updates live | [No live updates in the dashboard](#no-live-updates-in-the-dashboard) |
| Gateway healthy, hears nothing | [The gateway is on the wrong serial port](#the-gateway-is-on-the-wrong-serial-port) |
| `pip`, `apt` or `docker pull` fail on certificates | [A Raspberry Pi with a stale clock](#a-raspberry-pi-with-a-stale-clock) |
| Data written, dashboard shows nothing recent | [Measurements landing in the past](#measurements-landing-in-the-past) |
| A code change has no effect | [Compose restarted the old image](#compose-restarted-the-old-image) |
| `unknown shorthand flag: 'd' in -d` | [Compose v2 is not installed](#compose-v2-is-not-installed) |
| Serial port busy, or the board reboots when you connect | [Serial port contention](#serial-port-contention) |
| No temperature from a sensor, identical positions | [Node-side symptoms](#node-side-symptoms) |

---

## Nothing arrives and nothing errors

**Symptom.** `docker compose ps` shows every service `Up`, the dashboard loads,
and there is no data anywhere.

Almost always credentials (G5), and quiet by design: the broker refuses
anonymous clients, the refused clients keep retrying, and nothing crashes.

```bash
docker compose logs telegraf | grep -i connect          # expect one Connected per input (3)
docker compose logs gateway-receiver | grep -i mqtt     # expect "Connected to broker!"
docker compose logs mosquitto | grep -i "not authori"
```

The gateway names the cause itself: `Could not connect ... Not authorized —
mqtt/pwfile and secrets/ must come from the same run of mqtt/init-credentials.sh`.
`rc=5` or `not authorised` in any log means a password in `secrets/` does not
match its hash in `mqtt/pwfile`. The script creates both in one run and refuses
to overwrite either, so this happens when one was copied from another host or
restored from a backup without the other. Recreate both together: see
[Rotating the credentials](#rotating-the-credentials).

If the code was just updated, rebuild before re-checking: see
[Compose restarted the old image](#compose-restarted-the-old-image).

To separate "the broker never got it" from "the database never stored it",
watch the broker directly with Telegraf's account, which reads everything
(`MQTT_TOPIC_PREFIX` from `.env`):

```bash
set -a; . ./.env; . ./secrets/telegraf.env; set +a
docker compose exec mosquitto mosquitto_sub \
  -t "$MQTT_TOPIC_PREFIX/#" -v -u telegraf -P "$MQTT_PASSWORD_TELEGRAF"
```

Traffic here but empty measurements: see
[Published, never stored](#published-never-stored).

---

## Published, never stored

**Symptom.** The gateway log shows `[MQTT] →` lines, the broker shows traffic,
and InfluxDB has nothing (or not everything).

The broker accepts a publish that nobody consumes, and it **drops a publish its
ACL forbids without logging it** — the publisher gets no error either (MQTT
3.1.1 has no way to say so). Three things must agree on the topic prefix (G4):

| Who | Where it comes from |
|---|---|
| The gateway publishes under | `MQTT_TOPIC_PREFIX` in `.env` |
| Telegraf subscribes to | the same variable, substituted into `telegraf/etc/telegraf.conf` |
| The broker ACL allows | the same variable, rendered from `mqtt/aclfile.template` at every broker start |

All three read the one variable, but each reads it **when its container
starts**. After changing `.env`, recreate them all:

```bash
docker compose up -d --force-recreate
docker compose exec mosquitto grep -E "^(user|topic)" /mosquitto/aclfile   # the rendered ACL
```

Only the `gateway` account may write: a publish from any other account is
dropped the same way, on purpose, so a leaked reader password cannot inject data.

---

## The gateway restarts in a loop

**Symptom.** `docker compose ps` shows `gateway-receiver` restarting.

The receiver exits on purpose rather than run without data; the last lines of
its log say why:

```bash
docker compose logs --tail 30 gateway-receiver
```

| Exit | Meaning |
|---|---|
| 2 | Configuration: a required setting is missing (`MQTT_TOPIC_PREFIX`, `MESH_DEPLOYMENT`, `GATEWAY_SERIAL_PORT`), a value is invalid, or the deployment file is missing or invalid. The message names it |
| 1 | The radio: the serial link was lost (`lost the serial link to the radio`), or the device is not a Meshtastic radio (a traceback ending in the serial library) |

Compose itself refuses to start without the three required settings
(`required variable ... is missing a value`).

---

## Drift warnings

**Symptom.** `[MESH] WARNING` or `[PDR] WARNING` lines in the gateway log.

The gateway's `deployments/` file and the platform's copy must be byte-identical
(G10, [`deployments/README.md`](../deployments/README.md)). Each warning is
printed once, and the periodic `[GW] Report` counts what was discarded and why.

| Warning | Usual cause |
|---|---|
| `!xxxxxxxx is not in the deployment file` | A node missing from this copy, or another mesh on the same channel |
| `sends <flow> but ... declares no cadence` | The radio emits a flow this copy does not declare: the copies differ, or the radio was provisioned from a different file |
| `arrived ... inside its N s cadence` | `cadence_violated`: smart position broadcast left on, or a cadence that differs from the radio's. **The PDR is invalid until fixed** |
| `this radio ... is not in` / `not 'gateway'` / `not CLIENT_MUTE` | See [the wrong serial port](#the-gateway-is-on-the-wrong-serial-port) |

Compare the two copies with `sha256sum`; the gateway prints its own at start.

---

## The dashboard cannot query InfluxDB

**Symptom.** The map's status bar reads `Error loading nodes: InfluxDB query
failed: ...`, or a node's dashboard shows `History unavailable`.

The API answers `503` with the reason instead of an empty list, so this is the
database, not an empty mesh. Usual causes: `influxdb` is down or still
starting, or the read account in `secrets/web.env` does not match the
database. The accounts are created on influxdb's **first** start only: new
credentials afterwards do not change them, and every query then fails with
`authorization failed` — see [Rotating the credentials](#rotating-the-credentials).

```bash
docker compose ps influxdb
docker compose logs web | grep "\[DB\]"      # the start-up check says what it found
```

It recovers by itself once InfluxDB answers: every request retries. A
`WARNING: InfluxDB unreachable` at the dashboard's start is normal when it
comes up before the database.

---

## Rotating the credentials

**When.** A password leaked, or `mqtt/pwfile` and `secrets/` no longer belong
together.

`./mqtt/init-credentials.sh` refuses to run while either exists: credentials
are created together or not at all. Before InfluxDB's first start, delete both
and run it again. After it, InfluxDB keeps the accounts it created, so their
passwords also have to change inside the database — with the **old** admin
password, which disappears with the old `secrets/`:

```bash
OLD=$(grep '^INFLUXDB_ADMIN_PASSWORD=' secrets/influxdb.env | cut -d= -f2)
rm -r secrets && sudo rm mqtt/pwfile        # pwfile belongs to uid 1883
./mqtt/init-credentials.sh
. ./secrets/influxdb.env
for u in "$INFLUXDB_ADMIN_USER:$INFLUXDB_ADMIN_PASSWORD" \
         "$INFLUXDB_WRITE_USER:$INFLUXDB_WRITE_USER_PASSWORD" \
         "$INFLUXDB_READ_USER:$INFLUXDB_READ_USER_PASSWORD"; do
  docker compose exec -T influxdb influx -username admin -password "$OLD" \
    -execute "SET PASSWORD FOR \"${u%%:*}\" = '${u#*:}'"
done
docker compose up -d --force-recreate
```

If the data can go, `docker compose down -v` instead deletes the database (and
every measurement in it); the next start creates the accounts afresh.

---

## The dashboard login

**Symptom.** The browser asks for a user and password and rejects every one, or
`docker compose ps` shows `proxy` restarting.

The proxy (`proxy/Caddyfile`) is the only service open to the network, and it
asks for `DASHBOARD_USER` with the password whose bcrypt hash is
`DASHBOARD_PASSWORD_HASH` in `secrets/proxy.env`. `./mqtt/init-credentials.sh`
prints the password **once**; it is stored nowhere.

- **Every password rejected:** the hash lost its single quotes. Unquoted,
  docker compose expands the `$` signs inside it (only a warning on the
  console) and no password can match. It must read
  `DASHBOARD_PASSWORD_HASH='$2a$14$...'`.
- **`proxy` restarting:** `docker compose logs proxy` names it — an empty user
  or a hash that is not bcrypt. Caddy refuses to start rather than serve the
  dashboard without a login.
- **Password lost:** make a new one and its hash, paste the hash (quoted), and
  recreate the proxy:

```bash
docker run --rm caddy:2.10-alpine caddy hash-password --plaintext '<new password>'
docker compose up -d --force-recreate proxy
```

---

## No live updates in the dashboard

**Symptom.** The pages load and the history charts fill, but nothing updates
live and the dot in the dashboard's header stays grey.

The live feed (Socket.IO) accepts the page's own origin — whatever address the
browser used to reach the proxy — and refuses any other with HTTP 400 while the
pages still load. If `MONITOR_ALLOWED_ORIGINS` is set in `.env`, it replaces
that rule with its own list: unset it, or add the address exactly as the
browser shows it (`scheme://host:port`), then
`docker compose up -d --force-recreate web`.

If the origin is right and still nothing arrives, check the feed itself:
`docker compose logs web | grep MQTT` should show `subscribed → <prefix>/+/device`
(and `position`, `environment`).

---

## The gateway is on the wrong serial port

**Symptom.** `gateway-receiver` is `Up`, and no mesh traffic ever arrives — or
it starts with `WARNING: this radio (...) is not in <deployment>.yaml`, `is N1
... declared as function 'node'`, or `role is CLIENT, not CLIENT_MUTE`.

`ttyACM*` numbering is assignment order, not identity: it changes between
reboots and depends on what else is plugged in. Pointed at a node instead of the
gateway radio, the container opens it and listens to the wrong radio. The
start-up warnings above are how the gateway notices.

```bash
ls -l /dev/serial/by-id/          # pick the gateway radio's entry
# set GATEWAY_SERIAL_PORT=/dev/serial/by-id/usb-... in .env, then
docker compose up -d --force-recreate gateway-receiver
```

Always use a `by-id` path. If the container cannot open the device at all, the
host user is probably not in `dialout`:

```bash
sudo usermod -aG dialout "$USER"    # then log out and back in
```

A gateway radio not in `CLIENT_MUTE` rebroadcasts and contaminates its own
measurement (G6): provision it from the platform.

---

## A Raspberry Pi with a stale clock

**Symptom.** `pip`, `apt` or `docker pull` fail with TLS or certificate errors —
"certificate has expired or is not yet valid", "Release file is not valid yet".

A Pi has no battery-backed clock. At boot it restores the last time saved to
disk and only then syncs over the network, so a Pi powered off for a fortnight
comes up a fortnight behind. Valid certificates then look **not yet valid**, and
every TLS client breaks at once.

```bash
timedatectl                              # compare against the real date
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
timedatectl                              # want: System clock synchronized: yes
```

A managed building network may block NTP (UDP 123). Point the Pi at a reachable
time server — the gateway host works — or set the clock by hand to unblock:
`sudo date -s "YYYY-MM-DD HH:MM:SS"`.

Fix this **before** starting containers: see
[Measurements landing in the past](#measurements-landing-in-the-past).

---

## Measurements landing in the past

**Symptom.** Data is being published and stored, but the dashboard and any
"last N hours" query show nothing.

The gateway stamps each record with the **local wall clock**
(`received_at`), and Telegraf uses that stamp as the database timestamp. A host
running twelve days behind writes every point twelve days into the past —
silently, since nothing about a wrong timestamp is invalid.

This corrupts the record instead of stopping it: in InfluxDB the timestamp is
part of a point's identity, so misfiled points cannot be corrected in place.
Check `timedatectl` on **every** host that publishes before starting containers.
(The PDR arithmetic itself runs on the monotonic clock and is unaffected.)

---

## Compose restarted the old image

**Symptom.** A code change, or a `git pull`, has no effect at all.

`gateway-receiver` bakes its Python into the image with `COPY`. Plain
`docker compose up -d` sees a running container and leaves it alone — it does
**not** rebuild.

```bash
docker compose up -d --build
```

Telegraf, the broker configuration and `deployments/` are mounted, not baked:
a change there needs a restart (`docker compose restart <service>`), not a
rebuild. That difference is why one kind of change can appear to work while
another does not.

---

## Compose v2 is not installed

**Symptom.** `docker compose up -d --build` prints `unknown shorthand flag: 'd'
in -d` and a usage block.

`compose` is not being resolved as a Docker subcommand — usually a host with the
old standalone `docker-compose` (v1) and no v2 plugin. **v1 is not a fallback.**

```bash
docker compose version      # want: Docker Compose version v2.x
sudo apt-get update && sudo apt-get install -y docker-compose-plugin
```

On a Pi where Docker came from `apt install docker.io`, installing from the
official Docker repository gets a matching CLI, daemon and plugin. If `apt`
fails on certificates, fix the clock first.

---

## Serial port contention

**Symptom.** Provisioning fails to open the port, or a board reboots the moment
something connects to it.

**Only one process can hold a serial port.** `gateway-receiver` holds the
gateway radio's for as long as it runs, and `restart: unless-stopped` reopens it
after a crash. Bring it down before provisioning that radio from the platform:

```bash
docker compose stop gateway-receiver
```

An editor or serial monitor left open on the port counts too. Opening a
LILYGO's USB console resets the board (the ESP32 auto-reset circuit is driven by
the serial control lines): harmless for a one-off read; for a permanent
install, prefer a GPIO UART.

---

## Node-side symptoms

A sensor detected but sending no telemetry, every node reporting the same
position, a flow that never arrives from a node: the cause is on the radio, not
in the gateway. They are catalogued in `meshtastic-platform`'s
`docs/troubleshooting.md`.

---

## Still stuck?

The chronological record of what broke and how it was diagnosed is in
[`session-log.md`](session-log.md); the delivery-ratio estimator is explained in
[`architecture/pdr-cadence-tracker.md`](architecture/pdr-cadence-tracker.md).
