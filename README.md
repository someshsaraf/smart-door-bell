<div align="center">

# 🔔 Smart Doorbell

**A round-screen doorbell on a Tuya T5 board, and a wall dashboard on a Raspberry Pi
that rings, shows the camera, and lets you answer from inside.**

![TuyaOpen](https://img.shields.io/badge/TuyaOpen-T5AI-ff4800)
![LVGL](https://img.shields.io/badge/LVGL-9.1-2f80ed)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-5-c51a4a?logo=raspberrypi&logoColor=white)
![MQTT](https://img.shields.io/badge/MQTT-Mosquitto-660066?logo=eclipsemosquitto&logoColor=white)
![Qt](https://img.shields.io/badge/PySide6-Qt%206-41cd52?logo=qt&logoColor=white)

<img src="docs/images/indoor_photo.jpg" alt="Indoor dashboard on a 10-inch display, showing the clock and Bangalore top stories over a sunset landscape" width="820">

<sub>The indoor dashboard on its 10-inch display: clock, live headlines, shortcuts and recent doorbell events.</sub>

</div>

---

## ✨ At a glance

| | Outdoor unit — at the door | Indoor unit — on the wall |
|---|---|---|
| **Hardware** | Tuya T5 (T5AI) board with a 1.75″ 466×466 round AMOLED touch display | Raspberry Pi 5 + 10″ HDMI display + Bluetooth speaker |
| **When a visitor taps** | The bell swings, sound waves pulse, the ring is sent to the indoor unit | Chime plays on the speaker, the door camera appears with a big **STOP** |
| **Day to day** | Bell, clock and date on a crisp round screen | Big clock over rotating **news** or a **photo** slideshow |
| **Setup** | Wi-Fi, theme, bell picture and colour, ring time — on the round screen | The same outdoor settings, plus speaker, tone and news — from the wall |

---

## 🧭 How it works

```mermaid
sequenceDiagram
    autonumber
    actor Visitor
    participant O as 🛎️ Outdoor unit<br/>(Tuya T5)
    participant B as 📨 MQTT broker<br/>(Mosquitto on the Pi)
    participant I as 🖥️ Indoor dashboard<br/>(Raspberry Pi)
    Visitor->>O: tap the bell
    O->>B: start {timer: 30 s, event_id}
    B->>I: start
    I-->>O: ack {event_id}
    Note over O: no ack in 2 s → resend<br/>(up to 3 times, same event_id)
    Note over I: chime loops on the speaker<br/>camera feed + countdown + STOP
    alt STOP pressed indoors
        I->>O: stop
        Note over O: back to the main screen
    else timer runs out
        Note over O,I: both sides stop on their own
    end
```

Everything stays on your home network: the doorbell talks to a Mosquitto broker on the Pi, and
the Pi reads the camera directly over RTSP. No cloud account is needed.

---

## 🛎️ Outdoor unit — Tuya T5 round display

<div align="center">
<img src="docs/images/outdoor_screens.png" alt="Three round doorbell screens: blue bell on a light theme, the blue bell swinging with sound waves, and a gold bell on a dark theme" width="860">

<sub><b>Classic bell</b> · <b>Push button</b> (pulsing halo invites a tap) · <b>Ringing</b> (Midnight &amp; Gold)<br/>
Rendered from the firmware's own layout, colours and bell shading — not a photo of the device.</sub>
<br/><br/>
<img src="docs/images/outdoor_bell_page.png" alt="Round Bell settings page with six bell thumbnails: Classic, Push button, Temple (selected), Hand bell, Twin bells, Flat" width="300">

<sub>The <b>Bell</b> settings page: six styles, each previewed in your bell colour.</sub>
</div>

**Board:** Tuya T5-E1 / **Waveshare T5AI 1.75″ Touch AMOLED** development board — 466×466 round AMOLED,
capacitive touch, QSPI display interface (TuyaOpen board `WAVESHARE_T5AI_TOUCH_AMOLED_1_75`).

- 🔔 **Tap to ring** — the bell swings with pulsing sound waves; drawn on the device at full resolution, no blurry bitmaps
- 🛎️ **Six bell styles** — *Classic*, *Push button* (a pulsing halo shows visitors where to press), *Temple* bell, *Hand bell*,
  *Twin bells* and *Flat*, picked on the doorbell's **Bell** page from thumbnails drawn in your bell colour
- 🔊 **Chime at the door** — on the board's speaker (8 Ω, MX1.25 connector) so the visitor hears it rang: five chimes,
  once per press or for the whole ring, three volume levels (**Sound** settings page)
- ✋ **Hold 5 s for settings** — a ring traces the screen edge while you hold
- 📶 **Wi-Fi setup on the screen** — scan, pick a network, type the password on a keyboard sized for the round display; saved and reconnected after every reboot; a wrong password never loses the network that worked
- 🕒 **Network clock** — time and date from NTP (IST), never a made-up time
- 🎨 **Themes** — *Clean & Light* or *Midnight & Gold* (true black, AMOLED-friendly), four bell colours
- 🌌 **Aurora glow** — soft magenta, cyan and violet light drifting behind the bell; it speeds up and brightens while ringing (on/off under Appearance)
- ⏱️ **Ring duration** — 10 / 15 / 30 / 45 / 60 s
- 📨 **Reliable ring delivery** — every press carries an `event_id`; resent every 2 s until the indoor unit acknowledges it
- 🎙️ **Intercom (trial)** — talk with the visitor through the doorbell's microphone and speaker (echo-cancelled), opened from the dashboard
- 🪔 **Festival themes** — Diwali, Christmas and New Year dress the doorbell up by themselves (see below)
- 🔄 **Remote settings** — everything above can also be changed from the indoor dashboard
- 💾 Settings survive restarts (encrypted on-board key–value storage)

---

## 🖥️ Indoor unit — Raspberry Pi dashboard

<table>
<tr>
<td width="50%"><img src="docs/images/indoor_news.jpg" alt="Dashboard showing a large India top-stories headline with the next three headlines listed"></td>
<td width="50%"><img src="docs/images/indoor_photos.jpg" alt="Dashboard showing a full-screen sunset landscape with the clock and recent events"></td>
</tr>
<tr>
<td align="center"><b>News</b> — a headline every 12 s, tagged by region, genre and source</td>
<td align="center"><b>Photos</b> — full-screen landscapes, sliding every 15 s</td>
</tr>
</table>

- 🕒 **Ambient home screen** — large clock and date over a full-screen backdrop; one tap switches **News ⇄ Photos**
- 📰 **News your way** — mix any of *Global, India, Karnataka, Bangalore* with any of *Top stories, Politics, Business, Technology, Sports, Automobiles, Entertainment, Science, Health* (Google News, no API key, cached for offline starts)
- 🏞️ **Photo slideshow** — 12 hand-picked Unsplash landscapes; drop your own pictures into `Indoor/assets/scenic/`
- 🚪 **Visitor alert** — live VIGI camera feed (RTSP), countdown and a big **STOP** that also returns the doorbell to its main screen
- 🔊 **16 ring tones on a Bluetooth speaker** — chimes, Bollywood-style (shehnai, sitar, dhol, santoor), festive (Jingle Bells, Auld Lang Syne) and funny ones (boing, kazoo, rubber duck…), all original; add your own `.wav`/`.mp3` under `Indoor/assets/tones/mine/`. Loops for the whole ring until the timer ends or STOP is pressed
- 🎙️ **Two-way talk (trial, off by default: Settings → Speaker)** — **Talk** on the visitor screen, or any time from the **Front door** tile (live camera + intercom). The Bluetooth speaker switches to its hands-free microphone for the call and back to full-quality playback afterwards
- 📱 **Phone notifications** — a push alert on every ring through the free [ntfy](https://ntfy.sh) app, no account needed: subscribe to the topic shown under **Settings → Phone** (own server: `sudo bash Indoor/tools/setup_ntfy.sh` installs ntfy on the Pi with logins, then set `"notify": {"server": "...", "token": "tk_..."}` in `config.json`)
- 📋 **Recent events** — the last rings at a glance
- 🪔 **Festival themes** — sparks, snow or confetti and a greeting during festivals (see below)
- 🚀 **Starts at boot** — restarts itself if it ever crashes

### ⚙️ Settings

<table>
<tr>
<td width="50%"><img src="docs/images/settings_speaker.png" alt="Speaker settings: sound output, volume slider, search, test sound and a list showing a connected Philips BT100"></td>
<td width="50%"><img src="docs/images/settings_tone.png" alt="Bell tone settings: tones grouped as Chimes, Bollywood style and Funny, each with a preview button"></td>
</tr>
<tr>
<td align="center"><b>Speaker</b> — pair, connect, volume, test</td>
<td align="center"><b>Bell tone</b> — chimes, Bollywood style, funny, your own</td>
</tr>
<tr>
<td><img src="docs/images/settings_news.png" alt="News settings: region and genre toggle buttons"></td>
<td><img src="docs/images/settings_outdoor.png" alt="Outdoor unit settings: theme, bell colour, ring duration and Wi-Fi of the doorbell"></td>
</tr>
<tr>
<td align="center"><b>News</b> — any regions × any genres</td>
<td align="center"><b>Outdoor unit</b> — configure the doorbell from the wall</td>
</tr>
</table>

---

## 🪔 Festival themes

Around festivals both units switch to a festive look by themselves and return to your own settings afterwards.
The dashboard keeps the calendar and tells the doorbell (retained MQTT message), so the doorbell needs no
calendar of its own and still reverts on time by its own clock if the dashboard is off.

| Festival | When | Doorbell | Dashboard | Tones |
|---|---|---|---|---|
| Diwali | 2 days before to 2 days after | Golden temple bell on maroon, orange and gold glow | Golden sparks rising | Temple bell strikes · shehnai |
| Christmas | 23 – 27 December | Golden twin bells on deep green, red and green glow | Snowfall | Jingle Bells |
| New Year | 1 – 2 January | Gold bell on midnight blue, gold and magenta glow | Confetti | Auld Lang Syne |

On the dashboard the wallpaper changes too (diyas and string lights, a snowy night with a lit tree, fireworks over a skyline; put your own pictures in `Indoor/assets/festivals/diwali/`, `christmas/` or `new_year/` to use them instead) and every page, Settings included, takes the festival colours. The doorbell's date line alternates with the greeting (*Happy Diwali*, *Happy New Year 2027*…).
**Settings → Festivals** on the dashboard turns the themes and the festive tones on or off, lists the next dates
and lets you try each look for a minute. The doorbell has the same switches on its own **Festivals** settings page (festive look, festive chime, try a look for a minute). Diwali follows the lunar calendar: dates up to 2030 are built in
(`Indoor/festivals.py`); add later years in `config.json` as `"festivals": {"diwali": {"2031": "2031-11-14"}}`.

---

## 🧰 What you need

| Part | Used for |
|---|---|
| Tuya T5-E1 / Waveshare T5AI 1.75″ Touch AMOLED board | Outdoor doorbell |
| Raspberry Pi 5 (Raspberry Pi OS desktop) | Indoor dashboard and MQTT broker |
| 10″ HDMI display (touch recommended) | Dashboard screen |
| Bluetooth speaker | Chime |
| TP-Link VIGI (or any RTSP) camera — optional | Live view of the door |

---

## 🚀 Getting started

### 1 · Indoor unit (Raspberry Pi)

```bash
sudo apt install -y python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore \
                    python3-pygame python3-opencv python3-paho-mqtt mosquitto mosquitto-clients
# let the doorbell reach the broker from your LAN
printf 'listener 1883\nallow_anonymous true\n' | sudo tee /etc/mosquitto/conf.d/doorbell.conf
sudo systemctl restart mosquitto
sudo ufw allow from 192.168.1.0/24 to any port 1883 proto tcp   # only if ufw is active; use your subnet

cp -r Indoor ~/Indoor && cd ~/Indoor
python3 app.py                      # try it
sh autostart/install.sh             # start it at every boot
```

Set the camera in `~/Indoor/config.json` → `"camera": {"rtsp_url": "rtsp://USER:PASS@CAMERA_IP:554/stream1"}`.
Pair the speaker, pick a tone and choose your news under **⚙ Settings**.
Full details: **[Indoor/README.md](Indoor/README.md)**.

### 2 · Outdoor unit (Tuya T5)

The firmware is a [TuyaOpen](https://github.com/tuya/TuyaOpen) application and builds inside the SDK.
Board: Tuya T5-E1 1.75″ AMOLED, using the SDK's `WAVESHARE_T5AI_TOUCH_AMOLED_1_75` definition — all board,
LVGL 9, touch and font settings are already in `Outdoor/app_default.config`.

```powershell
git clone https://github.com/tuya/TuyaOpen.git; cd TuyaOpen
. .\export.ps1                                   # every new terminal (export.sh on Linux/macOS)
cd examples\graphics
git clone https://github.com/someshsaraf/smart-door-bell.git doorbell
cd doorbell\Outdoor
tos.py build                                     # → dist\Outdoor_1.0.1\Outdoor_QIO_1.0.1.bin
tos.py flash -p COM6                             # your serial port
```

Configuration explained, how to check and change it, logs and troubleshooting:
**[Outdoor/README.md](Outdoor/README.md)**.

### 3 · Connect them

On the doorbell: **hold the screen 5 s → Wi-Fi** → join your network, then **Indoor Unit → Set address** → the Pi's IP
(`hostname -I` on the Pi). The page turns **Connected** within seconds. From then on everything can be changed from
the dashboard's **⚙ Settings → Outdoor unit**.

> **Tip:** reserve the Pi's address in your router (DHCP reservation) so the doorbell never loses it.

---

## 📨 MQTT topics

| Topic | Direction | Purpose |
|---|---|---|
| `home/doorbell/start` | outdoor → indoor | Ring, with `timer` and `event_id` |
| `home/doorbell/ack` | indoor → outdoor | Start received (also for duplicates) |
| `home/doorbell/stop` | both ways | Stop ringing |
| `home/doorbell/outdoor/state` | outdoor → indoor (retained) | Doorbell settings and network |
| `home/doorbell/outdoor/online` | outdoor → indoor (retained) | `online` / `offline` (last will) |
| `home/doorbell/outdoor/config` | indoor → outdoor | Change doorbell settings |
| `home/doorbell/outdoor/wifi_scan` | outdoor → indoor | Networks the doorbell can see |
| `home/doorbell/festival` | indoor → outdoor (retained) | Festival theme running now |
| `home/doorbell/talk` | indoor → outdoor | Intercom call start / end (audio: UDP 5004) |

Payloads and rules: **[Indoor/topics.md](Indoor/topics.md)**.

---

## 📁 Project layout

```
doorbell/
├── Outdoor/                 TuyaOpen firmware for the T5 round display
│   ├── README.md              build & flash guide, board configuration
│   ├── src/doorbell_ui.c      LVGL screens, bell rendering, touch, settings
│   ├── src/doorbell_net.c     Wi-Fi, NTP clock, MQTT client, remote settings
│   └── app_default.config     board: WAVESHARE_T5AI_TOUCH_AMOLED_1_75
├── Indoor/                  Raspberry Pi dashboard (Python, PySide6)
│   ├── app.py                 dashboard, ring screen, camera, MQTT
│   ├── settings_ui.py         settings screens and on-screen keyboard
│   ├── news.py · bluetooth.py news feed · speaker pairing
│   ├── assets/                tones, scenic photos (with credits)
│   └── autostart/             start at boot
└── docs/images/             pictures used in this README
```

---

## 🔒 Good to know

- **Encrypted doorbell link** — the doorbell talks to the Pi's broker over **TLS 1.2 with a pre-shared key** on port 8883
  (ECDHE-PSK-AES128-CBC-SHA256: forward secrecy, no certificates, so it works before the doorbell's clock is set).
  Only a doorbell holding the key can connect, and that key may only use `home/doorbell/…` topics. The dashboard
  connects to the broker on `127.0.0.1`, so its traffic never leaves the Pi. To set it up:
  1. On the PC: `python Outdoor/tools/make_psk.py` writes the key into `Outdoor/src/doorbell_secret.h` and
     `Indoor/mqtt_psk.txt`; copy the latter to `~/Indoor/` on the Pi. Both files are git-ignored.
  2. On the Pi: `sudo bash ~/Indoor/tools/setup_mqtt_tls.sh` adds the encrypted listener; plain 1883 stays open meanwhile.
  3. Build and flash the doorbell (without the header it builds plain MQTT and warns).
  4. Once the doorbell shows *Connected*: `sudo bash ~/Indoor/tools/setup_mqtt_tls.sh --lock` limits plain MQTT to the Pi itself.
- **Notifications** go to ntfy.sh over HTTPS; a self-hosted server is reached over Tailscale (WireGuard). Settings → Phone shows which.
  The ntfy server itself can read the alert text ("Someone is at the front door · time"), nothing more.
- The trial intercom's audio (UDP 5004) is not encrypted yet; it is off by default.
- Both devices must be able to reach each other: avoid guest Wi-Fi networks, which block devices from talking to each other.

## 🙏 Credits

Built on [TuyaOpen](https://github.com/tuya/TuyaOpen) and [LVGL](https://lvgl.io) ·
dashboard in [PySide6 / Qt](https://doc.qt.io/qtforpython-6/) ·
landscape photos from [Unsplash](https://unsplash.com) via [Lorem Picsum](https://picsum.photos) — photographers in
[Indoor/assets/scenic/CREDITS.md](Indoor/assets/scenic/CREDITS.md) ·
headlines from [Google News](https://news.google.com) RSS.
