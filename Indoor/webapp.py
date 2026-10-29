"""The whole dashboard for the browser (web.py serves it): everything the pages
show is published here as named parts whenever it changes, and every tap in a
browser comes back here, on the window's thread, and goes through the same code
as a tap on the wall screen, so both always agree.

Parts:  state     ringing, countdown, mute, doorbell online, MQTT, festival
        news      stories (photo, channel, summary)   breaking   ticker headlines
        market    NIFTY / SENSEX band                  photos     slideshow pictures
        events    recordings                           log        recent events
        settings  every setting with its choices      speaker    Bluetooth
        camera    camera address (never its password)  outdoor    the doorbell's own settings
Ring alerts also go to the phones registered for push (push.py)."""
import base64, secrets, threading, time, traceback
from pathlib import Path
from PySide6.QtCore import QBuffer, QIODevice, QObject, QTimer, Qt
import camera_cfg, push
from festivals import FESTIVALS, upcoming
from news import CHANNELS, DEFAULT_CHANNELS, GENRES, REGIONS
from recorder import CLIP_S, PRE_S, RING_S
import looks
from settings_ui import (OUTDOOR_BELLS, OUTDOOR_CHIMES, OUTDOOR_DURATIONS, OUTDOOR_STYLES, OUTDOOR_THEMES, OUTDOOR_VOLUMES,
                         BELL_ICONS, list_tones, web_addresses)
from web import secure_url

ASYNC = object()  # an action that answers later, from a worker thread
DEFAULTS = {"look": looks.DEFAULT, "tone": "ding_dong.wav", "intercom": False, "news_channels": DEFAULT_CHANNELS, "news_regions": ["india"],
            "news_genres": ["top"], "record_seconds": CLIP_S, "record_audio": True, "offline_alert_min": 15, "notify": False, "festival_themes": True,
            "festival_tones": True, "home_view": "news"}
OUTDOOR_KEYS = {"theme", "bell_color", "bell_style", "glow", "chime", "chime_repeat", "volume", "ring_seconds", "screen_off"}


class WebApp(QObject):
    def __init__(self, w, settings, save, tones):
        super().__init__(); self.w = w; self.web = w.web; self.settings = settings; self.save = save; self.tones = tones
        self.mqtt = (None, ""); self.log = []; self.addresses = []; self.speaker = {"devices": [], "output": "", "volume": 0, "status": ""}
        self.snap_sent = True; self.rang_text = ""
        self.web.action.connect(self.on_action)
        w.news.updated.connect(self.news); w.news.breaking.connect(self.breaking)
        w.markets.updated.connect(lambda d: self.web.publish("market", {"data": d, "note": ""}))
        w.markets.status.connect(lambda note: self.web.publish("market", {"data": w.home.market, "note": note}))
        w.recorder.saved.connect(lambda _e: self.events())
        w.home.logged.connect(self.on_log)
        w.bt.devices.connect(lambda devs: self.set_speaker(devices=devs))
        w.bt.output.connect(lambda name, vol: self.set_speaker(output=name, volume=vol))
        w.bt.status.connect(lambda text: self.set_speaker(status=text))
        w.notifier.result.connect(lambda ok, text: self.notice(("✓ " if ok else "✗ ") + text))
        w.sig.status.connect(lambda ok, msg: (setattr(self, "mqtt", (ok, msg)), self.state()))
        w.sig.message.connect(self.on_mqtt)  # after the window's own handler: the outdoor panel is up to date
        self.timer = QTimer(self); self.timer.timeout.connect(self.slow); self.timer.start(60000)

    # ---------- publishing ----------
    def publish_all(self):
        """Everything, once the server runs (later only what changes)."""
        if not self.web.server: return
        h = self.w.home
        self.slow(); self.news(h.news); self.breaking(h.breaking)
        self.web.publish("market", {"data": h.market, "note": h.market_note})
        self.web.publish("photos", [{"url": "/photos/" + p.name, "credit": h.credits.get(p.name, "")} for p in h.base_paths])
        self.events(); self.camera(); self.outdoor(); self.web.publish("log", self.log)
        self.web.publish("speaker", self.speaker); self.w.bt.request("list")

    def slow(self):
        """Addresses and festival dates change rarely: every minute is plenty."""
        self.addresses = web_addresses(); self.state(); self.settings_part()

    def state(self):
        w = self.w; now = time.monotonic()
        muted = time.time() + (w.muted_until - now) if w.muted_until > now else 0
        self.web.publish("state", {
            "ringing": w.active, "remaining": max(0, int(w.until - now + 0.999)) if w.active else 0,
            "total": getattr(w, "ring_total", 0), "rang_at": w.ring.rang_at, "door_online": w.door_online,
            "muted_until": muted, "camera": bool(camera_cfg.url() or w.cfg_camera_url()),
            "mqtt": {"ok": self.mqtt[0], "text": self.mqtt[1]},
            "festival": {"key": w.home.festival_key, "text": w.home.greeting},
            "home_view": self.settings.get("home_view", "news"), "intercom": self.settings.get("intercom", False)})

    def news(self, items):
        out = []
        for i in items:
            ch = CHANNELS.get(i.get("channel")) or CHANNELS["google"]
            img = Path(i["image"]).name if i.get("image") and Path(i["image"]).exists() else ""
            out.append({"title": i["title"], "source": i.get("source") or ch[0], "time": i.get("time"),
                        "summary": i.get("summary", ""), "img": "/news_img/" + img if img else "", "color": ch[1],
                        "tag": i.get("genre") or "", "region": i.get("region") or ""})
        self.web.publish("news", {"items": out, "note": self.w.home.news_note})

    def breaking(self, items):
        self.web.publish("breaking", [{"title": i["title"], "source": i.get("source", ""), "time": i.get("time")} for i in items])

    def events(self):
        self.web.publish("events", [{k: e.get(k) for k in ("time", "kind", "video", "thumb", "seconds", "note", "audio")}
                                    for e in sorted(self.w.recorder.entries, key=lambda e: -e["time"])[:200]])

    def on_log(self, lines):
        self.log = lines; self.web.publish("log", lines)

    def camera(self):
        c = camera_cfg.load()
        self.web.publish("camera", {"ip": c["ip"], "port": c["port"], "user": c["user"], "main": c["main"], "sub": c["sub"],
                                    "has_password": bool(c["password"])})

    def set_speaker(self, **kw):
        self.speaker = {**self.speaker, **kw}; self.web.publish("speaker", self.speaker)

    def on_mqtt(self, topic, _payload):
        if "outdoor" in topic: self.outdoor()

    def outdoor(self):
        o = self.w.settings.outdoor
        self.web.publish("outdoor", {"online": o.online, "state": o.state, "networks": o.networks, "msg": o.msg.text()})

    def notice(self, text):
        self.web.publish("notice", {"text": text, "t": time.time()})

    def settings_part(self):
        s = self.settings; n = self.w.notifier
        self.web.publish("settings", {
            "values": {k: s.get(k, v) for k, v in DEFAULTS.items()},
            "tones": [{"cat": c, "name": name, "rel": rel} for c, name, rel in list_tones(self.tones)],
            "channels": [{"key": k, "name": v[0], "color": v[1]} for k, v in CHANNELS.items()],
            "regions": [{"key": k, "name": v[0]} for k, v in REGIONS.items()],
            "genres": [{"key": k, "name": v[0]} for k, v in GENRES.items()],
            "record": {"pre": PRE_S, "ring_default": RING_S},
            "looks": [{"key": k, "name": v["name"], "about": v["about"], "colors": v["colors"]} for k, v in looks.LOOKS.items()],
            "festivals": [{"key": k, "name": v[0]} for k, v in FESTIVALS.items()],
            "upcoming": [{"name": FESTIVALS[k][0], "first": f"{a:%a %d %b}", "last": f"{b:%a %d %b %Y}"}
                         for k, a, b in upcoming(__import__("datetime").date.today(), self.w.cfg_festivals())],
            "notify": {"topic": s.get("notify_topic", ""), "server": n.server, "encryption": n.encryption()},
            "web": {"addresses": [{"name": a, "url": u} for a, u in self.addresses], "secure_url": secure_url(),
                    "push": push.available(), "devices": push.listing()},
            "outdoor": {"themes": OUTDOOR_THEMES, "bells": [{"name": a, "color": c} for a, c in OUTDOOR_BELLS],
                        "styles": [{"name": name, "icon": next((f"/bells/{p.name}" for p in BELL_ICONS.glob(f"{i}_*.png")), "")}
                                   for i, name in enumerate(OUTDOOR_STYLES)],
                        "chimes": OUTDOOR_CHIMES, "volumes": [{"name": a, "value": v} for a, v in OUTDOOR_VOLUMES],
                        "durations": OUTDOOR_DURATIONS}})

    # ---------- ring alerts on phones ----------
    def sub_claim(self):
        return secure_url() or "mailto:doorbell@example.com"

    def ring_started(self, source):
        self.web.ring_token = secrets.token_urlsafe(16); self.snap_sent = source != "MQTT"
        self.rang_text = time.strftime("%I:%M %p").lstrip("0")
        if source == "MQTT":  # a real press (not the demo)
            push.send(self.ring_payload(""), self.sub_claim(), ttl=60)

    def ring_payload(self, image, update=False):
        return {"type": "ring", "title": "Someone is at the door", "body": f"Rang at {self.rang_text} · tap to see who it is",
                "token": self.web.ring_token, "image": image, "update": update, "time": time.time()}

    def frame(self, img):
        """The first camera picture of a ring goes to the phones too (Android shows it in the notification)."""
        if self.snap_sent or not self.web.ring_token: return
        self.snap_sent = True
        buf = QBuffer(); buf.open(QIODevice.WriteOnly)
        img.scaledToWidth(min(720, img.width()), Qt.SmoothTransformation).save(buf, "JPEG", 78)
        token = self.web.add_snap(bytes(buf.data()))
        push.send(self.ring_payload(f"/api/snap/{token}.jpg", update=True), self.sub_claim(), ttl=60)

    def ring_ended(self, source):
        if not self.web.ring_token: return
        self.web.ring_token = None
        how = {"TIMER": "no one answered", "TOUCH": "answered", "MQTT": "stopped at the door"}.get(source, "stopped")
        push.send({"type": "ended", "title": "Doorbell", "body": f"Rang at {self.rang_text} · {how}", "update": True,
                   "time": time.time()}, self.sub_claim(), ttl=300, urgency="normal")

    # ---------- actions from browsers ----------
    def on_action(self, what, req):
        data, reply = req["data"] or {}, req["reply"]
        fn = getattr(self, "do_" + what, None)
        if fn is None: reply({"ok": False, "error": f"unknown action {what}"}); return
        try:
            result = fn(data, reply)
            if result is not ASYNC: reply(result)
        except Exception as e:
            traceback.print_exc(); reply({"ok": False, "error": str(e)})

    def later(self, reply, job):
        """Runs `job` (slow: network, camera) on a worker thread; its result is the answer."""
        def run():
            try: reply(job())
            except Exception as e: reply({"ok": False, "error": str(e)})
        threading.Thread(target=run, daemon=True).start(); return ASYNC

    def do_stop(self, d, _r):
        self.w.on_voice_command("stop", None, "Stopped from the notification" if d.get("via") == "notification" else "Stopped from a phone")

    def do_mute(self, d, _r):
        self.w.on_voice_command("mute", max(1, min(1440, int(d.get("minutes", 60)))), "Bell muted from a phone")

    def do_unmute(self, _d, _r):
        self.w.on_voice_command("unmute", None, "Bell on again")

    def do_delete(self, d, _r):
        times = {float(t) for t in d.get("times", [])}
        self.w.recorder.delete_many([e for e in self.w.recorder.entries if e["time"] in times]); self.w.events_page.refresh()
        self.events()

    def do_set(self, d, _r):
        key, value = d.get("key"), d.get("value")
        lists = {"news_channels": (CHANNELS, DEFAULT_CHANNELS), "news_regions": (REGIONS, ["india"]), "news_genres": (GENRES, ["top"])}
        if key == "tone":
            if value not in {rel for _, _, rel in list_tones(self.tones)}: return {"ok": False, "error": "no such tone"}
        elif key in ("intercom", "notify", "festival_themes", "festival_tones", "record_audio"): value = bool(value)
        elif key in lists:
            value = [k for k in value if k in lists[key][0]] or lists[key][1]
        elif key == "offline_alert_min":
            if value not in (0, 5, 15, 60): return {"ok": False, "error": "not a choice"}
        elif key == "record_seconds":  # 1 s up to the ring's length
            top = max(1, int(self.w.settings.outdoor.state.get("ring_seconds") or RING_S))
            if not isinstance(value, int) or not 1 <= value <= top: return {"ok": False, "error": f"1 to {top} seconds"}
        elif key == "look":
            if value not in looks.LOOKS: return {"ok": False, "error": "no such look"}
        elif key == "home_view":
            if value not in ("news", "photos"): return {"ok": False}
            self.w.home.set_view(value); return {"ok": True}  # the wall saves it itself
        else: return {"ok": False, "error": "not a setting"}
        self.settings[key] = value
        if key == "news_regions": self.settings.pop("news_region", None)
        self.save()
        if key in lists: self.w.news.refresh()
        if key.startswith("festival_"): self.w.check_festival()
        if key == "record_audio": self.w.recorder.buffer.restart()
        if key == "look": self.w.apply_look()
        self.w.settings.sync(); self.settings_part(); self.state()

    def do_play_tone(self, d, _r):
        rel = d.get("rel") or self.settings.get("tone", DEFAULTS["tone"])
        if rel not in {r for _, _, r in list_tones(self.tones)}: return {"ok": False, "error": "no such tone"}
        if self.w.active: return {"ok": False, "error": "Not while the bell rings"}
        self.w.preview(self.tones / rel)

    def do_speaker(self, d, _r):
        job, mac = d.get("job"), d.get("mac")
        if job == "test": self.w.preview(self.w.audio.tone()); return
        if job == "volume": self.w.bt.request("volume", value=max(0, min(100, int(d.get("value", 50))))); return
        if job not in ("list", "scan", "connect", "disconnect", "forget"): return {"ok": False, "error": "unknown"}
        dev = next((x for x in self.speaker["devices"] if x["mac"] == mac), None)
        if job in ("connect", "disconnect", "forget") and not dev: return {"ok": False, "error": "Choose a speaker first"}
        self.w.bt.request(job, mac)
        if job == "connect": self.settings["speaker"] = {"mac": dev["mac"], "name": dev["name"]}; self.save()
        if job == "forget" and self.settings.get("speaker", {}).get("mac") == mac: self.settings.pop("speaker"); self.save()

    def do_festival_try(self, d, _r):
        key = d.get("key") or ""
        if key and key not in FESTIVALS: return {"ok": False}
        self.w.preview_festival(key); self.state()

    def do_notify_test(self, _d, _r):
        self.notice("Sending…")
        self.w.notifier.send("Doorbell test", "Notifications from the indoor unit work.", tags="white_check_mark",
                             priority="default", force=True)

    def do_notify_topic(self, _d, _r):
        from notify import new_topic
        self.settings["notify_topic"] = new_topic(); self.save(); self.w.settings.phone.show_topic(); self.settings_part()

    def _camera(self, d):
        """The saved camera with the browser's changes; an empty password keeps the saved one."""
        cam = camera_cfg.load()
        for k in ("ip", "user", "main", "sub"):
            if k in d: cam[k] = str(d[k]).strip()
        if "port" in d: cam["port"] = int(d["port"] or 554)
        if d.get("password"): cam["password"] = str(d["password"])
        return cam

    def do_camera_find(self, _d, reply):
        return self.later(reply, lambda: {"ok": True, "cameras": [{"ip": ip, "name": n} for ip, n in camera_cfg.find_cameras()]})

    def do_camera_test(self, d, reply):
        cam = self._camera(d)
        def job():
            try: import cv2
            except ImportError: cv2 = None
            ok, res = camera_cfg.test(cam, cv2)
            if not ok: return {"ok": False, "error": res}
            h, w = res.shape[:2]; jpg = cv2.imencode(".jpg", res, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
            return {"ok": True, "size": f"{w}×{h}", "jpeg": base64.b64encode(jpg).decode()}
        return self.later(reply, job)

    def do_camera_save(self, d, _r):
        camera_cfg.save(self._camera(d)); self.w.recorder.buffer.restart()
        self.w.settings.camera.cam = camera_cfg.load(); self.w.settings.camera.show_values(); self.camera(); self.state()

    def do_outdoor(self, d, _r):
        change = d.get("change") or {}
        allowed = (set(change) <= OUTDOOR_KEYS or set(change) == {"network"} or
                   (set(change) == {"command"} and change["command"] in ("screen_on", "screen_off", "wifi_scan")))
        if not change or not allowed: return {"ok": False, "error": "not an outdoor setting"}
        if not self.w.send_outdoor(change): return {"ok": False, "error": "Not sent: MQTT is not connected"}
        self.w.settings.outdoor.msg.setText("Sent from a phone · waiting for the outdoor unit to confirm")
        self.outdoor()

    def do_push_changed(self, _d, _r):
        self.settings_part()

    def do_push_test(self, d, _r):
        push.send({"type": "test", "title": "Doorbell", "body": "Ring alerts work on this device.", "time": time.time()},
                  self.sub_claim(), ttl=300, urgency="normal", only=d.get("id"))
