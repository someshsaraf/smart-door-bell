# MQTT topics

| Direction | Topic | Payload | Action |
|---|---|---|---|
| Outdoor → Pi | `home/doorbell/start` | `{"command":"start","timer":30,"event_id":"outdoor-123456"}` | Show visitor screen with camera, play bell for `timer` seconds |
| Pi → Outdoor | `home/doorbell/ack` | `{"event_id":"outdoor-123456","status":"received"}` | Start received. `status` is `duplicate` for a start that arrived while already ringing |
| Pi → Outdoor | `home/doorbell/stop` | `{"command":"stop","source":"indoor","event_id":"..."}` | STOP pressed on the Pi: outdoor unit returns to its main screen |
| Outdoor → Pi | `home/doorbell/stop` | `{"command":"stop","source":"outdoor"}` | Ring cancelled outdoors (settings opened mid-ring) |
| Pi → broker | `home/doorbell/indoor/status` | JSON | Ringing/idle status |
| Outdoor → Pi | `home/doorbell/outdoor/state` (retained) | `{"theme":1,"bell_color":1,"ring_seconds":30,"wifi_ssid":"HomeNet","ip":"192.168.2.68","broker":"192.168.2.134","time_synced":true,"firmware":"1.0.1"}` | Current outdoor settings, shown on the Pi's settings page. Republished after every change |
| Outdoor → Pi | `home/doorbell/outdoor/online` (retained) | `online` / `offline` | `offline` is the outdoor unit's MQTT last will, published by the broker if it drops off |
| Pi → Outdoor | `home/doorbell/outdoor/config` | see below | Change outdoor settings |
| Outdoor → Pi | `home/doorbell/outdoor/wifi_scan` | `{"networks":[{"ssid":"HomeNet","rssi":-48,"secure":true}]}` | Answer to a `wifi_scan` command |

## Outdoor settings from the Pi

Any subset of these fields in one `home/doorbell/outdoor/config` message:

| Field | Values | Effect on the outdoor unit |
|---|---|---|
| `theme` | `0` Clean & Light, `1` Midnight & Gold | Same as choosing it under Appearance (also selects that theme's bell colour unless `bell_color` is given) |
| `bell_color` | `0` Blue, `1` Gold, `2` Silver, `3` Red | Bell colour |
| `ring_seconds` | `10`, `15`, `30`, `45`, `60` | Ring duration sent with each start |
| `wifi` | `{"ssid":"...","password":"..."}` | Joins that network; saved only if it connects, otherwise it returns to the saved one |
| `broker` | `"192.168.2.134"` | New MQTT broker address (saved). A wrong value cuts the link; fix it on the doorbell |
| `command` | `"wifi_scan"` | Scans and answers on `home/doorbell/outdoor/wifi_scan` |

The outdoor unit saves every change, so it survives a restart. The Wi-Fi password
travels in clear text over the LAN; see the broker section of the README.

Delivery of a start:

- The outdoor unit keeps the same `event_id` for every send of one press.
- With no ack for that `event_id` within 2 s it resends, at most 3 times after the first send.
  If none is acknowledged it gives up and its Indoor Unit page shows "Last ring not confirmed".
- The Pi acks every start, including duplicates, and ignores starts while its timer runs.

Do not retain start commands; otherwise a reconnect could replay an old ring.
The outdoor unit subscribes at QoS 0 and publishes at QoS 0; the ack/resend above
is what makes the start reliable.
