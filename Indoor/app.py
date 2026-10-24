import json, os, signal, sys, threading, time
from pathlib import Path
# RTSP over TCP is far more reliable than UDP on Wi-Fi; the 5 s timeout keeps a
# dead camera from blocking the capture thread. Must be set before cv2 loads.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;5000000")
# SDL (pygame) otherwise swallows SIGTERM, so `kill` / systemd could not stop the app.
os.environ.setdefault("SDL_NO_SIGNAL_HANDLERS", "1")
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread, QVariantAnimation, QEasingCurve, QRectF, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QLinearGradient
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

from bluetooth import Bluetooth
from news import News, ago
from settings_ui import SettingsPage

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
    def publish(self, topic, payload):
        if not (self.client and self.connected): return False
        self.client.publish(topic, json.dumps(payload), qos=1, retain=False); return True
    def close(self):
        if self.client:
            self.client.loop_stop(); self.client.disconnect()

class Audio:
    """Plays the chosen bell tone. The mixer is reopened for every sound so it
    always uses the current output, e.g. a speaker connected after start-up."""
    def tone(self):
        path = TONES / SETTINGS.get("tone", "ding_dong.wav")
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
        self.paths = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        try: self.credits = json.loads((folder / "credits.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): self.credits = {}
        self.idx = 0; self.pos = 0.0; self.cache = {}
        self.mode = "photos"; self.news = []; self.news_idx = 0; self.news_note = "Loading news…"
        self.intervals = {"photos": int(photo_s * 1000), "news": int(news_s * 1000)}
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1100, easingCurve=QEasingCurve.InOutCubic)
        self.anim.valueChanged.connect(self._step); self.anim.finished.connect(self._done)
        self.timer = QTimer(self); self.timer.timeout.connect(self.next)
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
            pm = QPixmap(str(self.paths[i])).scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
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
        for i in range(n):
            p.setBrush(QColor(255, 255, 255, 240 if i == active else 110)); rad = 5 if i == active else 3.5
            p.drawEllipse(QPointF(w / 2 + (i - (n - 1) / 2) * 18, h - 26), rad, rad)
        name = self.credits.get(self.paths[self.idx].name) if not shift else None
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
            p.setFont(self._font(15, True)); p.setPen(QColor("#7cc4ff"))
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

class Dashboard(QFrame):
    """Full-screen wallpaper with the clock, a slim shortcut rail and recent
    events floating on top of it in translucent panels."""
    open_settings = Signal()
    view_changed = Signal(str)  # "news" or "photos"
    def __init__(self, view="news"):
        super().__init__(); self.setObjectName("dashboard")
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0)
        sc=CFG.get("scenic",{})
        self.scenic=Scenic(ROOT/sc.get("folder","assets/scenic"), sc.get("interval_seconds",15),
                           CFG.get("news",{}).get("interval_seconds",12)); root.addWidget(self.scenic)

        over = QHBoxLayout(self.scenic); over.setContentsMargins(28,28,28,52); over.setSpacing(28)
        rail = QFrame(); rail.setObjectName("glass"); rl = QVBoxLayout(rail); rl.setContentsMargins(10,10,10,10); rl.setSpacing(10)
        rl.addWidget(tile("⌂","Front door"))
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
    def __init__(self):
        super().__init__(); self.setObjectName("ring")
        root=QHBoxLayout(self); root.setContentsMargins(24,24,24,24); root.setSpacing(24)

        video=QFrame(); video.setObjectName("video"); vl=QVBoxLayout(video); vl.setContentsMargins(0,0,0,0)
        self.view=label("","videoView"); self.view.setAlignment(Qt.AlignCenter)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)  # never resized by the frames it shows
        vl.addWidget(self.view)
        self.cam_note=label("", "camNote"); self.cam_note.setAlignment(Qt.AlignCenter); vl.addWidget(self.cam_note)
        root.addWidget(video,3)

        side=QVBoxLayout(); side.setSpacing(10)
        side.addWidget(label("FRONT DOOR · VISITOR ALERT","section"))
        side.addStretch()
        bell=label("🔔","bell"); bell.setAlignment(Qt.AlignCenter); side.addWidget(bell)
        title=label("Someone is at the door","ringTitle"); title.setAlignment(Qt.AlignCenter); title.setWordWrap(True); side.addWidget(title)
        self.subtitle=label("Bell is playing","secondary"); self.subtitle.setAlignment(Qt.AlignCenter); side.addWidget(self.subtitle)
        self.count=label("00:30","count"); self.count.setAlignment(Qt.AlignCenter); side.addWidget(self.count)
        side.addStretch()
        b=QPushButton("STOP"); b.setObjectName("stop"); b.setMinimumHeight(140); b.clicked.connect(self.stop.emit); side.addWidget(b)
        panel=QFrame(); panel.setObjectName("side"); panel.setLayout(side); panel.setFixedWidth(330)
        root.addWidget(panel)
        self.last=None
    def show_frame(self, img):
        self.last=img
        self.view.setPixmap(QPixmap.fromImage(img).scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    def clear_video(self, note):
        self.last=None; self.view.clear(); self.cam_note.setText(note)
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.last is not None: self.show_frame(self.last)

class Window(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Indoor Doorbell Dashboard"); self.setMinimumSize(800,450)
        self.active=False; self.until=0; self.event_id=None; self.camera=None
        self.audio=Audio(); self.bt=Bluetooth()
        self.stack=QStackedWidget(); self.home=Dashboard(SETTINGS.get("home_view","news")); self.ring=RingPage()
        self.home.view_changed.connect(lambda v: (SETTINGS.__setitem__("home_view", v), save_settings()))
        self.news=News(SETTINGS, ROOT/"news_cache.json")
        self.news.updated.connect(self.home.scenic.set_news)
        self.news.failed.connect(lambda why: self.home.scenic.set_news_note(f"News unavailable ({why}). Retrying every minute."))
        self.news.start()
        self.settings=SettingsPage(self.bt, TONES, SETTINGS, save_settings, self.preview, self.send_outdoor, self.news.refresh)
        self.settings.speaker.test_cb=lambda: self.preview(self.audio.tone())
        for page in (self.home, self.ring, self.settings): self.stack.addWidget(page)
        self.home.open_settings.connect(lambda: self.stack.setCurrentWidget(self.settings))
        self.settings.back.connect(lambda: (self.audio.stop(), self.stack.setCurrentWidget(self.home)))
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.addWidget(self.stack)
        self.ring.stop.connect(lambda: self.stop_ring("TOUCH"))
        if SETTINGS.get("speaker"): self.bt.request("reconnect", SETTINGS["speaker"]["mac"])
        self.sig=Signals(); self.sig.message.connect(self.handle); self.sig.status.connect(self.home.set_status)
        self.mqtt=MQTT(self.sig); self.mqtt.start()
        self.clock_timer=QTimer(self); self.clock_timer.timeout.connect(self.home.update_clock); self.clock_timer.start(1000); self.home.update_clock()
        self.tick=QTimer(self); self.tick.timeout.connect(self.countdown); self.tick.start(200)
        self.demo=QTimer(self)
        if CFG.get("demo_mode",False): self.demo.timeout.connect(self.demo_ring); self.demo.start(18000)
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
    def start_camera(self):
        if self.camera: return
        url=CFG.get("camera",{}).get("rtsp_url","")
        if not url: self.ring.clear_video("Camera not configured · set camera.rtsp_url in config.json"); return
        if cv2 is None: self.ring.clear_video("OpenCV missing · sudo apt install python3-opencv"); return
        self.ring.clear_video("Connecting to camera…")
        self.camera=Camera(url); self.camera.frame.connect(self.on_frame); self.camera.state.connect(self.ring.cam_note.setText); self.camera.start()
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
        self.ring.count.setText(self.fmt(seconds)); self.ring.subtitle.setText(f"Bell is playing · {source}")
        self.stack.setCurrentWidget(self.ring); self.start_camera(); self.audio.play()
        self.active=True; self.home.add_event(f"Doorbell started ({seconds}s)")
        self.mqtt.publish(CFG["mqtt"]["topic_status"],{"state":"ringing","remaining_seconds":seconds,"event_id":event_id})
        self.demo.stop()
    def countdown(self):
        if not self.active:return
        remaining=max(0,int(self.until-time.monotonic()+0.999)); self.ring.count.setText(self.fmt(remaining))
        if remaining<=0:self.stop_ring("TIMER")
    def stop_ring(self,source="TOUCH"):
        if not self.active:
            self.stack.setCurrentWidget(self.home); return
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
        self.audio.stop(); self.stop_camera(); self.mqtt.close(); self.bt.request("quit"); self.news.stop(); event.accept()

def style(app):
    app.setStyleSheet("""
    QWidget { background:#0b111b; color:#edf3fb; font-family:'DejaVu Sans'; font-size:15px; }
    #dashboard,#ring { background:#0b111b; }
    QLabel#section {color:#8ea1b8;font-size:12px;font-weight:700;letter-spacing:1px;}
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
    QFrame#video {background:#000;border:1px solid #24364a;border-radius:18px;}
    QLabel#videoView {background:#000;border-radius:18px;}
    QLabel#camNote {background:transparent;color:#8ea1b8;font-size:14px;padding:6px;}
    QFrame#side {background:transparent;}
    QFrame#side QLabel {background:transparent;}
    QLabel#bell {font-size:72px;}
    QLabel#ringTitle {font-size:28px;font-weight:700;color:#f8fafc;}
    QLabel#count {font-size:56px;font-weight:700;color:#93c5fd;}
    QPushButton#stop {background:#e85d5d;color:white;border:0;border-radius:24px;font-size:34px;font-weight:800;letter-spacing:4px;}
    QPushButton#stop:pressed {background:#c94343;}
    QPushButton {background:#1b2a3d;color:#edf3fb;border:1px solid #2c4058;border-radius:14px;font-size:17px;padding:0 18px;}
    QPushButton:pressed {background:#24364a;}
    QPushButton:checked {background:#2f80ed;border-color:#2f80ed;color:white;}
    QPushButton#nav {text-align:left;padding-left:24px;font-size:19px;}
    QLabel#pageTitle {font-size:30px;font-weight:700;}
    QFrame#panel {background:#141f2d;border:1px solid #24364a;border-radius:18px;}
    QFrame#panel QLabel, QFrame#panel QSlider {background:transparent;}
    QFrame#panel QScrollArea, QFrame#panel QScrollArea > QWidget > QWidget {background:transparent;}
    QListWidget#list {background:#0f1824;border:1px solid #24364a;border-radius:12px;font-size:18px;}
    QListWidget#list::item {min-height:58px;padding-left:12px;}
    QListWidget#list::item:selected {background:#2f80ed;color:white;border-radius:10px;}
    QSlider::groove:horizontal {height:10px;background:#24364a;border-radius:5px;}
    QSlider::handle:horizontal {background:#2f80ed;width:36px;margin:-14px 0;border-radius:18px;}
    QDialog#keyboard {background:#0b111b;}
    QLineEdit#kbEdit {background:#141f2d;border:2px solid #2f80ed;border-radius:12px;font-size:24px;padding:0 14px;}
    QPushButton#kbKey {font-size:22px;}
    QPushButton#kbOk {font-size:20px;background:#2f80ed;border-color:#2f80ed;}
    """)
def main():
    app=QApplication(sys.argv); style(app); w=Window()
    # Quit cleanly on SIGTERM; the timer gives Python a chance to run the handler.
    signal.signal(signal.SIGTERM, lambda *a: app.quit())
    keepalive=QTimer(); keepalive.timeout.connect(lambda: None); keepalive.start(500)
    if os.environ.get("DOORBELL_FULLSCREEN","1")=="1": w.showFullScreen()
    else:w.show()
    sys.exit(app.exec())
if __name__=="__main__":main()
