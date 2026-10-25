# MQTT topics

| Direction | Topic | Payload | Action |
|---|---|---|---|
| Outdoor → Pi | `home/doorbell/start` | `{"command":"start","timer":30,"event_id":"outdoor-123456"}` | Show visitor screen with camera, play bell for `timer` seconds |
| Pi → Outdoor | `home/doorbell/ack` | `{"event_id":"outdoor-123456","status":"received"}` | Start received. `status` is `duplicate` for a start that arrived while already ringing |
| Pi → Outdoor | `home/doorbell/stop` | `{"command":"stop","source":"indoor","event_id":"..."}` | STOP pressed on the Pi: outdoor unit returns to its main screen |
| Outdoor → Pi | `home/doorbell/stop` | `{"command":"stop","source":"outdoor"}` | Ring cancelled outdoors (settings opened mid-ring) |
| Pi → broker | `home/doorbell/indoor/status` | JSON | Ringing/idle status |
| Outdoor → Pi | `home/doorbell/outdoor/state` (retained) | `{"theme":1,"bell_color":1,"ring_seconds":30,"bell_style":0,"glow":true,"chime":0,"chime_repeat":false,"volume":70,"wifi_ssid":"HomeNet","ip":"192.168.2.68","broker":"192.168.2.134","time_synced":true,"firmware":"1.0.1"}` | Current outdoor settings, shown on the Pi's settings page. Republished after every change |
| Outdoor → Pi | `home/doorbell/outdoor/online` (retained) | `online` / `offline` | `offline` is the outdoor unit's MQTT last will, published by the broker if it drops off |
| Pi → Outdoor | `home/doorbell/outdoor/config` | see below | Change outdoor settings |
| Outdoor → Pi | `home/doorbell/outdoor/wifi_scan` | `{"networks":[{"ssid":"HomeNet","rssi":-48,"secure":true}]}` | Answer to a `wifi_scan` command |
| Pi → Outdoor | `home/doorbell/talk` | `{"command":"start","host":"192.168.1.102","port":5004}` / `{"command":"end"}` | Intercom call. Audio then flows as raw 16 kHz mono 16-bit PCM in 20 ms UDP packets (640 bytes) both ways on port 5004; the doorbell answers to the address the audio comes from and hangs up by itself after 10 s without audio or 5 min |
| Pi → Outdoor | `home/doorbell/festival` (retained) | `{"festival":"diwali","until":1794335400,"greeting":"Happy Diwali","tones":true}` | Festival theme running now: `diwali`, `christmas`, `new_year` or `none`. `until` is the end in UTC seconds; the doorbell reverts by itself when its clock passes it. `tones` false keeps the user's chime. Republished whenever it changes and on every reconnect |

## Outdoor settings from the Pi

Any subset of these fields in one `home/doorbell/outdoor/config` message:

| Field | Values | Effect on the outdoor unit |
|---|---|---|
| `theme` | `0` Clean & Light, `1` Midnight & Gold | Same as choosing it under Appearance (also selects that theme's bell colour unless `bell_color` is given) |
| `bell_color` | `0` Blue, `1` Gold, `2` Silver, `3` Red | Bell colour |
| `bell_style` | `0` Classic, `1` Push button, `2` Temple, `3` Hand bell, `4` Twin bells, `5` Flat | Home-screen bell picture (Push button adds a pulsing halo) |
| `glow` | `true` / `false` | Aurora glow behind the bell: soft magenta, cyan and violet light drifting on the home screen |
| `chime` | `0` Ding Dong, `1` Westminster, `2` Triple Chime, `3` Marimba, `4` Church Bell | Chime on the doorbell's own speaker when pressed |
| `chime_repeat` | `false` once per press, `true` for the whole ring | The repeating chime stops when the ring ends or is stopped |
| `volume` | `0`–`100` (the doorbell offers Quiet `40`, Normal `70`, Loud `100`) | Doorbell speaker volume |
| `ring_seconds` | `10`, `15`, `30`, `45`, `60` | Ring duration sent with each start |
| `network` | `{"ssid":"...","password":"...","broker":"192.168.1.102"}` (each optional) | New Wi-Fi and/or indoor unit address, **applied as one change**: saved only if the doorbell joins the Wi-Fi *and* reaches the broker within 60 s, otherwise it returns to its previous Wi-Fi and address. The result appears in the state as `"network_change": "applied"` or `"reverted"` |
| `wifi`, `broker` | `{"ssid","password"}` / `"192.168.1.102"` | Older separate forms; handled exactly like `network` |
| `screen_off` | `{"enabled":true,"from":23,"to":6}` (each optional; hours 0–23, local time) | Screen dark between the hours (over midnight when from > to); a touch lights it for 30 s, rings and calls always light it. Default 23 → 6. Reported back in the state as `screen_off`, with `screen_lit` saying whether it is lit now |
| `command` | `"wifi_scan"` | Scans and answers on `home/doorbell/outdoor/wifi_scan` |
| `command` | `"screen_on"` / `"screen_off"` | Lights or darkens the screen now; holds until the schedule changes (at the from/to hour), and a touch or ring still wakes a darkened screen |

The outdoor unit saves every change, so it survives a restart. With the doorbell's
TLS key set up (README, "Good to know") the doorbell connects on port 8883 with
TLS-PSK, so these messages, including a Wi-Fi password, are encrypted on the LAN;
the dashboard uses 127.0.0.1:1883 on the Pi itself.

Delivery of a start:

- The outdoor unit keeps the same `event_id` for every send of one press.
- With no ack for that `event_id` within 2 s it resends, at most 3 times after the first send.
  If none is acknowledged it gives up and its Indoor Unit page shows "Last ring not confirmed".
- The Pi acks every start, including duplicates, and ignores starts while its timer runs.

Do not retain start commands; otherwise a reconnect could replay an old ring.
The outdoor unit subscribes at QoS 0 and publishes at QoS 0; the ack/resend above
is what makes the start reliable.
