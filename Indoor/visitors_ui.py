"""Visitors page of the dashboard: every ring and parcel event, newest first,
with the visitor's face (or the snapshot) and the time; a tap shows the photo."""
import time
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QScroller,
                               QVBoxLayout, QWidget)
from visitors import LOG_DIR

KINDS = {"ring": "Rang the bell", "parcel": "Parcel delivered", "parcel_taken": "Parcel picked up"}
COLUMNS = 5


def when(t):
    lt, today = time.localtime(t), time.localtime()
    clock = time.strftime("%I:%M %p", lt).lstrip("0")
    days = (time.mktime(today[:3] + (0, 0, 0, 0, 0, -1)) - time.mktime(lt[:3] + (0, 0, 0, 0, 0, -1))) // 86400
    return f"Today {clock}" if days == 0 else f"Yesterday {clock}" if days == 1 else time.strftime("%a %d %b · ", lt) + clock


class Card(QPushButton):
    def __init__(self, entry):
        super().__init__(); self.setObjectName("visitorCard"); self.entry = entry; self.setFixedSize(300, 320)
        lay = QVBoxLayout(self); lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(6)
        pic = QLabel(); pic.setObjectName("visitorPic"); pic.setAlignment(Qt.AlignCenter); pic.setFixedSize(280, 230)
        path = entry.get("face") or entry.get("photo")
        pm = QPixmap(str(LOG_DIR / path)) if path else QPixmap()
        if pm.isNull(): pic.setText("No picture")
        else: pic.setPixmap(pm.scaled(pic.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(pic)
        for text, obj in ((KINDS.get(entry["kind"], entry["kind"]), "visitorKind"), (when(entry["time"]), "visitorTime")):
            l = QLabel(text); l.setObjectName(obj); l.setAlignment(Qt.AlignCenter); lay.addWidget(l)
        for w in self.findChildren(QLabel): w.setAttribute(Qt.WA_TransparentForMouseEvents)


class Photo(QLabel):
    """Full-screen photo; a tap closes it."""
    def __init__(self, parent, path):
        super().__init__(parent); self.setObjectName("visitorPhoto"); self.setAlignment(Qt.AlignCenter)
        self.setGeometry(parent.rect()); pm = QPixmap(str(path))
        self.setPixmap(pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)); self.show(); self.raise_()
    def mousePressEvent(self, e): self.deleteLater()


class VisitorsPage(QFrame):
    back = Signal()

    def __init__(self, log):
        super().__init__(); self.setObjectName("settings"); self.log = log
        root = QVBoxLayout(self); root.setContentsMargins(24, 20, 24, 20); root.setSpacing(12)
        head = QHBoxLayout(); t = QLabel("Visitors"); t.setObjectName("pageTitle"); head.addWidget(t); head.addStretch()
        self.porch = QLabel(""); self.porch.setObjectName("secondary"); head.addWidget(self.porch); head.addSpacing(24)
        b = QPushButton("‹  Back"); b.setMinimumHeight(56); b.setFixedWidth(160); b.clicked.connect(self.back.emit); head.addWidget(b)
        root.addLayout(head)
        self.note = QLabel(f"Rings and parcels of the last 30 days, kept only on this Pi."); self.note.setObjectName("secondary")
        root.addWidget(self.note)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.NoFrame)
        QScroller.grabGesture(self.scroll.viewport(), QScroller.LeftMouseButtonGesture)
        root.addWidget(self.scroll, 1)
        log.saved.connect(lambda _e: self.isVisible() and self.refresh())

    def set_porch(self, text):
        self.porch.setText(text)

    def refresh(self):
        body = QWidget(); grid = QGridLayout(body); grid.setSpacing(16); grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        entries = sorted(self.log.entries, key=lambda e: e["time"], reverse=True)
        for i, e in enumerate(entries):
            c = Card(e); c.clicked.connect(lambda _=False, e=e: self.open(e)); grid.addWidget(c, i // COLUMNS, i % COLUMNS)
        if not entries:
            l = QLabel("No visitors yet. Rings are logged here with a snapshot."); l.setObjectName("secondary"); grid.addWidget(l, 0, 0)
        self.scroll.setWidget(body)

    def open(self, e):
        if e.get("photo"): Photo(self.window(), LOG_DIR / e["photo"])

    def showEvent(self, e):
        super().showEvent(e); self.refresh()
