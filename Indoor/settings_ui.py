"""Settings screen of the indoor unit: Bluetooth speaker, bell tone, and the
outdoor unit's settings (applied over MQTT, see topics.md)."""
import time
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize
from news import GENRES, REGIONS
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QScroller, QSizePolicy, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget, QButtonGroup)

# Must match the outdoor firmware's tables (Outdoor/src/doorbell_ui.c).
OUTDOOR_THEMES = ["Clean & Light", "Midnight & Gold"]
OUTDOOR_BELLS = [("Blue", "#2F80ED"), ("Gold", "#D4A537"), ("Silver", "#A7B1BC"), ("Red", "#D64545")]
OUTDOOR_DURATIONS = [10, 15, 30, 45, 60]

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
        bt.devices.connect(self.show_devices); bt.status.connect(self.msg.setText); bt.output.connect(self.show_output)
        self.test_cb = None
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

class TonePanel(QWidget):
    def __init__(self, folder, settings, save, preview):
        super().__init__(); self.settings = settings; self.save = save
        lay = QVBoxLayout(self); lay.setSpacing(12)
        lay.addWidget(label("Bell tone", "sectionTitle"))
        lay.addWidget(label("Played on the speaker for the whole ring, until it times out or STOP is pressed.", "secondary", True))
        group = QButtonGroup(self); group.setExclusive(True)
        for path in sorted(folder.glob("*.wav")):
            row = QHBoxLayout()
            pick = button(path.stem.replace("_", " ").title(), "choice", True, 64)
            pick.setChecked(settings.get("tone") == path.name); group.addButton(pick)
            pick.clicked.connect(lambda _=False, n=path.name: self.choose(n))
            play = button("▶  Preview", h=64); play.setFixedWidth(180); play.clicked.connect(lambda _=False, p=path: preview(p))
            row.addWidget(pick, 1); row.addWidget(play); lay.addLayout(row)
        lay.addStretch()
    def choose(self, name):
        self.settings["tone"] = name; self.save()

class NewsPanel(QWidget):
    """Region (one) and genres (any number) of the headlines on the main page."""
    def __init__(self, settings, save, changed):
        super().__init__(); self.settings = settings; self.save = save; self.changed = changed
        lay = QVBoxLayout(self); lay.setSpacing(12)
        lay.addWidget(label("News", "sectionTitle"))
        lay.addWidget(label("Headlines on the main page (the Photos / News tile there switches between them). "
                            "From Google News, refreshed every 15 minutes.", "secondary", True))
        lay.addWidget(label("REGIONS (choose any; their news is mixed)", "section")); row = QHBoxLayout()
        current = set(settings.get("news_regions") or [settings.get("news_region", "india")]); self.region_btns = {}
        for key, (text, _, _) in REGIONS.items():
            b = button(text, "choice", True, 64); b.setChecked(key in current); row.addWidget(b)
            b.toggled.connect(lambda _=False: self.set_regions()); self.region_btns[key] = b
        lay.addLayout(row)
        lay.addWidget(label("GENRES (choose any)", "section")); grid = QGridLayout(); grid.setSpacing(10)
        chosen = set(settings.get("news_genres", ["top"])); self.genre_btns = {}
        for i, (key, (text, _)) in enumerate(GENRES.items()):
            b = button(text, "choice", True, 64); b.setChecked(key in chosen); grid.addWidget(b, i // 3, i % 3)
            b.toggled.connect(lambda _=False: self.set_genres()); self.genre_btns[key] = b
        lay.addLayout(grid)
        self.msg = label("", "secondary", True); lay.addWidget(self.msg); lay.addStretch()
    def set_regions(self):
        keys = [k for k, b in self.region_btns.items() if b.isChecked()]
        self.settings["news_regions"] = keys or ["india"]; self.settings.pop("news_region", None); self.save(); self.changed()
        self.msg.setText("Updating headlines…" if keys else "No region chosen: showing India")
    def set_genres(self):
        keys = [k for k, b in self.genre_btns.items() if b.isChecked()]
        self.settings["news_genres"] = keys or ["top"]; self.save(); self.changed()
        self.msg.setText("Updating headlines…" if keys else "No genre chosen: showing top stories")

class OutdoorPanel(QWidget):
    """Mirrors the outdoor unit's own settings. Every change is sent at once; the
    buttons show what the outdoor unit reports back, so they are always true."""
    def __init__(self, send):
        super().__init__(); self.send = send; self.state = {}; self.online = None; self.networks = []
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); touch_scroll(scroll)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # dragged with a finger
        body = QWidget(); lay = QVBoxLayout(body); lay.setSpacing(12); scroll.setWidget(body); outer.addWidget(scroll)

        lay.addWidget(label("Outdoor unit", "sectionTitle"))
        self.status = label("Waiting for the outdoor unit…", "secondary", True); lay.addWidget(self.status)

        def choice_row(title, options, key, values):
            lay.addWidget(label(title, "section")); row = QHBoxLayout(); group = QButtonGroup(self); btns = []
            for i, text in enumerate(options):
                b = button(text, "choice", True); group.addButton(b); row.addWidget(b); btns.append(b)
                b.clicked.connect(lambda _=False, v=values[i]: self.set(key, v))
            lay.addLayout(row); return btns
        self.theme_btns = choice_row("THEME", OUTDOOR_THEMES, "theme", range(len(OUTDOOR_THEMES)))
        self.bell_btns = choice_row("BELL COLOUR", [n for n, _ in OUTDOOR_BELLS], "bell_color", range(len(OUTDOOR_BELLS)))
        for b, (_, color) in zip(self.bell_btns, OUTDOOR_BELLS): b.setIcon(dot_icon(color)); b.setIconSize(QSize(22, 22))
        self.ring_btns = choice_row("RING DURATION (seconds)", [str(s) for s in OUTDOOR_DURATIONS], "ring_seconds", OUTDOOR_DURATIONS)

        lay.addWidget(label("WI-FI", "section"))
        self.wifi_now = label("", "secondary"); lay.addWidget(self.wifi_now)
        row = QHBoxLayout(); scan = button("Scan networks"); scan.clicked.connect(self.scan)
        join = button("Join selected network…"); join.clicked.connect(self.join); row.addWidget(scan); row.addWidget(join); lay.addLayout(row)
        self.wifi_list = QListWidget(); self.wifi_list.setObjectName("list"); self.wifi_list.setMinimumHeight(220); touch_scroll(self.wifi_list)
        lay.addWidget(self.wifi_list)
        lay.addWidget(label("If the outdoor unit cannot join the new network it goes back to the one it has now.", "secondary", True))

        lay.addWidget(label("INDOOR UNIT ADDRESS (MQTT broker)", "section"))
        row = QHBoxLayout(); self.broker = label("", "secondary"); row.addWidget(self.broker, 1)
        change = button("Change…"); change.setFixedWidth(200); change.clicked.connect(self.change_broker); row.addWidget(change); lay.addLayout(row)
        lay.addWidget(label("Only change this when the Pi's address changes: with a wrong address the outdoor unit "
                            "can no longer be reached from here and must be set on the doorbell itself.", "secondary", True))
        self.msg = label("", "status"); lay.addWidget(self.msg); lay.addStretch()
        self.refresh()

    def set(self, key, value):
        if self.send({key: value}): self.msg.setText("Sent · waiting for the outdoor unit to confirm")
        else: self.msg.setText("Not sent: MQTT is not connected"); self.refresh()
    def scan(self):
        if self.send({"command": "wifi_scan"}): self.wifi_list.clear(); QListWidgetItem("Scanning…", self.wifi_list)
    def join(self):
        i = self.wifi_list.currentRow()
        if not (0 <= i < len(self.networks)): self.msg.setText("Scan, then choose a network in the list first"); return
        n = self.networks[i]; pw = ""
        if n.get("secure", True):
            pw = Keyboard.ask(self, f"Wi-Fi password for {n['ssid']}", password=True)
            if pw is None: return
            if len(pw) < 8: self.msg.setText("A Wi-Fi password has at least 8 characters"); return
        if self.send({"wifi": {"ssid": n["ssid"], "password": pw}}):
            self.msg.setText(f"Asked the outdoor unit to join {n['ssid']} · it reconnects in a few seconds")
    def change_broker(self):
        host = Keyboard.ask(self, "Indoor unit address (IP of this Pi)", self.state.get("broker", ""))
        if host and host.strip() and self.send({"broker": host.strip()}): self.msg.setText(f"Outdoor unit will now use {host.strip()}")

    # ---- updates from MQTT ----
    def on_state(self, data):
        self.state = data; self.msg.setText(""); self.refresh()
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
                                  (self.ring_btns, "ring_seconds", OUTDOOR_DURATIONS)]:
            for b, v in zip(btns, values): b.setChecked(s.get(key) == v)
        self.wifi_now.setText(f"Connected to {s['wifi_ssid']} ({s.get('ip') or 'no address'})" if s.get("wifi_ssid") else "Not reported yet")
        self.broker.setText(s.get("broker") or "Not reported yet")

class SettingsPage(QFrame):
    back = Signal()
    def __init__(self, bt, tones, settings, save, preview, send, news_changed):
        super().__init__(); self.setObjectName("settings")
        root = QVBoxLayout(self); root.setContentsMargins(24, 20, 24, 20); root.setSpacing(16)
        head = QHBoxLayout(); head.addWidget(label("Settings", "pageTitle")); head.addStretch()
        b = button("‹  Back", h=56); b.setFixedWidth(160); b.clicked.connect(self.back.emit); head.addWidget(b); root.addLayout(head)
        body = QHBoxLayout(); body.setSpacing(24); nav = QVBoxLayout(); nav.setSpacing(10)
        self.stack = QStackedWidget()
        self.speaker = SpeakerPanel(bt, settings, save); self.tone = TonePanel(tones, settings, save, preview); self.outdoor = OutdoorPanel(send)
        self.news = NewsPanel(settings, save, news_changed)
        group = QButtonGroup(self)
        for i, (text, panel) in enumerate([("Speaker", self.speaker), ("Bell tone", self.tone), ("News", self.news),
                                           ("Outdoor unit", self.outdoor)]):
            panel_frame = QFrame(); panel_frame.setObjectName("panel"); QVBoxLayout(panel_frame).addWidget(panel); self.stack.addWidget(panel_frame)
            nb = button(text, "nav", True, 72); group.addButton(nb); nav.addWidget(nb)
            nb.clicked.connect(lambda _=False, i=i: self.stack.setCurrentIndex(i)); nb.setChecked(i == 0)
        nav.addStretch(); navw = QWidget(); navw.setLayout(nav); navw.setFixedWidth(240)
        body.addWidget(navw); body.addWidget(self.stack, 1); root.addLayout(body, 1)
