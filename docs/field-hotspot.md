# The gateway as a WiFi access point

The gateway host makes its own WiFi network and brings it up at every boot,
in the office as in the field: a laptop joins the host's WiFi and opens the
dashboard at `http://10.42.0.1/`.

```
laptop ── WiFi "meshtastic-gw" ──► gateway host (10.42.0.1)
 (gets 10.42.0.x)                   ├─ proxy :80 ──► dashboard
                                    └─ gateway radio on USB ◄── LoRa ── nodes
```

NetworkManager, already running on Raspberry Pi OS bookworm, does all of it: a
connection profile in access-point mode with `ipv4.method shared` brings up the
WiFi network and hands out addresses (DHCP) and names (DNS). Nothing else is
installed, and nothing in the stack changes: the proxy already listens on every
interface.

Written for pi7 (`office-bench`): its access point is the NetworkManager
profile `terrain-ap` (SSID `meshtastic-gw`), its office network the profile
`preconfigured` (SSID `oficina_v2`). Another host: `nmcli connection show`
names its profiles.

**While the access point is up the host is off the office network and the
internet**, and so is SSH to its office address. The Pi 4 radio cannot
reliably be a client and an access point at once, and pi7 has no Ethernet
cable. Reach it through its own WiFi: `ssh rpi7@10.42.0.1`. §5 joins the
office network for what needs it.

---

## 1. Create the profile (once)

Over SSH from the office. Creating the profile does not activate it.

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name terrain-ap \
  autoconnect no \
  ssid "meshtastic-gw" \
  802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
  ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method disabled \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<wifi password>" \
  wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.pmf disable
```

| Setting | Why |
|---|---|
| `mode ap` | The host makes the network instead of joining one |
| `band bg`, `channel 6` | 2.4 GHz: more range than 5 GHz |
| `ipv4.method shared` | DHCP and DNS for whoever joins; the host is always `10.42.0.1` |
| `wifi-sec.*` | WPA2 with AES, which the Pi's WiFi chip handles with any client |
| `<wifi password>` | 8 to 63 characters (WPA2). Not the dashboard password |

## 2. Try it once in the office

With the laptop next to the host.

1. On the host: `sudo nmcli connection up terrain-ap`. An SSH session over the
   office network freezes here: expected.
2. On the laptop, join `meshtastic-gw`. It gets a `10.42.0.x` address.
3. Open `http://10.42.0.1/` and log in as `dashboard`.
4. `ssh rpi7@10.42.0.1`, then
   `cd ~/Desktop/meshtastic-gateway && docker compose ps`: six services up.
5. Back to the office network: `sudo nmcli connection up preconfigured`. The
   host returns to `10.6.5.7`; rejoin `oficina_v2` on the laptop.

## 3. Boot as an access point (once)

Nobody types commands at power-on: the host must bring up its own network by
itself.

```bash
sudo nmcli connection modify terrain-ap connection.autoconnect yes connection.autoconnect-priority 10
sudo nmcli connection modify preconfigured connection.autoconnect no
```

At boot NetworkManager activates only profiles with autoconnect on, the
highest priority first; between equal priorities it takes the one used last,
which is the office network. `nmcli connection up` (step 2) activates a
profile once and is forgotten at the next boot. With the office profile's
autoconnect off, the access point is the only profile left to choose. If it
fails to come up, the host has no network at all; it never falls back to the
office.

The host stays on the office network until it reboots. Check it with
`sudo reboot`: within one or two minutes `meshtastic-gw` appears on the
laptop. If it does not, `nmcli -f NAME,AUTOCONNECT,AUTOCONNECT-PRIORITY
connection show` must list `terrain-ap` as `yes 10` and `preconfigured` as
`no`.

## 4. After every boot

1. Power the host and wait one or two minutes: the system boots and the
   containers start by themselves (`restart: unless-stopped`).
2. Join `meshtastic-gw` on the laptop.
3. Set the host's clock from the laptop's, first thing:

   ```bash
   ssh rpi7@10.42.0.1 "sudo date -s @$(date +%s)"
   ```

   `$(date +%s)` expands on the laptop, so the host gets the laptop's time. A
   Pi has no battery-backed clock and its own WiFi has no internet to sync
   from: it boots at the time it was switched off, and every record it stores
   until this step lands in the past
   ([Measurements landing in the past](troubleshooting.md#measurements-landing-in-the-past)).
   In the office too: after a reboot the clock is behind by a minute or two,
   after a night unplugged by the whole night.
4. Open `http://10.42.0.1/`.

## 5. On another WiFi network for a while

Running the gateway needs no other network: the containers start at boot on
the access point, and the dashboard, its map included, is served from the
host. The internet is needed to download: `git pull`, a missing image, and a
build that installs packages (the first one, or after `requirements.txt`
changes). Join `meshtastic-gw`, `ssh rpi7@10.42.0.1`, then:

```bash
sudo systemd-run --collect /bin/sh -c 'nmcli connection up preconfigured || nmcli connection up terrain-ap'
```

The SSH session freezes: the access point is gone. `systemd-run` keeps the
command running without it, and if the network cannot be joined (out of
range, a wrong password) the host brings its access point back. Rejoin
`oficina_v2` on the laptop and `ssh rpi7@10.6.5.7`; the clock syncs by itself
(NTP). The host stays there until its next boot, which brings the access
point back. To return sooner: `sudo nmcli connection up terrain-ap`.

Any other network with internet (a home network, a phone's hotspot) needs its
profile once, with autoconnect off so it never competes with the access point
at boot:

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name <name> autoconnect no \
  ssid "<its SSID>" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<its password>"
```

Then the command above with `<name>` for `preconfigured`. On that network the
host's address comes from its router: reach it as `<hostname>.local`
(`raspberrypi.local` until the host is renamed), or find it in the router's
list of clients.

## 6. Stop booting as an access point

Join `meshtastic-gw`, `ssh rpi7@10.42.0.1`, then:

```bash
sudo nmcli connection modify preconfigured connection.autoconnect yes
sudo nmcli connection modify terrain-ap connection.autoconnect no
sudo nmcli connection up preconfigured
```

The host is back on `oficina_v2` at `10.6.5.7`, at every boot. Step 3 returns
it to the access point.

---

## Good to know

- Range: the Pi 4's internal antenna covers some tens of metres, enough for a
  laptop in the same room.
- A laptop may warn that the network has no internet. It still reaches the
  dashboard; a phone may need "stay connected" or its mobile data off.
- Another host on the same bench gets its own SSID and subnet:
  `ipv4.addresses 10.42.1.1/24` in step 1, or `sudo nmcli connection modify
  <profile> ipv4.addresses 10.42.1.1/24` on an existing profile. Two hosts at
  `10.42.0.1` would mix up the laptop's SSH host keys and bookmarks. A laptop
  joins one WiFi network at a time.
- Internet together with the access point needs a second interface for it,
  an Ethernet cable or a USB WiFi adapter, while `wlan0` stays the access
  point. With `ipv4.method shared` the laptops that join then reach the
  internet through the host.
- Remove the profile, after step 6: `sudo nmcli connection delete terrain-ap`.
