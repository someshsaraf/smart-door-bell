import json, os, signal, sys, threading, time
from pathlib import Path
# RTSP over TCP is far more reliable than UDP on Wi-Fi; the 5 s timeout keeps a
# dead camera from blocking the capture thread. Must be set before cv2 loads.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;5000000")
# SDL (pygame) otherwise swallows SIGTERM, so `kill` / systemd could not stop the app.
os.environ.setdefault("SDL_NO_SIGNAL_HANDLERS", "1")
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread, QVariantAnimation, QEasingCurve, QRectF, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame, QStackedWidget,
                               QSizePolicy, QGraphicsDropShadowEffect)
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None
try:
    import pygame
except ImportError:
    pygame = None
try:
    import cv2
except ImportError:
    cv2 = None

import datetime as dt, math, random
import festive_art
from string import Template
from bluetooth import Bluetooth
from festivals import current as current_festival, greeting as festival_greeting
from news import News, ago
from settings_ui import SettingsPage, this_ip
from intercom import Intercom, PORT as TALK_PORT
from notify import Notifier
import camera_cfg

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text())
TONES = ROOT / "assets" / "tones"
# Choices made on the settings screen (tone, speaker). config.json stays hand-edited setup.
SETTINGS_FILE = ROOT / "settings.json"
try: SETTINGS = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError): SETTINGS = {}
def save_settings():
    tmp = SETTINGS_FILE.with_suffix(".tmp"); tmp.write_text(json.dumps(SETTINGS, indent=2), encoding="utf-8"); tmp.replace(SETTINGS_FILE)
def topic(key, default): return CFG["mqtt"].get(key, default)
T_OUT_STATE = topic("topic_outdoor_state", "home/doorbell/outdoor/state")
T_OUT_ONLINE = topic("topic_outdoor_online", "home/doorbell/outdoor/online")
T_OUT_CONFIG = topic("topic_outdoor_config", "home/doorbell/outdoor/config")
T_OUT_SCAN = topic("topic_outdoor_scan", "home/doorbell/outdoor/wifi_scan")
T_FESTIVAL = topic("topic_festival", "home/doorbell/festival")  # retained, read by the doorbell
T_TALK = topic("topic_talk", "home/doorbell/talk")  # intercom call start / end, to the doorbell
# Festival running now with festival tones on (key, e.g. "diwali"), else None; set by Window.check_festival.
FESTIVAL = {"key": None}
FESTIVAL_ART = ROOT / "assets" / "festivals"  # optional own wallpapers: assets/festivals/<key>/*.jpg
FESTIVAL_TONES = {"diwali": "shehnai_swagat.wav", "christmas": "jingle_bells.wav", "new_year": "auld_lang_syne.wav"}
class Signals(QObject):
    message = Signal(str, str)
    status = Signal(bool, str)

class MQTT:
    def __init__(self, signals):
        self.s = signals; self.client = None; self.connected = False
    def start(self):
        if mqtt is None:
            self.s.status.emit(False, "paho-mqtt missing"); return
        c = CFG["mqtt"]
        try:
            try: self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=c["client_id"])
            except (AttributeError, TypeError): self.client = mqtt.Client(client_id=c["client_id"])
            if c.get("username"): self.client.username_pw_set(c["username"], c.get("password", ""))
            self.client.on_connect = self.on_connect; self.client.on_disconnect = self.on_disconnect; self.client.on_message = self.on_message
            self.client.connect_async(c["host"], int(c["port"]), 30); self.client.loop_start()
        except Exception as e: self.s.status.emit(False, str(e))
    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        try: ok = int(reason_code) == 0
        except Exception: ok = str(reason_code).lower() in ("success", "0")
        self.connected = ok
        if ok:
            for t in (CFG["mqtt"]["topic_start"], CFG["mqtt"]["topic_stop"], T_OUT_STATE, T_OUT_ONLINE, T_OUT_SCAN):
                client.subscribe(t, qos=1)
            self.s.status.emit(True, "MQTT connected")
        else: self.s.status.emit(False, f"MQTT connection failed: {reason_code}")
    def on_disconnect(self, *args): self.connected = False; self.s.status.emit(False, "MQTT disconnected")
    def on_message(self, client, userdata, msg): self.s.message.emit(msg.topic, msg.payload.decode("utf-8", "replace"))
    def publish(self, topic, payload, retain=False):
        if not (self.client and self.connected): return False
        self.client.publish(topic, json.dumps(payload), qos=1, retain=retain); return True
    def close(self):
        if self.client:
            self.client.loop_stop(); self.client.disconnect()

class Audio:
    """Plays the chosen bell tone. The mixer is reopened for every sound so it
    always uses the current output, e.g. a speaker connected after start-up."""
    def tone(self):
        name = FESTIVAL_TONES.get(FESTIVAL["key"]) or SETTINGS.get("tone", "ding_dong.wav")  # festival tone wins
        path = TONES / name
        if not path.exists(): path = TONES / SETTINGS.get("tone", "ding_dong.wav")
        return path if path.exists() else ROOT / CFG["bell_audio"]
    def play(self, path=None, loop=True):
        if pygame is None: print("Audio unavailable: pygame missing", flush=True); return
        try:
            if pygame.mixer.get_init(): pygame.mixer.quit()
            pygame.mixer.init()
            pygame.mixer.music.load(str(path or self.tone())); pygame.mixer.music.play(-1 if loop else 0)
        except Exception as e: print("Audio unavailable:", e, flush=True)
    def stop(self):
        if pygame and pygame.mixer.get_init(): pygame.mixer.music.stop()

class Camera(QThread):
    """Reads the VIGI RTSP stream while a ring is active and hands frames to the UI.
    Only the newest frame is delivered; if the UI is busy, frames are dropped
    rather than queued, so the picture never lags behind live."""
    frame = Signal(QImage)
    state = Signal(str)
    def __init__(self, url):
        super().__init__(); self.url = url; self.idle = threading.Event(); self.idle.set()
    def run(self):
        while not self.isInterruptionRequested():
            self.state.emit("Connecting to camera…")
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                cap.release(); self.state.emit("Camera unavailable · retrying")
                for _ in range(20):
                    if self.isInterruptionRequested(): return
                    self.msleep(100)
                continue
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.state.emit("")
            while not self.isInterruptionRequested():
                ok, img = cap.read()
                if not ok: self.state.emit("Camera stream lost · reconnecting"); break
                if not self.idle.is_set(): continue
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB); h, w, _ = rgb.shape
                self.idle.clear(); self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())
            cap.release()
    def stop(self):
        self.requestInterruption(); self.wait(6000)

def label(text, obj=None):
    w = QLabel(text)
    if obj: w.setObjectName(obj)
    return w

class Scenic(QWidget):
    """Full-screen backdrop of the dashboard, in one of two modes:
    photos: every interval the next picture slides in from the right;
    news:   the wallpaper stays, darkened, and the next headline slides in.
    Pictures fill the frame (cropped, never stretched) and are scaled once per size."""
    def __init__(self, folder, photo_s, news_s):
        super().__init__()
        self.paths = self.base_paths = pictures(folder)
        try: self.credits = json.loads((folder / "credits.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): self.credits = {}
        self.idx = 0; self.pos = 0.0; self.cache = {}
        self.mode = "photos"; self.news = []; self.news_idx = 0; self.news_note = "Loading news…"
        self.intervals = {"photos": int(photo_s * 1000), "news": int(news_s * 1000)}
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1100, easingCurve=QEasingCurve.InOutCubic)
        self.anim.valueChanged.connect(self._step); self.anim.finished.connect(self._done)
        self.timer = QTimer(self); self.timer.timeout.connect(self.next)
    def set_festival(self, key):
        """Festival wallpapers: pictures in assets/festivals/<key>/ if any, else
        one painted in code ("@key"). None returns to the normal pictures."""
        self.paths = (pictures(FESTIVAL_ART / key) or [f"@{key}"]) if key else self.base_paths
        self.idx = 0; self.pos = 0.0; self.anim.stop(); self.cache.clear(); self.update()
    def set_mode(self, mode):
        self.mode = mode; self.anim.stop(); self.pos = 0.0
        self.timer.start(self.intervals[mode]); self.update()
    def set_news(self, items):
        self.news = items; self.news_idx = 0 if self.news_idx >= len(items) else self.news_idx; self.update()
    def set_news_note(self, text):
        self.news_note = text
        if not self.news: self.update()
    def next(self):
        if len(self.news if self.mode == "news" else self.paths) < 2: return
        if self.anim.state() != QVariantAnimation.Running: self.anim.start()
    def _step(self, v): self.pos = v; self.update()
    def _done(self):
        if self.mode == "news": self.news_idx = (self.news_idx + 1) % len(self.news)
        else: self.idx = (self.idx + 1) % len(self.paths)
        self.pos = 0.0; self.update()
    def _pixmap(self, i):
        key = (i, self.width(), self.height())
        if key not in self.cache:
            if len(self.cache) > 4: self.cache.clear()  # only the current and next are ever drawn
            src = self.paths[i]
            if isinstance(src, str): self.cache[key] = festive_art.paint(src[1:], self.width(), self.height()); return self.cache[key]
            pm = QPixmap(str(src)).scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x, y = (pm.width() - self.width()) // 2, (pm.height() - self.height()) // 2
            self.cache[key] = pm.copy(x, y, self.width(), self.height())
        return self.cache[key]
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height(); r = QRectF(self.rect())
        if not self.paths:
            p.fillRect(r, QColor("#1e4560")); p.setPen(QColor("#dce8f7"))
            p.drawText(r, Qt.AlignCenter, "Add landscape pictures to assets/scenic/"); return
        shift = int(self.pos * w); n = len(self.paths)
        if self.mode == "news": self._paint_news(p, w, h, shift); return
        p.drawPixmap(-shift, 0, self._pixmap(self.idx))
        if shift: p.drawPixmap(w - shift, 0, self._pixmap((self.idx + 1) % n))
        # Soft shades so the clock (top) and dots/credit/events (bottom) read on any picture.
        for y0, y1, a0, a1 in ((0, h * 0.45, 160, 0), (h * 0.65, h, 0, 150)):
            g = QLinearGradient(0, y0, 0, y1); g.setColorAt(0, QColor(0, 0, 0, a0)); g.setColorAt(1, QColor(0, 0, 0, a1))
            p.fillRect(QRectF(0, y0, w, y1 - y0), g)
        # page dots, bottom centre; the active one moves halfway through a slide
        active = self.idx if self.pos < 0.5 else (self.idx + 1) % n
        p.setPen(Qt.NoPen)
        for i in range(n if n > 1 else 0):
            p.setBrush(QColor(255, 255, 255, 240 if i == active else 110)); rad = 5 if i == active else 3.5
            p.drawEllipse(QPointF(w / 2 + (i - (n - 1) / 2) * 18, h - 26), rad, rad)
        name = self.credits.get(getattr(self.paths[self.idx], "name", "")) if not shift else None
        if name:
            f = QFont(self.font()); f.setPixelSize(12); p.setFont(f); p.setPen(QColor(255, 255, 255, 190))
            p.drawText(QRectF(28, h - 38, w / 2, 24), Qt.AlignLeft | Qt.AlignVCenter, f"Photo: {name} / Unsplash")
    # Headline area: right of the shortcut rail, below the clock, clear of the events card.
    NEWS_X = 170
    def _font(self, px, bold=False):
        f = QFont(self.font()); f.setPixelSize(px); f.setBold(bold); return f
    def _paint_news(self, p, w, h, shift):
        p.drawPixmap(0, 0, self._pixmap(self.idx)); p.fillRect(QRectF(0, 0, w, h), QColor(6, 10, 18, 190))
        x, top, width = self.NEWS_X, int(h * 0.30), int(w * 0.6)
        if not self.news:
            p.setFont(self._font(26)); p.setPen(QColor(255, 255, 255, 200))
            p.drawText(QRectF(x, top, width, 120), Qt.TextWordWrap, self.news_note); return
        n = len(self.news)
        p.save(); p.setClipRect(QRectF(x - 20, top - 10, w - x, h * 0.42))
        stories = [(self.news_idx, -shift)] + ([((self.news_idx + 1) % n, w - shift)] if shift else [])
        for i, off in stories:
            s = self.news[i]
            p.setFont(self._font(15, True)); p.setPen(QColor(PALETTE["tag"]))
            tag = "   ·   ".join(t for t in (s.get("region", "").upper(), s.get("genre", "").upper(), s.get("source", ""),
                                             ago(s.get("time", 0))) if t)
            p.drawText(QRectF(x + off, top, width, 24), Qt.AlignLeft | Qt.AlignVCenter, tag)
            p.setFont(self._font(44, True)); p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(x + off, top + 34, width, h * 0.42 - 44), Qt.TextWordWrap, s["title"])
        p.restore()
        # up next: the following three headlines, one line each
        y = top + h * 0.42 + 12
        p.setFont(self._font(13, True)); p.setPen(QColor(255, 255, 255, 150)); p.drawText(QRectF(x, y, width, 20), Qt.AlignLeft, "UP NEXT")
        p.setFont(self._font(19)); fm = p.fontMetrics()
        for k in range(1, min(4, n)):
            s = self.news[(self.news_idx + k) % n]; y += 34
            p.setPen(QColor(255, 255, 255, 215 - k * 30))
            p.drawText(QRectF(x, y, width, 30), Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(s["title"], Qt.ElideRight, width))
        p.setFont(self._font(12)); p.setPen(QColor(255, 255, 255, 150))
        p.drawText(QRectF(0, h - 38, w, 24), Qt.AlignCenter, f"{self.news_idx + 1} / {n}   ·   Google News")
    def resizeEvent(self, e):
        self.cache.clear(); super().resizeEvent(e)

def shadow(w, blur=24):
    """Soft drop shadow so text stays readable on bright photos."""
    e = QGraphicsDropShadowEffect(w); e.setBlurRadius(blur); e.setOffset(0, 2); e.setColor(QColor(0, 0, 0, 180)); w.setGraphicsEffect(e)

def tile(icon, text):
    """Small square shortcut on the left rail: icon above a short caption."""
    b = QPushButton(); b.setObjectName("tile"); b.setFixedSize(88, 84)
    lay = QVBoxLayout(b); lay.setContentsMargins(4, 8, 4, 8); lay.setSpacing(2)
    b.labels = []
    for t, obj in ((icon, "tileIcon"), (text, "tileText")):
        l = label(t, obj); l.setAlignment(Qt.AlignCenter); l.setAttribute(Qt.WA_TransparentForMouseEvents); lay.addWidget(l); b.labels.append(l)
    return b

def pictures(folder):
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")) if folder.is_dir() else []

class FestiveOverlay(QWidget):
    """Festival decoration over the dashboard: a greeting banner and light
    particles (Diwali: golden sparks rising, Christmas: snow, New Year:
    confetti). Transparent to touches; animates only while visible."""
    LOOK = {  # particle count, colours, banner text colour
        "diwali": (60, [(255, 200, 80), (255, 140, 40), (255, 90, 140)], "#ffc24a"),
        "christmas": (110, [(255, 255, 255)], "#ff6b6b"),
        "new_year": (80, [(255, 205, 60), (255, 70, 200), (60, 220, 255), (150, 255, 110), (255, 255, 255)], "#ffd54a"),
    }
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents); self.setAttribute(Qt.WA_NoSystemBackground)
        self.key = None; self.text = ""; self.parts = []
        self.timer = QTimer(self); self.timer.timeout.connect(self.step); self.hide()
    def set_festival(self, key, text):
        self.key, self.text = key, text
        if not key:
            self.timer.stop(); self.hide(); return
        count, colors, _ = self.LOOK[key]
        self.parts = [self.spawn(colors, scatter=True) for _ in range(count)]
        self.setGeometry(self.parentWidget().rect()); self.show(); self.raise_(); self.timer.start(40)
    def spawn(self, colors, scatter=False):
        w, h = max(1, self.width()), max(1, self.height())
        p = {"x": random.uniform(0, w), "c": random.choice(colors), "ph": random.uniform(0, 6.3), "rot": random.uniform(0, 360)}
        if self.key == "diwali":   # sparks drift up from the bottom
            p.update(y=random.uniform(0, h) if scatter else h + 10, vy=-random.uniform(0.5, 1.5), r=random.uniform(1.5, 3.2))
        elif self.key == "christmas":  # snow falls from the top
            p.update(y=random.uniform(0, h) if scatter else -10, vy=random.uniform(0.6, 2.0), r=random.uniform(1.5, 4.5))
        else:  # confetti
            p.update(y=random.uniform(0, h) if scatter else -12, vy=random.uniform(1.2, 2.6), r=random.uniform(4, 7))
        return p
    def step(self):
        if not self.isVisible(): return
        colors = self.LOOK[self.key][1]; h = self.height()
        for i, p in enumerate(self.parts):
            p["ph"] += 0.05; p["y"] += p["vy"]; p["x"] += math.sin(p["ph"]) * 0.6; p["rot"] += 4
            if p["y"] < -20 or p["y"] > h + 20: self.parts[i] = self.spawn(colors)
        self.update()
    def paintEvent(self, e):
        if not self.key: return
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        for q in self.parts:
            r, g, b = q["c"]
            if self.key == "diwali":  # soft glow and a bright, flickering core
                a = int(120 + 100 * math.sin(q["ph"] * 3))
                grad = QRadialGradient(QPointF(q["x"], q["y"]), q["r"] * 4)
                grad.setColorAt(0, QColor(r, g, b, max(0, a))); grad.setColorAt(1, QColor(r, g, b, 0))
                p.setBrush(grad); p.drawEllipse(QPointF(q["x"], q["y"]), q["r"] * 4, q["r"] * 4)
                p.setBrush(QColor(255, 245, 210, 230)); p.drawEllipse(QPointF(q["x"], q["y"]), q["r"] * 0.7, q["r"] * 0.7)
            elif self.key == "christmas":
                p.setBrush(QColor(r, g, b, 190)); p.drawEllipse(QPointF(q["x"], q["y"]), q["r"], q["r"])
            else:
                p.save(); p.translate(q["x"], q["y"]); p.rotate(q["rot"]); p.setBrush(QColor(r, g, b, 220))
                p.drawRect(QRectF(-q["r"] / 2, -q["r"], q["r"], q["r"] * 2)); p.restore()
        # greeting banner, top right under the MQTT status (the big clock owns the top left)
        f = QFont(self.font()); f.setPixelSize(30); f.setBold(True); p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(self.text) + 60; box = QRectF(self.width() - tw - 36, 78, tw, 56)
        p.setBrush(QColor(10, 16, 26, 160)); p.setPen(QColor(self.LOOK[self.key][2])); p.drawRoundedRect(box, 28, 28)
        p.drawText(box, Qt.AlignCenter, self.text)

class Dashboard(QFrame):
    """Full-screen wallpaper with the clock, a slim shortcut rail and recent
    events floating on top of it in translucent panels."""
    open_settings = Signal()
    open_door = Signal()
    view_changed = Signal(str)  # "news" or "photos"
    def __init__(self, view="news"):
        super().__init__(); self.setObjectName("dashboard")
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0)
        sc=CFG.get("scenic",{})
        self.scenic=Scenic(ROOT/sc.get("folder","assets/scenic"), sc.get("interval_seconds",15),
                           CFG.get("news",{}).get("interval_seconds",12)); root.addWidget(self.scenic)

        over = QHBoxLayout(self.scenic); over.setContentsMargins(28,28,28,52); over.setSpacing(28)
        rail = QFrame(); rail.setObjectName("glass"); rl = QVBoxLayout(rail); rl.setContentsMargins(10,10,10,10); rl.setSpacing(10)
        door = tile("⌂","Front door"); door.clicked.connect(self.open_door.emit); rl.addWidget(door)
        # Switches between news and photos; it is labelled with the view it switches to.
        self.switch = tile("", ""); self.switch.clicked.connect(lambda: self._set_view("news" if self.view == "photos" else "photos"))
        rl.addWidget(self.switch)
        gear = tile("⚙","Settings"); gear.clicked.connect(self.open_settings.emit); rl.addWidget(gear)
        over.addWidget(rail, 0, Qt.AlignVCenter)
        self._set_view("photos" if view == "photos" else "news", notify=False)

        main = QVBoxLayout(); main.setSpacing(0)
        top = QHBoxLayout(); col = QVBoxLayout(); col.setSpacing(0)
        self.clock = label("", "heroClock"); self.date = label("", "heroDate")
        for l in (self.clock, self.date): shadow(l); col.addWidget(l)
        top.addLayout(col); top.addStretch()
        self.mqtt_status = label("○ MQTT starting…", "status"); top.addWidget(self.mqtt_status, 0, Qt.AlignTop)
        main.addLayout(top); main.addStretch()
        bottom = QHBoxLayout(); bottom.addStretch()
        events = QFrame(); events.setObjectName("glass"); events.setFixedWidth(360)
        el = QVBoxLayout(events); el.setContentsMargins(20,14,20,16); el.setSpacing(6)
        el.addWidget(label("RECENT EVENTS","glassTitle"))
        self.events=label("No recent events","eventText"); self.events.setWordWrap(True); el.addWidget(self.events)
        bottom.addWidget(events, 0, Qt.AlignBottom); main.addLayout(bottom)
        over.addLayout(main, 1)
        self.festive = FestiveOverlay(self.scenic)  # on top of everything; hidden outside festivals
    def resizeEvent(self, e):
        super().resizeEvent(e); self.festive.setGeometry(self.scenic.rect())
    def _set_view(self, mode, notify=True):
        self.view = mode; self.scenic.set_mode(mode)
        icon, text = ("☰", "News") if mode == "photos" else ("▣", "Photos")
        self.switch.labels[0].setText(icon); self.switch.labels[1].setText(text)
        if notify: self.view_changed.emit(mode)
    def update_clock(self):
        now=time.localtime(); self.date.setText(time.strftime("%A, %d %B",now)); self.clock.setText(time.strftime("%I:%M %p",now).lstrip("0"))
    def set_status(self, ok, msg):
        self.mqtt_status.setText(("● " if ok else "○ ")+msg); self.mqtt_status.setProperty("connected",ok)
        self.mqtt_status.style().unpolish(self.mqtt_status); self.mqtt_status.style().polish(self.mqtt_status)
    def add_event(self, msg):  # not "event": that would override QWidget.event()
        old=self.events.text()
        lines=[] if old=="No recent events" else old.splitlines()
        self.events.setText("\n".join((["• "+time.strftime("%H:%M")+"  "+msg]+lines)[:4]))

class RingPage(QFrame):
    """Visitor alert: live camera on the left, countdown and a large STOP on the right."""
    stop = Signal()
    talk = Signal()
    def __init__(self):
        super().__init__(); self.setObjectName("ring")
        root=QHBoxLayout(self); root.setContentsMargins(24,24,24,24); root.setSpacing(24)

        video=QFrame(); video.setObjectName("video"); vl=QVBoxLayout(video); vl.setContentsMargins(0,0,0,0)
        self.view=label("","videoView"); self.view.setAlignment(Qt.AlignCenter)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)  # never resized by the frames it shows
        vl.addWidget(self.view, 1)  # the picture takes all the room; the note below only shows with a message
        self.cam_note=label("", "camNote"); self.cam_note.setAlignment(Qt.AlignCenter)
        self.cam_note.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed); self.cam_note.hide(); vl.addWidget(self.cam_note)
        root.addWidget(video,3)

        side=QVBoxLayout(); side.setSpacing(10)
        self.section=label("FRONT DOOR · VISITOR ALERT","section"); side.addWidget(self.section)
        side.addStretch()
        self.bell=label("♪","bell"); self.bell.setAlignment(Qt.AlignCenter); side.addWidget(self.bell)
        self.title=label("Someone is at the door","ringTitle"); self.title.setAlignment(Qt.AlignCenter); self.title.setWordWrap(True); side.addWidget(self.title)
        self.subtitle=label("Bell is playing","secondary"); self.subtitle.setAlignment(Qt.AlignCenter); side.addWidget(self.subtitle)
        self.count=label("00:30","count"); self.count.setAlignment(Qt.AlignCenter); side.addWidget(self.count)
        self.call_note=label("","secondary"); self.call_note.setAlignment(Qt.AlignCenter); self.call_note.setWordWrap(True); side.addWidget(self.call_note)
        side.addStretch()
        self.talk_btn=QPushButton("☎  Talk"); self.talk_btn.setObjectName("talk"); self.talk_btn.setMinimumHeight(96)
        self.talk_btn.clicked.connect(self.talk.emit); side.addWidget(self.talk_btn)
        self.stop_btn=QPushButton("STOP"); self.stop_btn.setObjectName("stop"); self.stop_btn.setMinimumHeight(120)
        self.stop_btn.clicked.connect(self.stop.emit); side.addWidget(self.stop_btn)
        panel=QFrame(); panel.setObjectName("side"); panel.setLayout(side); panel.setFixedWidth(330)
        root.addWidget(panel)
        self.last=None
    def set_mode(self, ringing):
        """Visitor alert (countdown, STOP) or the live door view from the Front door tile (CLOSE)."""
        self.section.setText("FRONT DOOR · VISITOR ALERT" if ringing else "FRONT DOOR · LIVE")
        self.bell.setText("♪" if ringing else "⌂"); self.title.setText("Someone is at the door" if ringing else "Front door")
        self.subtitle.setVisible(ringing); self.count.setVisible(ringing); self.stop_btn.setText("STOP" if ringing else "CLOSE")
        self.talk_btn.setVisible(SETTINGS.get("intercom", False))  # trial feature, off by default (Settings > Speaker)
    def set_call(self, active, note=""):
        self.talk_btn.setText("☎  End call" if active else "☎  Talk"); self.talk_btn.setProperty("calling", active)
        self.talk_btn.style().unpolish(self.talk_btn); self.talk_btn.style().polish(self.talk_btn); self.call_note.setText(note)
    def show_frame(self, img):
        self.last=img
        self.view.setPixmap(QPixmap.fromImage(img).scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    def clear_video(self, note):
        self.last=None; self.view.clear(); self.set_note(note)
    def set_note(self, text):
        self.cam_note.setText(text); self.cam_note.setVisible(bool(text))
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.last is not None: self.show_frame(self.last)

class Window(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Indoor Doorbell Dashboard"); self.setMinimumSize(800,450)
        self.active=False; self.until=0; self.event_id=None; self.camera=None
        self.audio=Audio(); self.bt=Bluetooth(); self.door_ip=None
        self.intercom=Intercom()
        self.stack=QStackedWidget(); self.home=Dashboard(SETTINGS.get("home_view","news")); self.ring=RingPage()
        self.home.view_changed.connect(lambda v: (SETTINGS.__setitem__("home_view", v), save_settings()))
        self.news=News(SETTINGS, ROOT/"news_cache.json")
        self.news.updated.connect(self.home.scenic.set_news)
        self.news.failed.connect(lambda why: self.home.scenic.set_news_note(f"News unavailable ({why}). Retrying every minute."))
        self.news.start()
        self.notifier=Notifier(SETTINGS, CFG.get("notify",{}).get("server"), CFG.get("notify",{}).get("token"))
        self.settings=SettingsPage(self.bt, TONES, SETTINGS, save_settings, self.preview, self.send_outdoor, self.news.refresh,
                                   CFG.get("festivals"), self.notifier)
        self.settings.speaker.test_cb=lambda: self.preview(self.audio.tone())
        for page in (self.home, self.ring, self.settings): self.stack.addWidget(page)
        self.home.open_settings.connect(lambda: self.stack.setCurrentWidget(self.settings))
        self.settings.back.connect(lambda: (self.audio.stop(), self.stack.setCurrentWidget(self.home)))
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.addWidget(self.stack)
        self.ring.stop.connect(lambda: self.stop_ring("TOUCH"))
        self.ring.talk.connect(self.toggle_call)
        self.intercom.state.connect(lambda note: self.ring.set_call(True, note))
        self.intercom.ended.connect(self.call_ended)
        self.home.open_door.connect(self.open_door)
        if SETTINGS.get("speaker"): self.bt.request("reconnect", SETTINGS["speaker"]["mac"])
        self.sig=Signals(); self.sig.message.connect(self.handle); self.sig.status.connect(self.home.set_status)
        self.mqtt=MQTT(self.sig); self.mqtt.start()
        self.clock_timer=QTimer(self); self.clock_timer.timeout.connect(self.home.update_clock); self.clock_timer.start(1000); self.home.update_clock()
        self.tick=QTimer(self); self.tick.timeout.connect(self.countdown); self.tick.start(200)
        self.demo=QTimer(self)
        if CFG.get("demo_mode",False): self.demo.timeout.connect(self.demo_ring); self.demo.start(18000)
        # Festival themes: checked every minute; the result goes to the doorbell as a retained message.
        self.fest_sent=None; self.fest_preview=None  # last payload published; (key, monotonic end) of a trial
        self.sig.status.connect(lambda ok, _m: ok and (setattr(self, "fest_sent", None), QTimer.singleShot(500, self.check_festival)))
        self.settings.festival_changed.connect(self.check_festival); self.settings.festival_preview.connect(self.preview_festival)
        self.fest_timer=QTimer(self); self.fest_timer.timeout.connect(self.check_festival); self.fest_timer.start(60000)
        self.check_festival()
    def preview_festival(self, key):
        """Show a festival for one minute (Settings > Festivals > Try)."""
        self.fest_preview=(key, time.monotonic()+60) if key else None
        self.check_festival()
        if key: QTimer.singleShot(61000, self.check_festival)
    def check_festival(self):
        today=dt.date.today(); key=until=None
        if self.fest_preview and time.monotonic()<self.fest_preview[1]:
            key=self.fest_preview[0]; until=int(time.time()+self.fest_preview[1]-time.monotonic())
        else:
            self.fest_preview=None
            if SETTINGS.get("festival_themes", True):
                key, last=current_festival(today, CFG.get("festivals"))
                if key:  # runs until midnight after the last day
                    until=int(dt.datetime.combine(last+dt.timedelta(days=1), dt.time()).timestamp())
        tones=bool(key) and SETTINGS.get("festival_tones", True)
        FESTIVAL["key"]=key if tones else None
        text=festival_greeting(key, today) if key else ""
        if self.home.festive.key!=key or self.home.festive.text!=text: self.home.festive.set_festival(key, text)
        if key!=getattr(self, "look", None):  # wallpaper and page colours follow the festival
            self.look=key; style(QApplication.instance(), key); self.home.scenic.set_festival(key)
        payload={"festival":key or "none","until":until or 0,"greeting":text,"tones":tones}
        if payload!=self.fest_sent and self.mqtt.publish(T_FESTIVAL, payload, retain=True): self.fest_sent=payload
    def demo_ring(self):
        if not self.active: self.start_ring(CFG.get("default_timer_seconds",30),"DEMO")
    def preview(self, path):
        if not self.active: self.audio.play(path, loop=False)  # never over a real ring
    def send_outdoor(self, change):
        return self.mqtt.publish(T_OUT_CONFIG, change)
    def handle(self,topic,payload):
        c=CFG["mqtt"]
        if topic in (T_OUT_STATE, T_OUT_SCAN, T_OUT_ONLINE):
            o=self.settings.outdoor
            if topic==T_OUT_ONLINE: o.on_online(payload.strip()=="online"); return
            try: data=json.loads(payload)
            except ValueError: return
            if topic==T_OUT_STATE and data.get("ip"): self.door_ip=data["ip"]  # where call audio goes
            (o.on_state if topic==T_OUT_STATE else o.on_scan)(data); return
        if topic==c["topic_stop"]: self.stop_ring("MQTT"); return
        if topic!=c["topic_start"]: return
        try:
            data=json.loads(payload) if payload.strip().startswith("{") else {"timer":int(payload.strip())}
            cmd=str(data.get("command",data.get("action","start"))).lower()
            if cmd in ("stop","cancel"): self.stop_ring("MQTT"); return
            seconds=max(1,min(3600,int(data.get("timer",data.get("timer_seconds",CFG.get("default_timer_seconds",30))))))
            # Ack first, also for duplicates: the outdoor unit resends the start every
            # 2 s until it sees an ack carrying its event_id.
            self.mqtt.publish(c["topic_ack"],{"event_id":data.get("event_id"),"status":"duplicate" if self.active else "received"})
            if self.active: return  # already ringing: discard until the timer has run out
            self.start_ring(seconds,"MQTT",data.get("event_id"))
        except Exception as e: self.home.add_event("Invalid MQTT command: "+str(e))
    def open_door(self):
        """Front door tile: live camera and the intercom, no ring."""
        if self.active: return
        self.ring.set_mode(False); self.ring.set_call(False); self.stack.setCurrentWidget(self.ring); self.start_camera()
    def toggle_call(self):
        if self.intercom.active: self.end_call(); return
        if not SETTINGS.get("intercom", False): return
        if not self.door_ip: self.ring.set_call(False, "Doorbell address not known yet (it is sent when the doorbell connects)"); return
        self.audio.stop()  # the bell tone gives way to the call, and the speaker is switched to hands-free
        if pygame and pygame.mixer.get_init(): pygame.mixer.quit()
        if not self.mqtt.publish(T_TALK, {"command": "start", "host": this_ip(), "port": TALK_PORT}):
            self.ring.set_call(False, "Not connected to the doorbell (MQTT)"); return
        self.home.add_event("Talked to the door")
        self.intercom.start(self.door_ip, (SETTINGS.get("speaker") or {}).get("name")); self.ring.set_call(True, "Connecting…")
    def end_call(self):
        self.mqtt.publish(T_TALK, {"command": "end"}); self.intercom.stop()
    def call_ended(self):
        note=self.ring.call_note.text()
        self.ring.set_call(False, note if note.startswith("Call failed") else "Call ended")
        if self.active: self.until=max(self.until, time.monotonic()+10)  # a moment to see the door before the page closes
    def start_camera(self):
        if self.camera: return
        url=camera_cfg.url() or CFG.get("camera",{}).get("rtsp_url","")  # Settings > Camera, else config.json
        if not url: self.ring.clear_video("Camera not set up · Settings › Camera"); return
        if cv2 is None: self.ring.clear_video("OpenCV missing · sudo apt install python3-opencv"); return
        self.ring.clear_video("Connecting to camera…")
        self.camera=Camera(url); self.camera.frame.connect(self.on_frame); self.camera.state.connect(self.ring.set_note); self.camera.start()
    def on_frame(self, img):
        self.ring.show_frame(img)
        if self.camera: self.camera.idle.set()
    def stop_camera(self):
        if self.camera:
            cam=self.camera; self.camera=None
            cam.frame.disconnect(); cam.state.disconnect(); cam.stop()
        self.ring.clear_video("")
    def start_ring(self,seconds,source="MQTT",event_id=None):
        seconds=max(1,min(3600,int(seconds))); self.until=time.monotonic()+seconds; self.event_id=event_id
        self.ring.set_mode(True); self.ring.set_call(self.intercom.active)
        self.ring.count.setText(self.fmt(seconds)); self.ring.subtitle.setText(f"Bell is playing · {source}")
        self.stack.setCurrentWidget(self.ring); self.start_camera()
        if not self.intercom.active: self.audio.play()  # no bell tone over a call
        self.active=True; self.home.add_event(f"Doorbell started ({seconds}s)")
        if source=="MQTT":  # a real press (not the demo): tell the phones
            self.notifier.send("Doorbell", "Someone is at the front door · "+time.strftime("%I:%M %p").lstrip("0"))
        self.mqtt.publish(CFG["mqtt"]["topic_status"],{"state":"ringing","remaining_seconds":seconds,"event_id":event_id})
        self.demo.stop()
    def countdown(self):
        if not self.active:return
        if self.intercom.active: self.until=max(self.until, time.monotonic()+1)  # the page stays while talking
        remaining=max(0,int(self.until-time.monotonic()+0.999)); self.ring.count.setText(self.fmt(remaining))
        if remaining<=0:self.stop_ring("TIMER")
    def stop_ring(self,source="TOUCH"):
        if self.intercom.active and source in ("TOUCH", "MQTT"): self.end_call()
        if not self.active:  # the live door view closes
            self.stop_camera(); self.stack.setCurrentWidget(self.home); return
        self.active=False; self.audio.stop(); self.stop_camera(); self.stack.setCurrentWidget(self.home)
        self.home.add_event("Doorbell ended ("+source.lower()+")")
        # STOP pressed here: tell the outdoor unit so it returns to its main screen.
        # (On TIMER both sides time out by themselves; on MQTT the stop came from outside.)
        if source=="TOUCH":
            self.mqtt.publish(CFG["mqtt"]["topic_stop"],{"command":"stop","source":"indoor","event_id":self.event_id})
        self.mqtt.publish(CFG["mqtt"]["topic_status"],{"state":"idle","reason":source.lower(),"event_id":self.event_id})
        self.event_id=None
        if CFG.get("demo_mode",False): self.demo.start(18000)
    @staticmethod
    def fmt(s): return f"{s//60:02d}:{s%60:02d}"
    def closeEvent(self,event):
        self.intercom.stop(); self.audio.stop(); self.stop_camera(); self.mqtt.close(); self.bt.request("quit"); self.news.stop(); event.accept()

# Colours of every page; a festival swaps in its own set (see Window.check_festival).
PALETTES = {
    None: dict(bg="#0b111b", panel="#141f2d", button="#1b2a3d", border="#2c4058", line="#24364a", accent="#2f80ed",
               on_accent="#ffffff", muted="#8ea1b8", list="#0f1824", count="#93c5fd", tag="#7cc4ff"),
    "diwali": dict(bg="#1a0709", panel="#2a0e10", button="#3a1416", border="#6a2a22", line="#52201c", accent="#e8952a",
                   on_accent="#2a1200", muted="#d9a86b", list="#210a0c", count="#ffc24a", tag="#ffc24a"),
    "christmas": dict(bg="#071a10", panel="#0f2a1b", button="#15402a", border="#2b6a46", line="#1e5236", accent="#c8302f",
                      on_accent="#ffffff", muted="#a9c9b4", list="#0b2116", count="#ff8a80", tag="#ff8a80"),
    "new_year": dict(bg="#070b24", panel="#101a40", button="#18245a", border="#2f3f85", line="#223070", accent="#d4a537",
                     on_accent="#1a1400", muted="#a3aed6", list="#0c1434", count="#ffd54a", tag="#ffd54a"),
}
PALETTE = dict(PALETTES[None])
STYLE = Template("""
    QWidget { background:$bg; color:#edf3fb; font-family:'DejaVu Sans'; font-size:15px; }
    #dashboard,#ring { background:$bg; }
    QLabel#section {color:$muted;font-size:12px;font-weight:700;letter-spacing:1px;}
    QLabel#secondary {color:#b3c0d1;font-size:14px;}
    QLabel#sectionTitle {font-size:20px;font-weight:700;}
    QFrame#dashboard QLabel {background:transparent;}
    QLabel#heroClock {font-size:112px;font-weight:300;color:#ffffff;}
    QLabel#heroDate {font-size:26px;color:#f1f5fb;padding-left:6px;}
    QLabel#status {color:#fbbf24;font-size:13px;font-weight:700;background:rgba(10,16,26,150);border-radius:14px;padding:7px 14px;}
    QLabel#status[connected="true"] {color:#34d399;}
    QFrame#glass {background:rgba(10,16,26,140);border:1px solid rgba(255,255,255,38);border-radius:22px;}
    QPushButton#tile {background:rgba(255,255,255,16);border:0;border-radius:16px;padding:0;}
    QPushButton#tile:pressed {background:rgba(255,255,255,60);}
    QLabel#tileIcon {font-size:28px;color:#ffffff;}
    QLabel#tileText {font-size:12px;color:#dfe7f2;}
    QLabel#glassTitle {color:#b9c6d6;font-size:12px;font-weight:700;letter-spacing:1px;}
    QLabel#eventText {color:#f1f5fb;font-size:14px;}
    QFrame#video {background:#000;border:1px solid $line;border-radius:18px;}
    QLabel#videoView {background:#000;border-radius:18px;}
    QLabel#camNote {background:transparent;color:$muted;font-size:14px;padding:6px;}
    QFrame#side {background:transparent;}
    QFrame#side QLabel {background:transparent;}
    QLabel#bell {font-size:72px;}
    QLabel#ringTitle {font-size:28px;font-weight:700;color:#f8fafc;}
    QLabel#count {font-size:56px;font-weight:700;color:$count;}
    QPushButton#stop {background:#e85d5d;color:white;border:0;border-radius:24px;font-size:34px;font-weight:800;letter-spacing:4px;}
    QPushButton#stop:pressed {background:#c94343;}
    QPushButton#talk {background:#2fa36b;color:white;border:0;border-radius:24px;font-size:26px;font-weight:700;}
    QPushButton#talk:pressed {background:#258556;}
    QPushButton#talk[calling="true"] {background:#e8952a;}
    QPushButton {background:$button;color:#edf3fb;border:1px solid $border;border-radius:14px;font-size:17px;padding:0 18px;}
    QPushButton:pressed {background:$line;}
    QPushButton:checked {background:$accent;border-color:$accent;color:$on_accent;}
    QPushButton#nav {text-align:left;padding-left:24px;font-size:19px;}
    QLabel#pageTitle {font-size:30px;font-weight:700;}
    QLabel#camValue {font-size:22px;font-weight:600;}
    QLabel#camPreview {background:#000;border:1px solid $line;border-radius:14px;color:$muted;}
    QLabel#topicName {font-size:34px;font-weight:700;color:$count;padding:4px 0;}
    QFrame#panel {background:$panel;border:1px solid $line;border-radius:18px;}
    QFrame#panel QLabel, QFrame#panel QSlider {background:transparent;}
    QFrame#panel QScrollArea, QFrame#panel QScrollArea > QWidget > QWidget {background:transparent;}
    QListWidget#list {background:$list;border:1px solid $line;border-radius:12px;font-size:18px;}
    QListWidget#list::item {min-height:58px;padding-left:12px;}
    QListWidget#list::item:selected {background:$accent;color:$on_accent;border-radius:10px;}
    QSlider::groove:horizontal {height:10px;background:$line;border-radius:5px;}
    QSlider::handle:horizontal {background:$accent;width:36px;margin:-14px 0;border-radius:18px;}
    QDialog#keyboard {background:$bg;}
    QLineEdit#kbEdit {background:$panel;border:2px solid $accent;border-radius:12px;font-size:24px;padding:0 14px;}
    QPushButton#kbKey {font-size:22px;}
    QPushButton#kbOk {font-size:20px;background:$accent;border-color:$accent;}
    """)

def style(app, festival=None):
    PALETTE.clear(); PALETTE.update(PALETTES.get(festival, PALETTES[None]))
    app.setStyleSheet(STYLE.substitute(PALETTE))
def main():
    app=QApplication(sys.argv); style(app); w=Window()
    # Quit cleanly on SIGTERM; the timer gives Python a chance to run the handler.
    signal.signal(signal.SIGTERM, lambda *a: app.quit())
    keepalive=QTimer(); keepalive.timeout.connect(lambda: None); keepalive.start(500)
    if os.environ.get("DOORBELL_FULLSCREEN","1")=="1": w.showFullScreen()
    else:w.show()
    sys.exit(app.exec())
if __name__=="__main__":main()
