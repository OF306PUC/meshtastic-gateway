# The gateway as a WiFi access point

In the field there is no network to join, so the gateway host makes its own: a
laptop joins the host's WiFi and opens the dashboard at `http://10.42.0.1/`.

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

Written for pi7 (`office-bench`): its office network is the NetworkManager
profile `preconfigured` (SSID `oficina_v2`). Another host: `nmcli connection
show` names its profile.

**While the access point is up the host is off the office network**, and so is
SSH to its office address. The Pi 4 radio cannot reliably be a client and an
access point at once, and pi7 has no Ethernet cable. Reach it through its own
WiFi: `ssh rpi7@10.42.0.1`.

---

## 1. Create the profile (once)

Over SSH from the office. Creating the profile does not activate it.

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name terreno-ap \
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

## 3. Field mode, before leaving

In the field nobody types commands: the host must bring up its network by
itself at power-on.

```bash
sudo nmcli connection modify terreno-ap connection.autoconnect yes connection.autoconnect-priority 10
```

At boot NetworkManager activates the highest-priority profile it can. An access
point is always available, and 10 beats `preconfigured`'s 0. From here on the
host boots as an access point **in the office too**. Check it with
`sudo reboot`: within one or two minutes `meshtastic-gw` appears on the laptop.

## 4. In the field

1. Power the host and wait one or two minutes: the system boots and the
   containers start by themselves (`restart: unless-stopped`).
2. Join `meshtastic-gw` on the laptop.
3. Set the host's clock from the laptop's, first thing:

   ```bash
   ssh rpi7@10.42.0.1 "sudo date -s @$(date +%s)"
   ```

   `$(date +%s)` expands on the laptop, so the host gets the laptop's time. A
   Pi has no battery-backed clock and there is no internet to sync from: it
   boots at the time it was switched off, and every record it stores until
   this step lands in the past
   ([Measurements landing in the past](troubleshooting.md#measurements-landing-in-the-past)).
4. Open `http://10.42.0.1/`.

## 5. Back in the office

Join `meshtastic-gw`, `ssh rpi7@10.42.0.1`, then:

```bash
sudo nmcli connection modify terreno-ap connection.autoconnect no
sudo nmcli connection up preconfigured
```

The host is back on `oficina_v2` at `10.6.5.7`. Step 3 returns it to field
mode.

---

## Good to know

- Range: the Pi 4's internal antenna covers some tens of metres, enough for a
  laptop in the same room.
- A laptop may warn that the network has no internet. It still reaches the
  dashboard; a phone may need "stay connected" or its mobile data off.
- Remove the profile: `sudo nmcli connection delete terreno-ap`.
