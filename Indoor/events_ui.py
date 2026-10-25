"""Events page of the dashboard: every ring, newest first, with its recording.
A tap plays the clip full screen (decoded with OpenCV, so no extra media
packages are needed); it can be replayed or deleted. Select picks several
events to delete; Delete all clears the list. Every delete asks for a second
tap within CONFIRM_MS instead of a dialog."""
import time
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QScroller,
                               QSizePolicy, QVBoxLayout, QWidget)
from recorder import CLIP_S, DIR
try:
    import cv2
except ImportError:
    cv2 = None

COLUMNS = 4
KINDS = {"ring": "Rang the bell"}
CONFIRM_MS = 4000


def confirm(button, question, action):
    """First tap arms the button ("Tap again to …"), a second tap within CONFIRM_MS runs `action`."""
    if button.property("armed"):
        button.setProperty("armed", False); action(); return
    original = button.text(); button.setProperty("armed", True); button.setText(question)
    def disarm():
        try:
            if button.property("armed"): button.setProperty("armed", False); button.setText(original)
        except RuntimeError: pass  # the button is gone
    QTimer.singleShot(CONFIRM_MS, disarm)


def when(t):
    lt, now = time.localtime(t), time.localtime()
    clock = time.strftime("%I:%M %p", lt).lstrip("0")
    days = (time.mktime(now[:3] + (0, 0, 0, 0, 0, -1)) - time.mktime(lt[:3] + (0, 0, 0, 0, 0, -1))) // 86400
    return f"Today {clock}" if days == 0 else f"Yesterday {clock}" if days == 1 else time.strftime("%a %d %b · ", lt) + clock


class Card(QPushButton):
    def __init__(self, entry):
        super().__init__(); self.setObjectName("eventCard"); self.setFixedSize(380, 320); self.entry = entry
        lay = QVBoxLayout(self); lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(6)
        pic = QLabel(); pic.setObjectName("eventPic"); pic.setAlignment(Qt.AlignCenter); pic.setFixedSize(360, 203)
        pm = QPixmap(str(DIR / entry["thumb"])) if entry.get("thumb") else QPixmap()
        if pm.isNull(): pic.setText(entry.get("note") or "No recording")
        else: pic.setPixmap(pm.scaled(pic.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        lay.addWidget(pic)
        lines = ((KINDS.get(entry["kind"], entry["kind"]), "eventKind"), (when(entry["time"]), "eventTime"),
                 (("▶  " + f"{entry.get('seconds', CLIP_S)} s" + (f" · from {entry['pre']:.0f} s before the press" if entry.get("pre") else " recording"))
                  if entry.get("video") else "No recording", "eventTime"))
        for text, obj in lines:
            l = QLabel(text); l.setObjectName(obj); l.setAlignment(Qt.AlignCenter); lay.addWidget(l)
        for w in self.findChildren(QLabel): w.setAttribute(Qt.WA_TransparentForMouseEvents)


class Playback(QThread):
    """Decodes an MP4 and hands frames over at the clip's own pace."""
    frame = Signal(QImage)

    def __init__(self, path):
        super().__init__(); self.path = path

    def run(self):
        cap = cv2.VideoCapture(str(self.path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 15
        start = time.monotonic(); n = 0
        while not self.isInterruptionRequested():
            ok, img = cap.read()
            if not ok: break
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB); h, w, _ = rgb.shape
            self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())
            n += 1; wait = start + n / fps - time.monotonic()
            if wait > 0: self.msleep(int(wait * 1000))
        cap.release()


class Player(QFrame):
    """Full-screen player over the dashboard."""
    deleted = Signal(dict)

    def __init__(self, parent, entry):
        super().__init__(parent); self.setObjectName("player"); self.entry = entry; self.thread = None; self.last = None
        self.setGeometry(parent.rect())
        root = QVBoxLayout(self); root.setContentsMargins(24, 20, 24, 20); root.setSpacing(12)
        head = QHBoxLayout()
        title = QLabel(f"{KINDS.get(entry['kind'], entry['kind'])} · {when(entry['time'])}"); title.setObjectName("pageTitle")
        head.addWidget(title); head.addStretch()
        for text, slot in (("↻  Replay", self.play), ("Delete", None), ("✕  Close", self.close_player)):
            b = QPushButton(text); b.setMinimumHeight(56); b.setFixedWidth(220 if slot is None else 170); head.addWidget(b)
            b.clicked.connect(slot or (lambda _=False, b=b: confirm(b, "Tap again to delete", self.delete)))
        root.addLayout(head)
        self.view = QLabel(); self.view.setObjectName("videoView"); self.view.setAlignment(Qt.AlignCenter)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored); root.addWidget(self.view, 1)
        self.show(); self.raise_(); self.play()

    def play(self):
        self.stop()
        if not self.entry.get("video") or cv2 is None:
            self.view.setText(self.entry.get("note") or "No recording"); return
        self.thread = Playback(DIR / self.entry["video"]); self.thread.frame.connect(self.show_frame); self.thread.start()

    def show_frame(self, img):
        self.last = img
        self.view.setPixmap(QPixmap.fromImage(img).scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def stop(self):
        if self.thread:
            self.thread.requestInterruption(); self.thread.wait(2000); self.thread = None

    def delete(self):
        self.stop(); self.deleted.emit(self.entry); self.deleteLater()

    def close_player(self):
        self.stop(); self.deleteLater()


class EventsPage(QFrame):
    back = Signal()

    def __init__(self, recorder):
        super().__init__(); self.setObjectName("settings"); self.rec = recorder; self.selecting = False; self.cards = []
        root = QVBoxLayout(self); root.setContentsMargins(24, 20, 24, 20); root.setSpacing(12)
        head = QHBoxLayout(); t = QLabel("Events"); t.setObjectName("pageTitle"); head.addWidget(t); head.addStretch()
        self.select_btn = QPushButton("Select"); self.select_btn.clicked.connect(self.toggle_select)
        self.del_sel_btn = QPushButton("Delete selected"); self.del_sel_btn.hide()
        self.del_sel_btn.clicked.connect(lambda: self.selected() and confirm(
            self.del_sel_btn, f"Tap again: delete {len(self.selected())}", self.delete_selected))
        self.del_all_btn = QPushButton("Delete all")
        self.del_all_btn.clicked.connect(lambda: self.rec.entries and confirm(
            self.del_all_btn, f"Tap again: delete all {len(self.rec.entries)}", self.delete_all))
        for b in (self.select_btn, self.del_sel_btn, self.del_all_btn):
            b.setMinimumHeight(56); b.setMinimumWidth(170); head.addWidget(b)
        head.addSpacing(16)
        b = QPushButton("‹  Back"); b.setMinimumHeight(56); b.setFixedWidth(160); b.clicked.connect(self.back.emit); head.addWidget(b)
        root.addLayout(head)
        note = QLabel("Every ring with its recording (length: Settings › Camera), saved on the Pi's SD card for 30 days. "
                      "Tap one to play it.")
        note.setObjectName("secondary"); root.addWidget(note)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame)
        QScroller.grabGesture(self.scroll.viewport(), QScroller.LeftMouseButtonGesture); root.addWidget(self.scroll, 1)
        recorder.saved.connect(lambda _e: self.isVisible() and self.refresh())

    def refresh(self):
        body = QWidget(); grid = QGridLayout(body); grid.setSpacing(16); grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        entries = sorted(self.rec.entries, key=lambda e: e["time"], reverse=True); self.cards = []
        for i, e in enumerate(entries):
            c = Card(e); c.setCheckable(self.selecting); c.clicked.connect(lambda _=False, c=c: self.tap(c))
            grid.addWidget(c, i // COLUMNS, i % COLUMNS); self.cards.append(c)
        if not entries:
            l = QLabel("No rings yet. Each ring appears here with its recording."); l.setObjectName("secondary"); grid.addWidget(l, 0, 0)
        self.scroll.setWidget(body); self.update_buttons()

    def tap(self, card):
        if self.selecting: self.update_buttons()  # the card toggled itself
        else: self.open(card.entry)

    def toggle_select(self):
        self.selecting = not self.selecting; self.refresh()

    def selected(self):
        return [c.entry for c in self.cards if c.isChecked()]

    def update_buttons(self):
        n = len(self.selected())
        self.select_btn.setText("Done" if self.selecting else "Select")
        self.del_sel_btn.setVisible(self.selecting); self.del_sel_btn.setEnabled(n > 0)
        self.del_sel_btn.setText(f"Delete selected ({n})"); self.del_all_btn.setEnabled(bool(self.rec.entries))

    def delete_selected(self):
        self.rec.delete_many(self.selected()); self.selecting = False; self.refresh()

    def delete_all(self):
        self.rec.delete_many(list(self.rec.entries)); self.selecting = False; self.refresh()

    def open(self, entry):
        p = Player(self.window(), entry); p.deleted.connect(self.remove)

    def remove(self, entry):
        self.rec.delete(entry); self.refresh()

    def showEvent(self, e):
        super().showEvent(e); self.selecting = False; self.refresh()
