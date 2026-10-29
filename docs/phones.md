# 📱 Phones & web

[← Back to the README](../README.md)

## 💻 The dashboard in a browser

The Pi serves the whole dashboard as a web app on port 8080, laid out for phones as well as laptops:

- the news, the market and the photos
- the front door live, with its sound, and mute for 1 h or 8 h
- the recordings, to filter (All / Bell / Motion, by day), play and delete
- every setting, including the outdoor unit

A change made there shows on the wall at once, and the other way round. When someone rings, an open page shows the
live camera with a countdown and **STOP**. The page takes the colours of the look chosen on the wall.

**Switch it on:** **Settings → Web access** → set a password → **On**, then open the address shown or scan its QR
code. It works at home over Wi-Fi, and from anywhere with [Tailscale](https://tailscale.com) on the phone.

## 🔔 Ring alerts, no app needed

A notification on every ring, even with the page closed — with the visitor's picture (Android), **Stop the bell**,
and a tap to see the door live (Web Push, Android and iPhone). Browsers allow this only over HTTPS, which Tailscale
provides:

1. In the Tailscale admin console → **DNS**: turn on **MagicDNS** and **HTTPS Certificates** (once).
2. On the Pi: `sudo tailscale serve --bg 8080` — the page is then at `https://<pi-name>.<tailnet>.ts.net`, reachable
   only inside your tailnet (this is not Tailscale Funnel).
3. On each phone, with Tailscale on, open that address and log in.
   - **Android:** Settings → Web access & alerts → **Turn on ring alerts**
   - **iPhone** (iOS 16.4 or later): Safari → Share → **Add to Home Screen**, open *Doorbell* from the home screen,
     then turn alerts on there

## 📨 ntfy notifications

A push alert on every ring through the free [ntfy](https://ntfy.sh) app, no account needed: subscribe to the topic
shown under **Settings → Phone**. To run your own ntfy server on the Pi, with logins:
`sudo bash Indoor/tools/setup_ntfy.sh`, then set `"notify": {"server": "...", "token": "tk_..."}` in `config.json`.

## 🩺 Doorbell offline alert

When the doorbell loses power or Wi-Fi, the broker notices within about 45 s. Once it has been gone for **15 minutes**
(or 5 minutes, an hour, or never — **Settings → Phone**), the phones get *Doorbell offline*; later *Doorbell back
online*, with how long it was down. Sent through ntfy and to every browser with ring alerts on.

> The Pi does the watching: if the Pi itself is off (a power cut that takes both down), no alert can be sent.

---

Privacy and encryption of all this: **[Reference → Security](reference.md#-security)**.
