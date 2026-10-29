"""The home screen, drawn by Qt Quick on the Pi's GPU (home/*.qml): real blur, soft
shadows and smooth motion. QuickHome takes the place of a widget page in the
window's stack and keeps the old home page's interface (set_news, add_event,
open_door, ...), so the window feeds it as before.

HomeModel is what the QML sees as `home`: plain values (lists and maps), each
with its own change signal, and slots for the taps. The look (looks.py) picks
the QML layout; the breaking-news flash and festival decorations are shared.

Every minute, while the home screen shows, a still is taken from the camera for
the looks' Front door widgets (ffmpeg, one frame of the small stream)."""
import json, subprocess, threading, time
from pathlib import Path
from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot, Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap, QRadialGradient
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickWidgets import QQuickWidget
import festive_art, looks
from news import CHANNELS, is_breaking

HERE = Path(__file__).resolve().parent
STILL = Path("/dev/shm")
FLASH_MIN = 20  # a story this fresh, new since the last refresh, is flashed big
FLASH_S = 12


def pictures(folder):
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")) if folder.is_dir() else []


def file_url(path):
    return QUrl.fromLocalFile(str(path)).toString() if path else ""


def channel_color(source):
    for name, color, _, _ in CHANNELS.values():
        if source == name: return color
    return "#4285f4"


def story(i):
    """A news item as the QML uses it."""
    return {"title": i.get("title", ""), "summary": i.get("summary") or "", "source": i.get("source", ""),
            "time": i.get("time") or 0, "region": i.get("region", ""), "genre": i.get("genre", ""),
            "image": file_url(i.get("image")), "color": channel_color(i.get("source")), "breaking": is_breaking(i)}


_NAMES = {"look": "lookChanged", "view": "viewChanged", "news": "newsChanged", "newsNote": "newsChanged",
          "breaking": "breakingChanged", "market": "marketChanged", "marketNote": "marketChanged",
          "photos": "photosChanged", "festival": "festivalChanged", "greeting": "festivalChanged",
          "events": "eventsChanged", "statusOk": "statusChanged", "statusText": "statusChanged",
          "doorOnline": "doorChanged", "doorStill": "doorChanged", "doorStillTime": "doorChanged",
          "visits": "visitsChanged", "micState": "micChanged", "flash": "flashChanged"}


class HomeModel(QObject):
    lookChanged = Signal(); viewChanged = Signal(); newsChanged = Signal(); breakingChanged = Signal()
    marketChanged = Signal(); photosChanged = Signal(); festivalChanged = Signal(); eventsChanged = Signal()
    statusChanged = Signal(); doorChanged = Signal(); visitsChanged = Signal(); micChanged = Signal(); flashChanged = Signal()
    # taps
    door_tapped = Signal(); events_tapped = Signal(); settings_tapped = Signal(); view_tapped = Signal(str); listen_tapped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.v = dict(look=looks.DEFAULT, view="news", news=[], newsNote="", breaking=[], market={}, marketNote="",
                      photos=[], festival="", greeting="", events=[], statusOk=False, statusText="", doorOnline=-1,
                      doorStill="", doorStillTime=0.0, visits={}, micState="", flash={})

    def put(self, **values):
        for k, val in values.items():
            if self.v[k] != val:
                self.v[k] = val; getattr(self, _NAMES[k]).emit()

    def _p(name, kind, signal):
        return Property(kind, lambda self: self.v[name], notify=signal)
    look = _p("look", str, lookChanged); view = _p("view", str, viewChanged)
    news = _p("news", "QVariantList", newsChanged); newsNote = _p("newsNote", str, newsChanged)
    breaking = _p("breaking", "QVariantList", breakingChanged)
    market = _p("market", "QVariantMap", marketChanged); marketNote = _p("marketNote", str, marketChanged)
    photos = _p("photos", "QVariantList", photosChanged)
    festival = _p("festival", str, festivalChanged); greeting = _p("greeting", str, festivalChanged)
    events = _p("events", "QVariantList", eventsChanged)
    statusOk = _p("statusOk", bool, statusChanged); statusText = _p("statusText", str, statusChanged)
    doorOnline = _p("doorOnline", int, doorChanged); doorStill = _p("doorStill", str, doorChanged)
    doorStillTime = _p("doorStillTime", float, doorChanged)
    visits = _p("visits", "QVariantMap", visitsChanged)
    micState = _p("micState", str, micChanged)
    flash = _p("flash", "QVariantMap", flashChanged)
    del _p

    @Slot()
    def openDoor(self): self.door_tapped.emit()
    @Slot()
    def openEvents(self): self.events_tapped.emit()
    @Slot()
    def openSettings(self): self.settings_tapped.emit()
    @Slot(str)
    def setView(self, view): self.view_tapped.emit(view)
    @Slot()
    def listen(self): self.listen_tapped.emit()


class Pictures(QQuickImageProvider):
    """image://home/dot, /confetti (festival particles) and /festival/<key> (a festival's painted wallpaper)."""
    def __init__(self):
        super().__init__(QQuickImageProvider.Pixmap)

    def requestPixmap(self, id_, size, requested):
        if id_.startswith("festival/"):
            w, h = (requested.width(), requested.height()) if requested.width() > 0 else (1920, 900)
            return festive_art.paint(id_.split("/", 1)[1], w, h)
        if id_ == "confetti":
            pm = QPixmap(12, 20); pm.fill(Qt.white); return pm
        pm = QPixmap(32, 32); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
        g = QRadialGradient(QPointF(16, 16), 16); g.setColorAt(0, QColor(255, 255, 255, 255)); g.setColorAt(0.35, QColor(255, 255, 255, 200))
        g.setColorAt(1, QColor(255, 255, 255, 0)); p.setPen(Qt.NoPen); p.setBrush(g); p.drawEllipse(QRectF(0, 0, 32, 32)); p.end()
        return pm


class QuickHome(QQuickWidget):
    open_settings = Signal()
    open_door = Signal()
    open_events = Signal()
    view_changed = Signal(str)   # "news" or "photos"
    logged = Signal(list)        # the recent events' lines, newest first
    listen = Signal()            # the voice orb was tapped
    still_ready = Signal(str)

    def __init__(self, view="news", look=looks.DEFAULT, scenic=HERE / "assets" / "scenic", still_url=None):
        super().__init__()
        self.model = HomeModel(self); self.still_url = still_url  # a child: it outlives the QML when the window closes
        self.base_paths = pictures(scenic)
        try: self.credits = json.loads((scenic / "credits.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): self.credits = {}
        self.news = []; self.breaking = []; self.market = None; self.market_note = ""; self.news_note = ""
        self.festival_key = None; self.greeting = ""; self.lines = []; self.view = "photos" if view == "photos" else "news"
        self.seen = None; self.flashes = []; self.flash_at = 0.0; self.still_n = 0; self.still_busy = False
        m = self.model
        m.door_tapped.connect(self.open_door); m.events_tapped.connect(self.open_events)
        m.settings_tapped.connect(self.open_settings); m.listen_tapped.connect(self.listen)
        m.view_tapped.connect(self.set_view)
        self.still_ready.connect(lambda url: m.put(doorStill=url, doorStillTime=time.time()))
        self.engine().addImageProvider("home", Pictures())
        self.rootContext().setContextProperty("home", m)
        self.setResizeMode(QQuickWidget.SizeRootObjectToView); self.setClearColor(QColor("black"))
        self.set_look(look); m.put(view=self.view); self._photos()
        self.setSource(QUrl.fromLocalFile(str(HERE / "home" / "Home.qml")))
        for e in self.errors(): print("Home screen:", e.toString(), flush=True)
        self.ticker = QTimer(self); self.ticker.timeout.connect(self._tick); self.ticker.start(1000)
        self.still_timer = QTimer(self); self.still_timer.timeout.connect(self.grab_still); self.still_timer.start(60000)
        QTimer.singleShot(3000, self.grab_still)

    # ---------- what the window tells it ----------
    @property
    def look(self): return self.model.v["look"]
    def set_look(self, look):
        self.model.put(look=look if look in looks.LOOKS else looks.DEFAULT)
    def set_view(self, mode, notify=True):
        self.view = "photos" if mode == "photos" else "news"; self.model.put(view=self.view)
        if notify: self.view_changed.emit(self.view)
    def update_clock(self): pass  # the QML keeps its own time
    def set_status(self, ok, msg): self.model.put(statusOk=bool(ok), statusText=msg)
    def set_door(self, online): self.model.put(doorOnline=-1 if online is None else int(bool(online)))
    def set_mic(self, state): self.model.put(micState=state if state in ("listening", "thinking") else "")
    def set_visits(self, today, last, thumb):
        self.model.put(visits={"today": today, "last": last or 0, "thumb": file_url(thumb) if thumb else ""})
    def add_event(self, msg):  # not "event": that would override QWidget.event()
        self.lines = (["• " + time.strftime("%H:%M") + "  " + msg] + self.lines)[:4]
        self.model.put(events=list(self.lines)); self.logged.emit(list(self.lines))
    def set_news(self, items):
        self.news = items; self.model.put(news=[story(i) for i in items])
    def set_news_note(self, text):
        self.news_note = text; self.model.put(newsNote=text)
    def set_market(self, data):
        self.market = data; self.model.put(market=data or {})
    def set_market_note(self, note):
        self.market_note = note; self.model.put(marketNote=note)
    def set_breaking(self, items):
        """New ticker headlines; ones fresher than FLASH_MIN that were not there before are flashed big
        (on the first list after start-up only the newest, so a restart does not replay them all)."""
        fresh = [i for i in items if i.get("time") and time.time() - i["time"] < FLASH_MIN * 60]
        new = [i for i in fresh if i["title"] not in self.seen] if self.seen is not None else fresh[:1]
        self.seen = {i["title"] for i in items} | (self.seen or set())
        self.flashes += sorted(new, key=lambda i: i["time"])
        self.breaking = items; self.model.put(breaking=[story(i) for i in items])
    def set_festival(self, key, text=""):
        self.festival_key, self.greeting = key, text
        self.model.put(festival=key or "", greeting=text or ""); self._photos()

    # ---------- inside ----------
    def _photos(self):
        """The slideshow: a festival's own pictures (or its painted wallpaper) while it lasts."""
        if self.festival_key:
            own = pictures(HERE / "assets" / "festivals" / self.festival_key)
            photos = [{"url": file_url(p), "credit": ""} for p in own] or [{"url": f"image://home/festival/{self.festival_key}", "credit": ""}]
        else:
            photos = [{"url": file_url(p), "credit": self.credits.get(p.name, "")} for p in self.base_paths]
        self.model.put(photos=photos)

    def _tick(self):
        """The breaking-news flash: one at a time, FLASH_S seconds each, over the news view."""
        now = time.monotonic()
        if self.model.v["flash"] and now - self.flash_at > FLASH_S: self.model.put(flash={})
        if not self.model.v["flash"] and self.flashes and self.view == "news" and self.isVisible():
            self.model.put(flash=story(self.flashes.pop(0))); self.flash_at = now

    def grab_still(self):
        """One frame from the camera for the Front door widgets, while the home screen shows."""
        url = self.still_url() if self.still_url else ""
        if not url or self.still_busy or not self.isVisible(): return
        self.still_busy = True; self.still_n += 1; out = STILL / f"doorbell_still_{self.still_n % 2}.jpg"
        def run():
            try:
                r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-rtsp_transport", "tcp", "-i", url,
                                    "-frames:v", "1", "-vf", "scale=800:-2", "-q:v", "4", str(out)], capture_output=True, timeout=20)
                if r.returncode == 0 and out.exists(): self.still_ready.emit(file_url(out))
            except (OSError, subprocess.TimeoutExpired): pass
            finally: self.still_busy = False
        threading.Thread(target=run, daemon=True).start()
