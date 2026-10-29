# 🛎️ Outdoor unit

[← Back to the README](../README.md)

<img src="images/outdoor_door.jpg" alt="The outdoor unit on the wall by the door: a blue bell with the time and date" width="300" align="right">

A round 1.75″ AMOLED touch screen by the door, on a Tuya T5 board running [TuyaOpen](https://github.com/tuya/TuyaOpen)
and [LVGL](https://lvgl.io). Day to day it shows a bell, the time and the date; a tap rings inside.
Hardware: **[Waveshare T5-E1 Touch AMOLED 1.75″](hardware.md)**.

<br clear="right"/>

## 🔔 Ringing

- **Tap to ring** — the bell swings with pulsing sound waves, drawn on the device at full resolution
- **A chime at the door** too, so the visitor hears that it rang: five chimes, once per press or for the whole ring,
  three volume levels
- **Reliable delivery** — every press carries an `event_id` and is resent every 2 s until the Pi acknowledges it
- **Ring duration** — 10, 15, 30, 45 or 60 s; **STOP** on the dashboard ends it on both sides
- **The door's sound** — the microphone always keeps its last 8 s; on a press it sends the sound from 3 s before the
  press to the Pi, so recordings have sound from the start. The Front door view asks for it live

<div align="center">
<img src="images/outdoor_screens.png" alt="Three round doorbell screens: blue bell on a light theme, the bell swinging with sound waves, and a gold bell on a dark theme" width="760">

<sub><b>Classic bell</b> · <b>Push button</b> (a pulsing halo invites a tap) · <b>Ringing</b> (Midnight &amp; Gold)</sub>
</div>

## 🎨 Looks

<img src="images/outdoor_bell_page.png" alt="The Bell settings page with six bell thumbnails" width="260" align="right">

- **Six bell styles** — *Classic*, *Push button*, *Temple bell*, *Hand bell*, *Twin bells* and *Flat*, picked from
  thumbnails drawn in your bell colour
- **Two themes** — *Clean & Light*, or *Midnight & Gold* (true black, kind to AMOLED); four bell colours
- **Aurora glow** — soft magenta, cyan and violet light drifting behind the bell, brighter while ringing (can be off)
- **Festival themes** — Diwali, Christmas and New Year dress the doorbell up by themselves, and the date line
  alternates with the greeting (*Happy Diwali*). See [festival themes](indoor.md#-festival-themes)

<br clear="right"/>

## 🎛️ Configured from the wall

Day to day the doorbell is set up entirely from the dashboard — **Settings → Outdoor unit**, on the wall or in the
web app. Nothing needs doing at the door:

| Tab | What you can change |
|---|---|
| **Look** | Theme (*Clean & Light*, *Midnight & Gold*), bell style, bell colour, aurora glow |
| **Sound** | Chime, once per press or for the whole ring, volume, ring duration (10 – 60 s) |
| **Screen** | Screen off at night on or off, its hours, and *turn the screen on / off now* |
| **Network** | Move the doorbell to another Wi-Fi network or change the indoor unit's address |

A network change is safe: the doorbell keeps the new network only if it reaches the Pi within 60 s, otherwise it
returns to the old one by itself. The dashboard also shows the doorbell's firmware, Wi-Fi network and address, and
whether it is online.

## ⚙️ On the doorbell

- **Wi-Fi** — set up once on the doorbell's own setup screen: scan, pick the network and type the password on a
  keyboard sized for the round screen. Saved and reconnected after every reboot; a wrong password never loses the
  network that worked
- **Clock** — time and date from the network (NTP), never a made-up time
- **Screen off at night** — dark from 11 pm to 6 am by default. A touch lights it for 30 s (that touch never rings);
  a ring always lights it
- Settings survive restarts (encrypted on-board storage)

## 🎙️ Intercom (trial)

Talk with the visitor through the doorbell's microphone and speaker (echo-cancelled), started from the dashboard's
visitor screen. Off by default: **Settings → Speaker** on the dashboard. Its audio is not encrypted yet.

---

Build, flash, board configuration and troubleshooting: **[Outdoor/README.md](../Outdoor/README.md)**.
