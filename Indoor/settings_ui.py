"""Settings screen of the indoor unit: Bluetooth speaker, bell tone, and the
outdoor unit's settings (applied over MQTT, see topics.md)."""
import json, time
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from festivals import FESTIVALS, upcoming
from news import CHANNELS, DEFAULT_CHANNELS, GENRES, REGIONS
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QScroller, QSizePolicy, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget, QButtonGroup)

# Must match the outdoor firmware's tables (Outdoor/src/doorbell_ui.c).
OUTDOOR_THEMES = ["Clean & Light", "Midnight & Gold"]
OUTDOOR_BELLS = [("Blue", "#2F80ED"), ("Gold", "#D4A537"), ("Silver", "#A7B1BC"), ("Red", "#D64545")]
OUTDOOR_DURATIONS = [10, 15, 30, 45, 60]
# bell_style numbers 0..5; pictures in assets/bells/<number>_*.png
OUTDOOR_STYLES = ["Classic", "Push button", "Temple", "Hand bell", "Twin bells", "Flat"]
BELL_ICONS = Path(__file__).resolve().parent / "assets" / "bells"
OUTDOOR_CHIMES = ["Ding Dong", "Westminster", "Triple Chime", "Marimba", "Church Bell"]  # chime numbers 0..4
OUTDOOR_VOLUMES = [("Quiet", 40), ("Normal", 70), ("Loud", 100)]

def label(text, obj=None, wrap=False):
    w = QLabel(text); w.setWordWrap(wrap)
    if obj: w.setObjectName(obj)
    return w

def button(text, obj=None, checkable=False, h=56):
    b = QPushButton(text.replace("&", "&&")); b.setMinimumHeight(h); b.setCheckable(checkable)  # "&" would mark a shortcut
    if obj: b.setObjectName(obj)
    return b

def dot_icon(color, size=22):
    pm = QPixmap(size, size); pm.fill(Qt.transparent); p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing); p.setBrush(QColor(color)); p.setPen(QColor("#ffffff")); p.drawEllipse(1, 1, size - 2, size - 2); p.end()
    return QIcon(pm)

def this_ip():
    """This Pi's LAN address (the route to a public address; nothing is sent)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    except OSError: return ""
    finally: s.close()

def touch_scroll(w):
    QScroller.grabGesture(w.viewport() if hasattr(w, "viewport") else w, QScroller.LeftMouseButtonGesture)

class Keyboard(QDialog):
    """Full-screen on-screen keyboard for the touch display."""
    ROWS = {False: ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"],
            True: ["!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?\\|", "`~"]}
    def __init__(self, parent, title, text="", password=False):
        super().__init__(parent, Qt.FramelessWindowHint); self.setObjectName("keyboard"); self.setModal(True)
        self.shift = False; self.symbols = False
        root = QVBoxLayout(self); root.setContentsMargins(40, 30, 40, 30); root.setSpacing(12)
        root.addWidget(label(title, "sectionTitle"))
        row = QHBoxLayout(); self.edit = QLineEdit(text); self.edit.setObjectName("kbEdit"); self.edit.setMinimumHeight(60)
        if password: self.edit.setEchoMode(QLineEdit.Password)
        row.addWidget(self.edit, 1)
        if password:
            eye = button("Show", "kbKey", True, 60); eye.setFixedWidth(110)
            eye.toggled.connect(lambda on: (self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password), eye.setText("Hide" if on else "Show")))
            row.addWidget(eye)
        root.addLayout(row)
        self.grid = QGridLayout(); self.grid.setSpacing(8); root.addLayout(self.grid, 1)
        bottom = QHBoxLayout(); bottom.setSpacing(8)
        for text, fn, stretch in [("⇧", self.toggle_shift, 1), ("#+=", self.toggle_symbols, 1), ("Space", lambda: self.type(" "), 4),
                                  ("⌫", self.edit.backspace, 1), ("Cancel", self.reject, 2), ("OK", self.accept, 2)]:
            b = button(text, "kbOk" if text == "OK" else "kbKey", h=70); b.clicked.connect(fn); bottom.addWidget(b, stretch)
        root.addLayout(bottom)
        self.build()
    def build(self):
        while self.grid.count(): self.grid.takeAt(0).widget().deleteLater()
        for r, keys in enumerate(self.ROWS[self.symbols]):
            for c, k in enumerate(keys):
                k = k.upper() if self.shift and not self.symbols else k
                b = button(k, "kbKey", h=70); b.clicked.connect(lambda _=False, k=k: self.type(k))
                b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # keys fill the screen
                self.grid.addWidget(b, r, c + (r if not self.symbols and r > 1 else 0) // 2)
    def type(self, k):
        self.edit.insert(k)
        if self.shift: self.shift = False; self.build()
    def toggle_shift(self): self.shift = not self.shift; self.build()
    def toggle_symbols(self): self.symbols = not self.symbols; self.build()
    def showEvent(self, e):
        self.setGeometry(self.parent().geometry()); super().showEvent(e); self.edit.setFocus()
    @staticmethod
    def ask(parent, title, text="", password=False):
        k = Keyboard(parent.window(), title, text, password)  # top level: not styled as part of a panel
        return k.edit.text() if k.exec() == QDialog.Accepted else None

class SpeakerPanel(QWidget):
    def __init__(self, bt, settings, save):
        super().__init__(); self.bt = bt; self.settings = settings; self.save = save; self.items = []
        lay = QVBoxLayout(self); lay.setSpacing(14)
        lay.addWidget(label("Bluetooth speaker", "sectionTitle"))
        self.output = label("Sound plays on: …", "secondary"); lay.addWidget(self.output)
        vol = QHBoxLayout(); vol.addWidget(label("Volume", "secondary"))
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, 100); self.slider.setMinimumHeight(48)
        self.slider.sliderReleased.connect(lambda: self.bt.request("volume", value=self.slider.value()))
        self.vol_text = label("", "secondary"); self.slider.valueChanged.connect(lambda v: self.vol_text.setText(f"{v}%"))
        vol.addWidget(self.slider, 1); vol.addWidget(self.vol_text); lay.addLayout(vol)
        actions = QHBoxLayout()
        self.scan_btn = button("Search for speakers"); self.scan_btn.clicked.connect(lambda: self.bt.request("scan"))
        test = button("Play test sound"); test.clicked.connect(self.test)
        actions.addWidget(self.scan_btn); actions.addWidget(test); lay.addLayout(actions)
        self.list = QListWidget(); self.list.setObjectName("list"); touch_scroll(self.list); lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, job in [("Connect", "connect"), ("Disconnect", "disconnect"), ("Forget", "forget")]:
            b = button(text); b.clicked.connect(lambda _=False, job=job: self.act(job)); row.addWidget(b)
        lay.addLayout(row)
        self.msg = label("Put the speaker in pairing mode, then search. Choose it in the list and press Connect.", "secondary", True)
        lay.addWidget(self.msg)
        # Two-way talk is still being tried out: off unless chosen here. While a call
        # lasts, the speaker runs in its hands-free mode, so the bell tone stops.
        lay.addWidget(label("TWO-WAY TALK WITH THE DOOR (TRIAL)", "section")); row = QHBoxLayout(); group = QButtonGroup(self); self.talk_btns = {}
        for value, text in ((False, "Off"), (True, "On: Talk button on the door screens")):
            b = button(text, "choice", True, 56); b.setChecked(settings.get("intercom", False) == value); group.addButton(b); row.addWidget(b)
            self.talk_btns[value] = b
            b.clicked.connect(lambda _=False, value=value: (self.settings.__setitem__("intercom", value), self.save()))
        lay.addLayout(row)
        bt.devices.connect(self.show_devices); bt.status.connect(self.msg.setText); bt.output.connect(self.show_output)
        self.test_cb = None
    def sync(self):
        self.talk_btns[bool(self.settings.get("intercom", False))].setChecked(True)
    def show_devices(self, devs):
        self.items = devs; self.list.clear()
        for d in devs:
            state = "connected" if d["connected"] else "paired" if d["paired"] else "found"
            QListWidgetItem(f"{d['name']}    ·  {state}", self.list)
        if not devs: QListWidgetItem("No speakers found yet", self.list)
    def show_output(self, name, vol):
        self.output.setText(f"Sound plays on: {name}")
        if not self.slider.isSliderDown(): self.slider.setValue(vol)
    def act(self, job):
        i = self.list.currentRow()
        if not (0 <= i < len(self.items)): self.msg.setText("Choose a speaker in the list first"); return
        d = self.items[i]; self.bt.request(job, d["mac"])
        if job == "connect": self.settings["speaker"] = {"mac": d["mac"], "name": d["name"]}; self.save()
        if job == "forget" and self.settings.get("speaker", {}).get("mac") == d["mac"]: self.settings.pop("speaker"); self.save()
    def test(self):
        if self.test_cb: self.test_cb()
    def showEvent(self, e):
        self.bt.request("list"); super().showEvent(e)

AUDIO_TYPES = (".wav", ".mp3", ".ogg")
TONE_CATEGORIES = ["Chimes", "Bollywood style", "Festive", "Funny", "My tones"]

def list_tones(folder):
    """[(category, display name, path relative to folder)]: generated tones from
    tones.json, plus any audio file the user drops into the folder or its `mine/`."""
    try: catalogue = json.loads((folder / "tones.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): catalogue = {}
    found = []
    for path in sorted([*folder.glob("*"), *(folder / "mine").glob("*")]):
        if path.suffix.lower() not in AUDIO_TYPES: continue
        rel = path.relative_to(folder).as_posix(); meta = catalogue.get(rel, {})
        found.append((meta.get("category", "My tones"), meta.get("name", path.stem.replace("_", " ").title()), rel))
    order = {c: i for i, c in enumerate(TONE_CATEGORIES)}
    return sorted(found, key=lambda t: (order.get(t[0], len(order)), list(catalogue).index(t[2]) if t[2] in catalogue else 0, t[1]))

class TonePanel(QWidget):
    def __init__(self, folder, settings, save, preview):
        super().__init__(); self.settings = settings; self.save = save
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(8)
        outer.addWidget(label("Bell tone", "sectionTitle"))
        outer.addWidget(label("Played on the speaker for the whole ring, until it times out or STOP is pressed. "
                              "Your own .wav / .mp3 / .ogg files in assets/tones/mine/ appear under My tones.", "secondary", True))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); touch_scroll(scroll)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(); lay = QVBoxLayout(body); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        scroll.setWidget(body); outer.addWidget(scroll, 1)
        group = QButtonGroup(self); group.setExclusive(True); self.tone_btns = {}
        current = settings.get("tone", "ding_dong.wav"); grid = None; category = None; n = 0
        for cat, name, rel in list_tones(folder):
            if cat != category:  # new section: heading and a fresh two-column grid
                category = cat; lay.addWidget(label(cat.upper(), "section"))
                grid = QGridLayout(); grid.setSpacing(10); lay.addLayout(grid); n = 0
            cell = QHBoxLayout(); cell.setSpacing(6)
            pick = button(name, "choice", True, 60); pick.setChecked(rel == current); group.addButton(pick); self.tone_btns[rel] = pick
            pick.clicked.connect(lambda _=False, r=rel: self.choose(r))
            play = button("▶", h=60); play.setFixedWidth(64); play.clicked.connect(lambda _=False, p=folder / rel: preview(p))
            cell.addWidget(pick, 1); cell.addWidget(play); grid.addLayout(cell, n // 2, n % 2); n += 1
        lay.addStretch()
    def choose(self, name):
        self.settings["tone"] = name; self.save()
    def sync(self):
        b = self.tone_btns.get(self.settings.get("tone", "ding_dong.wav"))
        if b: b.setChecked(True)

class NewsPanel(QWidget):
    """Region (one) and genres (any number) of the headlines on the main page."""
    def __init__(self, settings, save, changed):
        super().__init__(); self.settings = settings; self.save = save; self.changed = changed
        lay = QVBoxLayout(self); lay.setSpacing(12)
        lay.addWidget(label("News", "sectionTitle"))
        lay.addWidget(label("The main page's news (the Photos / News tile there switches to it): the channels' top "
                            "stories with photos, and their newest headlines in the ticker below, marked BREAKING "
                            "when under 90 minutes old. From the channels' public feeds, every 10 minutes.", "secondary", True))
        lay.addWidget(label("CHANNELS (choose any; their stories are mixed)", "section")); grid = QGridLayout(); grid.setSpacing(10)
        on = set(settings.get("news_channels", DEFAULT_CHANNELS)); self.channel_btns = {}
        for i, (key, (name, _, _, _)) in enumerate(CHANNELS.items()):
            b = button(name, "choice", True, 64); b.setChecked(key in on); grid.addWidget(b, i // 3, i % 3)
            b.toggled.connect(lambda _=False: self.set_channels()); self.channel_btns[key] = b
        lay.addLayout(grid)
        lay.addWidget(label("GOOGLE NEWS: REGIONS (when Google News is chosen above)", "section")); row = QHBoxLayout()
        current = set(settings.get("news_regions") or [settings.get("news_region", "india")]); self.region_btns = {}
        for key, (text, _, _) in REGIONS.items():
            b = button(text, "choice", True, 64); b.setChecked(key in current); row.addWidget(b)
            b.toggled.connect(lambda _=False: self.set_regions()); self.region_btns[key] = b
        lay.addLayout(row)
        lay.addWidget(label("GOOGLE NEWS: TOPICS", "section")); grid = QGridLayout(); grid.setSpacing(10)
        chosen = set(settings.get("news_genres", ["top"])); self.genre_btns = {}
        for i, (key, (text, _)) in enumerate(GENRES.items()):
            b = button(text, "choice", True, 64); b.setChecked(key in chosen); grid.addWidget(b, i // 3, i % 3)
            b.toggled.connect(lambda _=False: self.set_genres()); self.genre_btns[key] = b
        lay.addLayout(grid)
        self.msg = label("", "secondary", True); lay.addWidget(self.msg); lay.addStretch()
    def sync(self):
        """Shows the settings as they are now (changed from a browser), without saving again."""
        for btns, chosen in ((self.channel_btns, self.settings.get("news_channels", DEFAULT_CHANNELS)),
                             (self.region_btns, self.settings.get("news_regions") or ["india"]),
                             (self.genre_btns, self.settings.get("news_genres", ["top"]))):
            for key, b in btns.items():
                b.blockSignals(True); b.setChecked(key in chosen); b.blockSignals(False)
    def set_channels(self):
        keys = [k for k, b in self.channel_btns.items() if b.isChecked()]
        self.settings["news_channels"] = keys or DEFAULT_CHANNELS; self.save(); self.changed()
        self.msg.setText("Updating the news…" if keys else "No channel chosen: showing NDTV, Times of India and BBC")
    def set_regions(self):
        keys = [k for k, b in self.region_btns.items() if b.isChecked()]
        self.settings["news_regions"] = keys or ["india"]; self.settings.pop("news_region", None); self.save(); self.changed()
        self.msg.setText("Updating headlines…" if keys else "No region chosen: showing India")
    def set_genres(self):
        keys = [k for k, b in self.genre_btns.items() if b.isChecked()]
        self.settings["news_genres"] = keys or ["top"]; self.save(); self.changed()
        self.msg.setText("Updating headlines…" if keys else "No genre chosen: showing top stories")

class CameraPanel(QWidget):
    """VIGI camera: address, login and stream, with a test that shows a snapshot."""
    tested = Signal(bool, object)  # ok, BGR frame or the reason it failed
    found = Signal(list)

    def __init__(self, settings, save):
        super().__init__()
        import camera_cfg
        self.cfg = camera_cfg; self.cam = camera_cfg.load(); self.settings = settings; self.save_settings = save
        lay = QVBoxLayout(self); lay.setSpacing(10)
        lay.addWidget(label("Camera", "sectionTitle"))
        lay.addWidget(label("The front-door camera shown when someone rings. The login is kept only on this Pi "
                            "(secrets.json, readable by nobody else) and never leaves it.", "secondary", True))
        body = QHBoxLayout(); body.setSpacing(20); left = QVBoxLayout(); left.setSpacing(10)
        self.values = {}
        for key, title, secret in (("ip", "IP ADDRESS", False), ("user", "USERNAME", False),
                                   ("password", "PASSWORD", True), ("main", "STREAM (VIGI: stream1)", False)):
            left.addWidget(label(title, "section")); row = QHBoxLayout()
            v = label("", "camValue"); row.addWidget(v, 1); self.values[key] = v
            b = button("Change", h=56); b.setFixedWidth(150); b.clicked.connect(lambda _=False, k=key, s=secret, t=title: self.edit(k, t, s))
            row.addWidget(b)
            if key == "ip":
                f = button("Find", h=56); f.setFixedWidth(110); f.clicked.connect(self.find); row.addWidget(f)
            left.addLayout(row)
        self.found_row = QHBoxLayout(); left.addLayout(self.found_row)
        left.addWidget(label("RECORDING AFTER THE PRESS: PICTURE AND SOUND", "section")); row = QHBoxLayout()
        for d in (-5, -1, 0, 1, 5):  # 0: the length itself
            if d == 0:
                self.len_value = label("", "camValue"); self.len_value.setAlignment(Qt.AlignCenter); row.addWidget(self.len_value, 1); continue
            b = button(("−" if d < 0 else "+") + ("5" if abs(d) == 5 else ""), h=52); b.setFixedWidth(90)
            b.clicked.connect(lambda _=False, d=d: self.step_length(d)); row.addWidget(b)
        left.addLayout(row); self.show_length()
        left.addWidget(label("SOUND IN RECORDINGS (the doorbell's microphone)", "section")); row = QHBoxLayout(); group = QButtonGroup(self); self.audio_btns = {}
        for value, text in ((True, "On"), (False, "Off: picture only")):
            b = button(text, "choice", True, 52); b.setChecked(settings.get("record_audio", True) == value); group.addButton(b); row.addWidget(b)
            b.clicked.connect(lambda _=False, v=value: self.set_audio(v)); self.audio_btns[value] = b
        left.addLayout(row)
        left.addWidget(label("MOTION RECORDING (people, animals, vehicles that move: 5 s before to 55 s after)", "section"))
        row = QHBoxLayout(); group = QButtonGroup(self); self.motion_btns = {}
        for value, text in ((True, "On"), (False, "Off")):
            b = button(text, "choice", True, 52); b.setChecked(settings.get("motion_record", True) == value); group.addButton(b); row.addWidget(b)
            b.clicked.connect(lambda _=False, v=value: self.set_motion(v)); self.motion_btns[value] = b
        left.addLayout(row)
        row = QHBoxLayout()
        t = button("Test connection", h=64); t.clicked.connect(self.test); row.addWidget(t)
        s = button("Save", "choice", h=64); s.clicked.connect(self.save); row.addWidget(s)
        left.addLayout(row)
        self.msg = label("", "secondary", True); left.addWidget(self.msg); left.addStretch()
        body.addLayout(left, 3)
        self.preview = QLabel("Snapshot appears here after a test"); self.preview.setObjectName("camPreview")
        self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumSize(480, 270)
        body.addWidget(self.preview, 4, Qt.AlignTop); lay.addLayout(body, 1)
        self.tested.connect(self.on_tested); self.found.connect(self.on_found)
        self.show_values()

    def show_values(self):
        c = self.cam
        self.values["ip"].setText(c["ip"] or "not set"); self.values["user"].setText(c["user"] or "none")
        self.values["password"].setText("•" * 8 if c["password"] else "not set"); self.values["main"].setText(c["main"])

    def edit(self, key, title, secret):
        text = Keyboard.ask(self, title.split(" (")[0].capitalize(), "" if secret else str(self.cam[key]), password=secret)
        if text is None: return
        self.cam[key] = text.strip() if key != "password" else text
        self.show_values(); self.msg.setText("Not saved yet: test it, then Save")

    def find(self):
        self.msg.setText("Looking for cameras on the network…")
        import threading
        threading.Thread(target=lambda: self.found.emit(self.cfg.find_cameras()), daemon=True).start()

    def on_found(self, cams, quiet=False):
        """cams: [(ip, description)]; one camera is chosen straight away."""
        while self.found_row.count():
            w = self.found_row.takeAt(0).widget()
            if w: w.deleteLater()
        if quiet: return
        if not cams: self.msg.setText("No camera found (is it powered and on this network?)"); return
        if len(cams) == 1:
            self.pick(*cams[0]); return
        self.msg.setText("Cameras found: tap yours")
        for ip, desc in cams[:4]:
            b = button(f"{desc}\n{ip}", "choice", h=64); b.clicked.connect(lambda _=False, ip=ip, d=desc: self.pick(ip, d))
            self.found_row.addWidget(b)

    def pick(self, ip, desc=""):
        self.cam["ip"] = ip; self.show_values(); self.on_found([], quiet=True)
        self.msg.setText(f"Found {desc + ' at ' if desc else ''}{ip}. Enter its password, test it, then Save")

    def test(self):
        self.msg.setText("Connecting to the camera…"); self.preview.setText("…")
        import threading
        try: import cv2
        except ImportError: cv2 = None
        cam = dict(self.cam)
        threading.Thread(target=lambda: self.tested.emit(*self.cfg.test(cam, cv2)), daemon=True).start()

    def on_tested(self, ok, result):
        if not ok:
            self.msg.setText("✗ " + result); self.preview.setText("No picture"); return
        h, w = result.shape[:2]
        rgb = result[:, :, ::-1].copy()
        from PySide6.QtGui import QImage
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.msg.setText(f"✓ Camera works: {w}×{h}. Press Save to use it.")

    on_saved = None  # set by the window: restarts the recording buffer

    def save(self):
        self.cfg.save(self.cam); self.msg.setText("✓ Saved. The ring screen uses it from the next ring.")
        if self.on_saved: self.on_saved()

    def sync(self):
        self.show_length()
        self.audio_btns[bool(self.settings.get("record_audio", True))].setChecked(True)
        self.motion_btns[bool(self.settings.get("motion_record", True))].setChecked(True)
    on_audio = None  # set by the window: the recording buffer starts again with or without sound
    def set_motion(self, on):
        self.settings["motion_record"] = on; self.save_settings()
        self.msg.setText("✓ Movements are recorded" if on else "✓ Only bell presses are recorded from now on")
    def set_audio(self, on):
        self.settings["record_audio"] = on; self.save_settings()
        if self.on_audio: self.on_audio()
        self.msg.setText("✓ Recordings get the doorbell's sound" if on else "✓ Recordings are picture only from now on")
    ring_seconds = None  # set by the settings page: the doorbell's ring length, the longest recording
    def length(self):
        """(seconds recorded after a press, the most allowed)"""
        from recorder import CLIP_S, RING_S
        top = max(1, int((self.ring_seconds() if self.ring_seconds else 0) or RING_S))
        return min(self.settings.get("record_seconds", CLIP_S), top), top
    def show_length(self):
        from recorder import PRE_S
        secs, top = self.length()
        self.len_value.setText(f"{secs} s   (1 – {top} s, the ring's length; plus {PRE_S} s before the press)")
    def step_length(self, d):
        secs, top = self.length(); secs = max(1, min(top, secs + d))
        self.settings["record_seconds"] = secs; self.save_settings(); self.show_length()
        self.msg.setText(f"✓ Each ring is recorded for {secs} s after the press")

def web_addresses():
    """http addresses of this Pi's web page: home network first, then Tailscale (if any)."""
    import subprocess
    out = []
    ip = this_ip()
    if ip:
        # name the network: a phone on another Wi-Fi of the same router (other subnet) cannot reach this address
        try:
            ssid = next((l.split(":", 1)[1] for l in subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                         capture_output=True, text=True, timeout=3).stdout.splitlines() if l.startswith("yes:")), "")
        except (OSError, subprocess.TimeoutExpired): ssid = ""
        out.append((f"On the Wi-Fi “{ssid}” only" if ssid else "Home network", f"http://{ip}:8080"))
    try:
        ts = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3).stdout.split()
        if ts: out.append(("Anywhere, with Tailscale", f"http://{ts[0]}:8080"))
    except (OSError, subprocess.TimeoutExpired): pass
    return out


def qr_pixmap(text, size=220):
    """A QR code of `text` (needs the qrcode package), or None."""
    try: import qrcode
    except ImportError: return None
    qr = qrcode.QRCode(border=2); qr.add_data(text); qr.make(fit=True); m = qr.get_matrix(); n = len(m)
    pm = QPixmap(size, size); pm.fill(QColor("#ffffff")); p = QPainter(pm); cell = size / n
    p.setPen(Qt.NoPen); p.setBrush(QColor("#000000"))
    for y, row in enumerate(m):
        for x, on in enumerate(row):
            if on: p.drawRect(int(x * cell), int(y * cell), int(cell + 1), int(cell + 1))
    p.end(); return pm


class WebAccessPanel(QWidget):
    """The dashboard in a browser on phones and laptops: on/off, password, addresses, QR code."""
    changed = Signal()

    def __init__(self, settings, save):
        super().__init__(); self.settings = settings; self.save = save
        import web
        self.web = web
        lay = QVBoxLayout(self); lay.setSpacing(10)
        lay.addWidget(label("Web access", "sectionTitle"))
        lay.addWidget(label("Open the doorbell on a phone, tablet or laptop: its status, a live camera view, an alert "
                            "with STOP when someone rings, mute, and the recordings. At home over Wi-Fi, from anywhere "
                            "with Tailscale (nothing is opened to the internet). A password protects it.", "secondary", True))
        lay.addWidget(label("WEB ACCESS", "section")); row = QHBoxLayout(); group = QButtonGroup(self); self.onoff = []
        for value, text in ((True, "On"), (False, "Off")):
            b = button(text, "choice", True, 60); b.setChecked(settings.get("web_access", False) == value); group.addButton(b)
            b.clicked.connect(lambda _=False, v=value: self.set_on(v)); row.addWidget(b); self.onoff.append(b)
        lay.addLayout(row)
        lay.addWidget(label("PASSWORD (also logs out every phone when changed)", "section")); row = QHBoxLayout()
        self.pw = label("", "camValue"); row.addWidget(self.pw, 1)
        b = button("Set password", h=56); b.setFixedWidth(220); b.clicked.connect(self.set_password); row.addWidget(b)
        lay.addLayout(row)
        body = QHBoxLayout(); left = QVBoxLayout(); left.addWidget(label("OPEN IN A BROWSER", "section"))
        self.urls = QVBoxLayout(); left.addLayout(self.urls); left.addStretch(); body.addLayout(left, 1)
        self.qr = QLabel(); self.qr.setFixedSize(230, 230); self.qr.setAlignment(Qt.AlignCenter); body.addWidget(self.qr, 0, Qt.AlignTop)
        lay.addLayout(body)
        self.msg = label("", "secondary", True); lay.addWidget(self.msg); lay.addStretch()
        self.refresh()

    def refresh(self):
        self.pw.setText("set" if self.web.has_password() else "not set yet")
        while self.urls.count():
            w = self.urls.takeAt(0).widget()
            if w: w.deleteLater()
        addrs = web_addresses()
        for name, url in addrs:
            self.urls.addWidget(label(name, "secondary")); self.urls.addWidget(label(url, "webUrl"))
        pm = qr_pixmap(addrs[0][1]) if addrs else None
        if pm: self.qr.setPixmap(pm)
        else: self.qr.setText("")
        on = self.settings.get("web_access", False)
        self.msg.setText("" if on and self.web.has_password() else
                         "Set a password, then switch it on." if not self.web.has_password() else "Switched off: the page does not open.")

    def set_on(self, value):
        if value and not self.web.has_password():
            self.msg.setText("Set a password first."); self.onoff[1].setChecked(True); return
        self.settings["web_access"] = value; self.save(); self.changed.emit(); self.refresh()

    def set_password(self):
        pw = Keyboard.ask(self, "New password (at least 6 characters)", password=True)
        if pw is None: return
        if len(pw) < 6: self.msg.setText("At least 6 characters, please"); return
        again = Keyboard.ask(self, "The same password again", password=True)
        if again != pw: self.msg.setText("The two did not match; nothing changed"); return
        self.web.set_password(pw); self.msg.setText("✓ Password set. Phones need to log in again."); self.changed.emit(); self.refresh()

    def showEvent(self, e):
        super().showEvent(e); self.refresh()

class PhonePanel(QWidget):
    """Push notifications to phones (ntfy app): on/off, the topic to subscribe to, a test."""
    def __init__(self, settings, save, notifier):
        super().__init__(); self.settings = settings; self.save = save; self.notifier = notifier
        from notify import new_topic
        if not settings.get("notify_topic"): settings["notify_topic"] = new_topic(); save()
        self.new_topic = new_topic
        lay = QVBoxLayout(self); lay.setSpacing(12)
        lay.addWidget(label("Phone notifications", "sectionTitle"))
        lay.addWidget(label("A push notification on your phone whenever someone rings. Install the free ntfy app "
                            "(Play Store / App Store), tap +, and subscribe to the topic below. Anyone who knows the "
                            "topic gets the alerts, so share it only with your family.", "secondary", True))
        lay.addWidget(label("TOPIC TO SUBSCRIBE TO", "section"))
        self.topic = label("", "topicName"); self.topic.setTextInteractionFlags(Qt.TextSelectableByMouse); lay.addWidget(self.topic)
        self.server = label("", "secondary"); lay.addWidget(self.server)
        lay.addWidget(label("NOTIFY WHEN THE BELL RINGS", "section")); row = QHBoxLayout(); group = QButtonGroup(self); self.onoff = {}
        for value, text in ((True, "On"), (False, "Off")):
            b = button(text, "choice", True, 64); b.setChecked(settings.get("notify", False) == value); group.addButton(b); row.addWidget(b)
            self.onoff[value] = b
            b.clicked.connect(lambda _=False, value=value: self.set_on(value))
        lay.addLayout(row)
        lay.addWidget(label("ALERT WHEN THE DOORBELL IS OFFLINE (no power, no Wi-Fi) FOR", "section"))
        row = QHBoxLayout(); group = QButtonGroup(self); self.offline_btns = {}
        for value, text in ((0, "Never"), (5, "5 min"), (15, "15 min"), (60, "1 hour")):
            b = button(text, "choice", True, 64); b.setChecked(settings.get("offline_alert_min", 15) == value); group.addButton(b); row.addWidget(b)
            b.clicked.connect(lambda _=False, v=value: (self.settings.__setitem__("offline_alert_min", v), self.save())); self.offline_btns[value] = b
        lay.addLayout(row)
        row = QHBoxLayout()
        test = button("Send a test notification", h=64); test.clicked.connect(self.test); row.addWidget(test)
        fresh = button("New topic (stops the old one)", h=64); fresh.clicked.connect(self.change_topic); row.addWidget(fresh)
        lay.addLayout(row)
        self.msg = label("", "secondary", True); lay.addWidget(self.msg); lay.addStretch()
        notifier.result.connect(lambda ok, text: self.msg.setText(("✓ " if ok else "✗ ") + text))
        self.show_topic()
    def sync(self):
        self.onoff[bool(self.settings.get("notify", False))].setChecked(True); self.show_topic()
        b = self.offline_btns.get(self.settings.get("offline_alert_min", 15))
        if b: b.setChecked(True)
    def show_topic(self):
        self.topic.setText(self.settings["notify_topic"])
        self.server.setText(f"Server: {self.notifier.server}   ·   {self.notifier.encryption()}")
    def set_on(self, value):
        self.settings["notify"] = value; self.save()
        self.msg.setText("Rings will be sent to the topic above" if value else "No notifications are sent")
    def test(self):
        self.msg.setText("Sending…")
        self.notifier.send("Doorbell test", "Notifications from the indoor unit work.", tags="white_check_mark",
                           priority="default", force=True)
    def change_topic(self):
        self.settings["notify_topic"] = self.new_topic(); self.save(); self.show_topic()
        self.msg.setText("New topic: subscribe to it again in the ntfy app")

class AlertsPanel(QWidget):
    """The day's summary, the milk delivery and night visitors, on the phones (daily.py), and whether
    the visitor descriptions (describe.py) are working."""
    SUMMARY = ((0, "Off"), (20, "8 pm"), (21, "9 pm"), (22, "10 pm"))
    MILK = (("", "Off"), ("4:30-5:30", "4:30–5:30 am"), ("4-6", "4–6 am"), ("5-7", "5–7 am"), ("6-8", "6–8 am"))
    NIGHT = (("", "Off"), ("1-4", "1–4 am"), ("0-5", "12–5 am"), ("23-5", "11 pm–5 am"))
    DEFAULTS = {"summary_at": 21, "milk_window": "4:30-5:30", "night_window": "1-4"}

    def __init__(self, settings, save):
        super().__init__(); self.settings = settings; self.save = save; self.daily = self.describer = None; self.btns = {}
        lay = QVBoxLayout(self); lay.setSpacing(10)
        lay.addWidget(label("Alerts & summary", "sectionTitle"))
        lay.addWidget(label("Sent to the phones subscribed in Settings › Phone (and the devices with ring alerts on), "
                            "whether or not ring notifications are on.", "secondary", True))
        self.choices(lay, "DAILY SUMMARY: visitors, deliveries and rings, morning to night", "summary_at", self.SUMMARY)
        row = QHBoxLayout(); b = button("Send today's summary now", h=52); b.clicked.connect(self.send_now); row.addWidget(b); row.addStretch()
        lay.addLayout(row)
        self.choices(lay, "MILK DELIVERY: the milkman's walk (gate, the milk spot, gate) looked for every morning", "milk_window", self.MILK)
        self.milk = label("", "secondary", True); lay.addWidget(self.milk)
        self.choices(lay, "ALERT WHEN A PERSON IS AT THE DOOR AT NIGHT", "night_window", self.NIGHT)
        lay.addWidget(label("VISITOR DESCRIPTIONS (a vision-language model on this Pi; nothing leaves it)", "section"))
        self.model = label("", "secondary", True); lay.addWidget(self.model)
        self.msg = label("", "secondary", True); lay.addWidget(self.msg); lay.addStretch()
        self.timer = QTimer(self); self.timer.timeout.connect(self.show_status); self.timer.start(15000)

    def choices(self, lay, title, key, options):
        lay.addWidget(label(title, "section")); row = QHBoxLayout(); group = QButtonGroup(self); self.btns[key] = {}
        for value, text in options:
            b = button(text, "choice", True, 52); group.addButton(b); row.addWidget(b); self.btns[key][value] = b
            b.clicked.connect(lambda _=False, k=key, v=value: self.set(k, v))
        lay.addLayout(row); self.sync()

    def attach(self, daily, describer):
        self.daily = daily; self.describer = describer; daily.changed.connect(self.show_status); self.show_status()

    def set(self, key, value):
        self.settings[key] = value; self.save(); self.show_status()

    def send_now(self):
        if self.daily: self.daily.send_summary(); self.msg.setText("✓ Today's summary sent")

    def show_status(self):
        if not self.daily or not self.isVisible(): return
        self.milk.setText(self.daily.milk_status()); self.model.setText(self.describer.status())

    def sync(self):
        for key, btns in self.btns.items():
            b = btns.get(self.settings.get(key, self.DEFAULTS[key]))
            if b: b.setChecked(True)

    def showEvent(self, e):
        super().showEvent(e); self.msg.setText(""); self.show_status()

class FestivalPanel(QWidget):
    """Festival themes: Diwali (2 days either side), Christmas (Dec 23-27) and
    New Year (Jan 1-2) change the look of both units, and optionally the tones."""
    LOOKS = {"diwali": "Golden temple bell, rising sparks, shehnai / temple bell tone",
             "christmas": "Twin bells on green, snowfall, Jingle Bells",
             "new_year": "Gold bell on midnight blue, confetti, Auld Lang Syne"}
    def __init__(self, settings, save, changed, preview, extra=None):
        super().__init__(); self.settings = settings; self.save = save; self.changed = changed; self.extra = extra
        lay = QVBoxLayout(self); lay.setSpacing(12)
        lay.addWidget(label("Festivals", "sectionTitle"))
        lay.addWidget(label("Around festivals the dashboard and the doorbell switch to a festive theme by themselves "
                            "and return to your own settings afterwards.", "secondary", True))
        self.flag_btns = {}
        for title, key, texts in (("FESTIVE THEMES", "festival_themes", ("Automatic", "Off")),
                                  ("FESTIVE BELL TONES", "festival_tones", ("On", "Off"))):
            lay.addWidget(label(title, "section")); row = QHBoxLayout(); group = QButtonGroup(self)
            for value, text in zip((True, False), texts):
                b = button(text, "choice", True, 64); b.setChecked(settings.get(key, True) == value); group.addButton(b); row.addWidget(b)
                b.clicked.connect(lambda _=False, key=key, value=value: self.set(key, value)); self.flag_btns[(key, value)] = b
            lay.addLayout(row)
        lay.addWidget(label("COMING UP", "section")); self.dates = label("", "secondary", True); lay.addWidget(self.dates)
        lay.addWidget(label("TRY ONE FOR A MINUTE", "section")); row = QHBoxLayout()
        for key, (name, _) in FESTIVALS.items():
            b = button(name, "choice", h=64); b.clicked.connect(lambda _=False, key=key: preview(key)); row.addWidget(b)
        b = button("Back to normal", "choice", h=64); b.clicked.connect(lambda: preview("")); row.addWidget(b)
        lay.addLayout(row); lay.addStretch(); self.refresh()
    def set(self, key, value):
        self.settings[key] = value; self.save(); self.changed()
    def sync(self):
        for key in ("festival_themes", "festival_tones"): self.flag_btns[(key, bool(self.settings.get(key, True)))].setChecked(True)
    def refresh(self):
        import datetime as dt
        lines = []
        for key, first, last in upcoming(dt.date.today(), self.extra):
            lines.append(f"{FESTIVALS[key][0]}: {first:%a %d %b} – {last:%a %d %b %Y}  ·  {self.LOOKS[key]}")
        self.dates.setText("\n".join(lines))
    def showEvent(self, e):
        super().showEvent(e); self.refresh()

class OutdoorPanel(QWidget):
    """Mirrors the outdoor unit's own settings. Every change is sent at once; the
    buttons show what the outdoor unit reports back, so they are always true."""
    def __init__(self, send):
        super().__init__(); self.send = send; self.state = {}; self.online = None; self.networks = []
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(10)
        # always visible: title, the doorbell's status, the last confirmation; then the sub-tabs
        head = QHBoxLayout(); head.addWidget(label("Outdoor unit", "sectionTitle")); head.addStretch()
        self.status = label("Waiting for the outdoor unit…", "secondary"); head.addWidget(self.status); lay.addLayout(head)
        tabs = QHBoxLayout(); tabs.setSpacing(10); group = QButtonGroup(self); self.pages = QStackedWidget()
        for i, name in enumerate(("Look", "Sound", "Screen", "Network")):
            b = button(name, "subtab", True, 56); b.setChecked(i == 0); group.addButton(b); tabs.addWidget(b)
            b.clicked.connect(lambda _=False, i=i: self.pages.setCurrentIndex(i))
            page = QWidget(); QVBoxLayout(page).setSpacing(10); self.pages.addWidget(page)
        lay.addLayout(tabs); lay.addWidget(self.pages, 1)
        self.msg = label("", "status"); lay.addWidget(self.msg)
        look, sound, screen, net = (self.pages.widget(i).layout() for i in range(4))

        def choice_row(into, title, options, key, values, cols=0, icons=None, h=56):
            into.addWidget(label(title, "section")); grid = QGridLayout(); grid.setSpacing(10); group = QButtonGroup(self); btns = []
            for i, text in enumerate(options):
                b = button(text, "choice", True, h); group.addButton(b); btns.append(b)
                if icons and icons[i]: b.setIcon(QIcon(str(icons[i]))); b.setIconSize(QSize(h - 16, h - 16))
                grid.addWidget(b, i // cols if cols else 0, i % cols if cols else i)
                b.clicked.connect(lambda _=False, v=values[i]: self.set(key, v))
            into.addLayout(grid); return btns

        # Look: theme, bell colour and style, glow
        self.theme_btns = choice_row(look, "THEME", OUTDOOR_THEMES, "theme", range(len(OUTDOOR_THEMES)))
        self.bell_btns = choice_row(look, "BELL COLOUR", [n for n, _ in OUTDOOR_BELLS], "bell_color", range(len(OUTDOOR_BELLS)))
        for b, (_, color) in zip(self.bell_btns, OUTDOOR_BELLS): b.setIcon(dot_icon(color)); b.setIconSize(QSize(22, 22))
        icons = [next(BELL_ICONS.glob(f"{i}_*.png"), None) for i in range(len(OUTDOOR_STYLES))]
        self.style_btns = choice_row(look, "BELL STYLE", OUTDOOR_STYLES, "bell_style", range(len(OUTDOOR_STYLES)), cols=3, icons=icons, h=76)
        self.glow_btns = choice_row(look, "BACKGROUND GLOW", ["Off", "Aurora (magenta · cyan)"], "glow", [False, True])
        look.addStretch()

        # Sound: the doorbell's own chime, and how long a ring lasts
        self.chime_btns = choice_row(sound, "CHIME (the doorbell's own speaker)", OUTDOOR_CHIMES, "chime", range(len(OUTDOOR_CHIMES)), cols=3)
        self.repeat_btns = choice_row(sound, "CHIME PLAYS", ["Once per press", "For the whole ring"], "chime_repeat", [False, True])
        self.volume_btns = choice_row(sound, "VOLUME", [n for n, _ in OUTDOOR_VOLUMES], "volume", [v for _, v in OUTDOOR_VOLUMES])
        self.ring_btns = choice_row(sound, "RING DURATION (seconds)", [str(s) for s in OUTDOOR_DURATIONS], "ring_seconds", OUTDOOR_DURATIONS)
        sound.addStretch()

        # Screen: off at night (on/off, from, until), and the screen right now
        screen.addWidget(label("SCREEN OFF AT NIGHT (a touch lights it for 30 s; rings always light it)", "section"))
        grid = QGridLayout(); grid.setSpacing(10); group = QButtonGroup(self); self.night_btns = []
        for i, (text, v) in enumerate((("On", True), ("Off: always lit", False))):
            b = button(text, "choice", True, 56); group.addButton(b); grid.addWidget(b, 0, i); self.night_btns.append(b)
            b.clicked.connect(lambda _=False, v=v: self.set("screen_off", {"enabled": v}))
        screen.addLayout(grid)
        row = QHBoxLayout(); self.night_hours = {}
        for key, title in (("from", "From"), ("to", "Until")):
            row.addWidget(label(title, "secondary"))
            minus = button("−", h=56); minus.setFixedWidth(64); row.addWidget(minus)
            v = label("", "camValue"); v.setAlignment(Qt.AlignCenter); v.setMinimumWidth(130); row.addWidget(v); self.night_hours[key] = v
            plus = button("+", h=56); plus.setFixedWidth(64); row.addWidget(plus); row.addSpacing(24)
            minus.clicked.connect(lambda _=False, k=key: self.step_hour(k, -1)); plus.clicked.connect(lambda _=False, k=key: self.step_hour(k, 1))
        row.addStretch(); screen.addLayout(row)
        screen.addWidget(label("RIGHT NOW", "section"))
        row = QHBoxLayout(); self.screen_now = label("", "camValue"); row.addWidget(self.screen_now, 1)
        for text, cmd in (("Turn screen on", "screen_on"), ("Turn screen off", "screen_off")):
            b = button(text, h=56); b.setMinimumWidth(220); b.clicked.connect(lambda _=False, c=cmd: self.screen_command(c)); row.addWidget(b)
        screen.addLayout(row)
        screen.addWidget(label("Turned on, it stays lit until you turn it off or the night ends; turned off, it stays dark "
                               "until a touch, a ring, you turn it on, or the schedule changes (at the From/Until hour).",
                               "secondary", True))
        screen.addStretch()

        # Network: Wi-Fi and the indoor unit's address, changed together
        net.addWidget(label("NOW", "section"))
        self.wifi_now = label("", "secondary"); net.addWidget(self.wifi_now)
        self.broker = label("", "secondary"); net.addWidget(self.broker)
        net.addWidget(label("CHANGE (Wi-Fi and indoor unit address, applied together)", "section"))
        row = QHBoxLayout(); scan = button("Scan networks"); scan.clicked.connect(self.scan)
        change = button("Change network…"); change.clicked.connect(self.change_network)
        row.addWidget(scan); row.addWidget(change); net.addLayout(row)
        self.wifi_list = QListWidget(); self.wifi_list.setObjectName("list"); touch_scroll(self.wifi_list)
        net.addWidget(self.wifi_list, 1)
        QListWidgetItem("Tap Scan networks to list the Wi-Fi networks the doorbell sees", self.wifi_list)
        net.addWidget(label("Choose a network in the list to move the doorbell to it, or none to keep its Wi-Fi and only "
                            "change the indoor unit address. The doorbell keeps the new settings only if it joins the "
                            "Wi-Fi and reaches the indoor unit within 60 s; otherwise it goes back to the old ones.",
                            "secondary", True))
        self.refresh()

    def set(self, key, value):
        if self.send({key: value}): self.msg.setText("Sent · waiting for the outdoor unit to confirm")
        else: self.msg.setText("Not sent: MQTT is not connected"); self.refresh()
    def night(self):
        return {"enabled": True, "from": 23, "to": 6, **(self.state.get("screen_off") or {})}
    def step_hour(self, key, delta):
        self.set("screen_off", {key: (self.night()[key] + delta) % 24})
    def screen_command(self, cmd):
        if self.send({"command": cmd}): self.msg.setText("Sent · the doorbell confirms below")
        else: self.msg.setText("Not sent: MQTT is not connected")
    def scan(self):
        if self.send({"command": "wifi_scan"}): self.wifi_list.clear(); QListWidgetItem("Scanning…", self.wifi_list)
    def change_network(self):
        """Wi-Fi (the network chosen in the list, if any) + password + indoor unit address,
        sent as one 'network' command so the doorbell switches everything at once."""
        change = {}
        i = self.wifi_list.currentRow()
        if 0 <= i < len(self.networks):
            n = self.networks[i]; pw = ""
            if n.get("secure", True):
                pw = Keyboard.ask(self, f"Wi-Fi password for {n['ssid']}", password=True)
                if pw is None: return
                if len(pw) < 8: self.msg.setText("A Wi-Fi password has at least 8 characters"); return
            change.update(ssid=n["ssid"], password=pw)
        current = self.state.get("broker", "")
        host = Keyboard.ask(self, "Indoor unit address: this Pi's IP on the doorbell's network", current or this_ip())
        if host is None: return
        host = host.strip()
        if host and host != current: change["broker"] = host
        if not change: self.msg.setText("Nothing to change: choose a network in the list or enter a new address"); return
        if self.send({"network": change}):
            what = " and ".join(t for t in (f"Wi-Fi {change['ssid']}" if "ssid" in change else "",
                                            f"address {change['broker']}" if "broker" in change else "") if t)
            self.msg.setText(f"Sent: {what}. The doorbell confirms within 60 s, or returns to its old settings.")

    # ---- updates from MQTT ----
    def on_state(self, data):
        self.state = data; self.refresh()
        result = data.get("network_change")
        self.msg.setText({"applied": "Network change applied and saved on the doorbell",
                          "reverted": "Network change failed: the doorbell went back to its previous Wi-Fi and address"}
                         .get(result, ""))
    def on_online(self, online):
        self.online = online; self.refresh()
    def on_scan(self, data):
        self.networks = data.get("networks", []); self.wifi_list.clear()
        for n in self.networks:
            QListWidgetItem(f"{n.get('ssid')}    ·  {n.get('rssi')} dBm{'' if n.get('secure', True) else '  · open'}", self.wifi_list)
        if not self.networks: QListWidgetItem("No networks found", self.wifi_list)
    def refresh(self):
        s = self.state
        if self.online is None and not s: self.status.setText("Waiting for the outdoor unit…")
        else:
            self.status.setText(("● Online" if self.online else "○ Offline (showing its last known settings)") +
                                (f"   ·   firmware {s['firmware']}" if s.get("firmware") else ""))
        for btns, key, values in [(self.theme_btns, "theme", list(range(len(OUTDOOR_THEMES)))),
                                  (self.bell_btns, "bell_color", list(range(len(OUTDOOR_BELLS)))),
                                  (self.style_btns, "bell_style", list(range(len(OUTDOOR_STYLES)))),
                                  (self.glow_btns, "glow", [False, True]),
                                  (self.chime_btns, "chime", list(range(len(OUTDOOR_CHIMES)))),
                                  (self.repeat_btns, "chime_repeat", [False, True]),
                                  (self.volume_btns, "volume", [v for _, v in OUTDOOR_VOLUMES]),
                                  (self.ring_btns, "ring_seconds", OUTDOOR_DURATIONS)]:
            for b, v in zip(btns, values): b.setChecked(s.get(key) == v)
        n = self.night(); reported = "screen_off" in s
        for b, v in zip(self.night_btns, (True, False)): b.setChecked(reported and n["enabled"] == v)
        hour = lambda h: f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"
        for key, v in self.night_hours.items(): v.setText(hour(n[key]) if reported else "—")
        self.screen_now.setText("Doorbell screen now: " + ("lit" if s.get("screen_lit") else "off") if "screen_lit" in s
                                else "Doorbell screen: needs the doorbell firmware with this setting")
        self.wifi_now.setText(f"Wi-Fi: {s['wifi_ssid']} (doorbell IP {s.get('ip') or 'none'})" if s.get("wifi_ssid") else "Wi-Fi: not reported yet")
        self.broker.setText(f"Indoor unit address: {s['broker']}" if s.get("broker") else "Indoor unit address: not reported yet")

class LookPanel(QWidget):
    """How the whole screen looks: the pages' colours and the home page's layout (looks.py)."""
    on_look = None  # set by the window: applies the choice straight away

    def __init__(self, settings, save):
        super().__init__()
        import looks
        self.looks = looks; self.settings = settings; self.save_settings = save; self.cards = {}
        lay = QVBoxLayout(self); lay.setSpacing(10)
        lay.addWidget(label("Look", "sectionTitle"))
        lay.addWidget(label("The home screen's layout and the colours and type of every page. "
                            "Tap one to try it: the screen changes straight away.", "secondary", True))
        grid = QGridLayout(); grid.setSpacing(16); group = QButtonGroup(self)
        for i, (key, look) in enumerate(looks.LOOKS.items()):
            b = QPushButton(); b.setObjectName("lookCard"); b.setCheckable(True); b.setFixedHeight(316); group.addButton(b)
            cl = QVBoxLayout(b); cl.setContentsMargins(14, 14, 14, 12); cl.setSpacing(6)
            pic = QLabel(); pic.setFixedHeight(204)
            if looks.preview(key):
                pic.setPixmap(QPixmap(str(looks.preview(key))).scaledToHeight(204, Qt.SmoothTransformation))
            for w in (pic, label(look["name"], "lookName"), label(look["about"], "lookAbout", True)):
                w.setAttribute(Qt.WA_TransparentForMouseEvents); cl.addWidget(w)
            cl.addStretch()
            b.clicked.connect(lambda _=False, k=key: self.choose(k)); self.cards[key] = b
            grid.addWidget(b, i // 2, i % 2)
        lay.addLayout(grid); lay.addStretch(); self.sync()

    def choose(self, key):
        self.settings["look"] = key; self.save_settings()
        if self.on_look: self.on_look()

    def sync(self):
        key = self.settings.get("look")
        self.cards[key if key in self.cards else self.looks.DEFAULT].setChecked(True)

class SettingsPage(QFrame):
    back = Signal()
    festival_changed = Signal()
    festival_preview = Signal(str)  # festival key to try for a minute, "" to end the trial
    def __init__(self, bt, tones, settings, save, preview, send, news_changed, festival_extra=None, notifier=None):
        super().__init__(); self.setObjectName("settings")
        root = QVBoxLayout(self); root.setContentsMargins(24, 20, 24, 20); root.setSpacing(16)
        head = QHBoxLayout(); head.addWidget(label("Settings", "pageTitle")); head.addStretch()
        b = button("‹  Back", h=56); b.setFixedWidth(160); b.clicked.connect(self.back.emit); head.addWidget(b); root.addLayout(head)
        body = QHBoxLayout(); body.setSpacing(24); nav = QVBoxLayout(); nav.setSpacing(10)
        self.stack = QStackedWidget()
        self.speaker = SpeakerPanel(bt, settings, save); self.tone = TonePanel(tones, settings, save, preview); self.outdoor = OutdoorPanel(send)
        self.news = NewsPanel(settings, save, news_changed)
        self.festivals = FestivalPanel(settings, save, self.festival_changed.emit, self.festival_preview.emit, festival_extra)
        self.phone = PhonePanel(settings, save, notifier); self.alerts = AlertsPanel(settings, save)
        self.camera = CameraPanel(settings, save)
        self.camera.ring_seconds = lambda: self.outdoor.state.get("ring_seconds")
        self.webaccess = WebAccessPanel(settings, save); self.look = LookPanel(settings, save)
        group = QButtonGroup(self)
        for i, (text, panel) in enumerate([("Look", self.look), ("Speaker", self.speaker), ("Bell tone", self.tone), ("News", self.news),
                                           ("Festivals", self.festivals), ("Phone", self.phone), ("Alerts", self.alerts), ("Camera", self.camera), ("Web access", self.webaccess), ("Outdoor unit", self.outdoor)]):
            panel_frame = QFrame(); panel_frame.setObjectName("panel"); QVBoxLayout(panel_frame).addWidget(panel); self.stack.addWidget(panel_frame)
            nb = button(text, "nav", True, 58); group.addButton(nb); nav.addWidget(nb)
            nb.clicked.connect(lambda _=False, i=i: self.stack.setCurrentIndex(i)); nb.setChecked(i == 0)
        nav.addStretch(); navw = QWidget(); navw.setLayout(nav); navw.setFixedWidth(240)
        body.addWidget(navw); body.addWidget(self.stack, 1); root.addLayout(body, 1)

    def sync(self):
        """A setting was changed in a browser: the buttons here show it too."""
        for panel in (self.look, self.speaker, self.tone, self.news, self.camera, self.phone, self.alerts, self.festivals): panel.sync()
        self.webaccess.refresh()
