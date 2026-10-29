# 🖥️ Indoor dashboard

[← Back to the README](../README.md)

A Raspberry Pi 5 on a 12.3″ touch display. When nobody is at the door it is a calm home screen with the time, the
news, the markets or photos; when someone rings it becomes the door.

<img src="images/indoor_wall.jpg" alt="The dashboard in the Editorial look on the 12.3-inch display" width="100%">

---

## 🎨 Four looks

The home screen is drawn with **Qt Quick on the Pi's GPU**: real frosted-glass blur, soft shadows, smooth motion and
[Inter](https://rsms.me/inter/) type. **Settings → Look** picks one; the other pages and the web app take its colours.

<table>
<tr>
<td width="50%"><img src="../Indoor/assets/looks/editorial.png" alt="Editorial look"></td>
<td width="50%"><img src="../Indoor/assets/looks/paper.png" alt="Paper look"></td>
</tr>
<tr>
<td><b>Editorial</b> — a cover: the story's photo fills the screen and drifts slowly, its headline set large on it; the clock, the front door and three tiles on a black panel</td>
<td><b>Paper</b> — the same cover with a light panel and a black front door button, for a bright room</td>
</tr>
<tr>
<td><img src="../Indoor/assets/looks/glass.png" alt="Glass look"></td>
<td><img src="../Indoor/assets/looks/fluent.png" alt="Fluent look"></td>
</tr>
<tr>
<td><b>Glass</b> — like a phone's home screen: frosted widgets over the story's photo, with a big Front door widget, rings today and a News / Photos switch</td>
<td><b>Fluent</b> — like a Windows app: a navigation pane with an accent Front door button, an info bar for breaking news, and cards on a soft Mica backdrop</td>
</tr>
</table>

In every look:

- **Front door** is the most prominent button, with the camera's latest picture (refreshed every minute) and
  whether the doorbell is online
- **The voice orb** — a softly swirling sphere (*"Ask the doorbell"*) that comes alive while listening
- **News or photos** — one tap switches between them

## 📰 News, markets and photos

- **News** — the top stories of *NDTV, Times of India, BBC, Yahoo News* and *Google News* (by region and topic;
  optionally *The Hindu, Hindustan Times*), one at a time with photo, channel and summary. Swipe or tap ‹ › to move
  between them. The newest headlines glide along the foot (*BREAKING* while any is under 90 minutes old), and a
  story under 20 minutes old slides in as a **BREAKING** banner. Public RSS feeds, no login; cached for offline starts
- **Market** — NIFTY 50, SENSEX and the NIFTY's top gainers and losers every 2 minutes during market hours (the last
  close otherwise), from Yahoo Finance via `yfinance`
- **Photos** — 12 landscapes, slowly zooming and cross-fading; add your own in `Indoor/assets/scenic/`

## 🚪 When someone rings

- **The visitor screen** — the door camera full screen like a video call: *VISITOR AT THE DOOR* with the ring time,
  a REC badge, a countdown ring and a big **STOP** (which also returns the doorbell to its main screen)
- **The door's sound** plays with the picture, delayed to match it, mixed with the chime
- **Red boxes** around people, animals and vehicles the AI detector sees
- **Front door** opens the same live view any time, without a ring
- **Talk (trial)** — two-way audio through the doorbell; off by default (**Settings → Speaker**)

## 🔊 Speaker and tones

- **16 ring tones** on a Bluetooth speaker — chimes, Bollywood style (shehnai, sitar, dhol, santoor), festive
  (Jingle Bells, Auld Lang Syne) and funny ones (boing, kazoo, rubber duck…), all original. Add your own `.wav` or
  `.mp3` in `Indoor/assets/tones/mine/`
- The tone loops for the whole ring, until the timer ends or STOP is pressed
- **Settings → Speaker** pairs, connects and tests the speaker

## 🎙️ Voice commands

Tap the orb (◉ on the other pages) and say:

> *"Stop the bell"* · *"Mute the bell for an hour"* · *"Show me all events"* ·
> *"Show events from yesterday / last Monday / 20 October / this week"* · *"Play the last recording"* ·
> *"Who is at the front door"* · *"Go home"*

Speech is recognised by Whisper on the Pi's CPU (about 2 s a command); nothing goes to the cloud. Needs a USB
microphone.

## ⚙️ Settings

| Section | What is in it |
|---|---|
| **Look** | The four looks, with previews |
| **Speaker** | Pair and connect, volume, test, the trial intercom |
| **Bell tone** | Pick and preview a tone |
| **News** | Channels, regions and topics |
| **Festivals** | Festival looks and tones on or off, the next dates, try a look for a minute |
| **Phone** | ntfy notifications, the doorbell-offline alert |
| **Camera** | Find, log in and test the camera; recording length, sound, motion recording |
| **Web access** | The web app's password and address, ring alerts on this device |
| **Outdoor unit** | Everything on the doorbell: look, sound, ring time, night screen, Wi-Fi and address |

## 🪔 Festival themes

Around festivals both units dress up by themselves and return to your settings afterwards. The dashboard keeps the
calendar and tells the doorbell (a retained MQTT message), so the doorbell reverts on time by its own clock even when
the dashboard is off.

| Festival | When | Doorbell | Dashboard | Tones |
|---|---|---|---|---|
| Diwali | 2 days before to 2 days after | Golden temple bell on maroon | Golden sparks rising | Temple bell · shehnai |
| Christmas | 23 – 27 December | Golden twin bells on deep green | Snowfall | Jingle Bells |
| New Year | 1 – 2 January | Gold bell on midnight blue | Confetti | Auld Lang Syne |

The photo slideshow shows festival pictures too (your own in `Indoor/assets/festivals/diwali/`, `christmas/` or
`new_year/`, else painted ones), and a greeting floats over the home screen. Diwali dates are built in up to 2030
(`Indoor/festivals.py`); add later years in `config.json`: `"festivals": {"diwali": {"2031": "2031-11-14"}}`.

---

Running the Pi side by hand, MQTT broker, camera and speaker from the command line: **[Indoor/README.md](../Indoor/README.md)**.
