"""The visitor screen: the front-door camera full screen, with everything else
floating over it like a video call: who/what at the top, the message at the
bottom left, the countdown ring and the big buttons at the bottom right.

The camera picture fits the height; the bands left and right are a blurred,
darkened copy of it instead of black. Each new frame is scaled once; the
blur is redone every few frames. While ringing, the countdown ring pulses."""
import math, time
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

RED, GREEN = QColor("#e5484d"), QColor("#2fa36b")
BOX = QColor("#ff3b30")  # what the detector found


class RingPage(QWidget):
    stop = Signal()
    talk = Signal()

    def __init__(self, intercom_enabled):
        super().__init__(); self.setObjectName("ring")
        self.intercom_enabled = intercom_enabled  # a function: the trial intercom is switched on
        self.ringing = True; self.remaining = 0; self.total = 1; self.rang_at = time.time()
        self.subtitle = "Bell is playing"; self.note = ""; self.frame = None; self.backdrop = None; self.frames = 0
        self.boxes = []; self.boxes_at = 0.0
        self.call_note = QLabel(self); self.call_note.hide()  # holds the call's status text (read by the window)
        self.stop_btn = QPushButton("■  STOP", self); self.stop_btn.setObjectName("ringStop"); self.stop_btn.clicked.connect(self.stop.emit)
        self.talk_btn = QPushButton("☎  Talk", self); self.talk_btn.setObjectName("ringTalk"); self.talk_btn.clicked.connect(self.talk.emit)
        self.sound_note = ""  # about the door's sound, which plays whenever the picture shows
        self.pulse = QTimer(self); self.pulse.timeout.connect(self.update)

    # ---------- what the window tells it ----------
    def set_mode(self, ringing):
        """Visitor alert (countdown, STOP) or the live door view from the Front door tile (CLOSE)."""
        self.ringing = ringing; self.rang_at = time.time()
        self.stop_btn.setText("■  STOP" if ringing else "×  CLOSE")
        self.talk_btn.setVisible(self.intercom_enabled()); self.place_buttons(); self.update()

    def set_count(self, remaining, total=None):
        self.remaining = remaining
        if total: self.total = max(1, total)
        self.update()

    def set_subtitle(self, text):
        self.subtitle = text; self.update()

    def set_call(self, active, note=""):
        self.talk_btn.setText("☎  End call" if active else "☎  Talk"); self.talk_btn.setProperty("calling", active)
        self.talk_btn.style().unpolish(self.talk_btn); self.talk_btn.style().polish(self.talk_btn)
        self.call_note.setText(note); self.update()

    def set_sound(self, note):
        """A problem with the door's sound, for the message line ("" when fine)."""
        if note != self.sound_note: self.sound_note = note; self.update()

    def show_frame(self, img):
        """A camera frame: fitted to the height, its blurred copy behind it (redone every 8 frames)."""
        w, h = self.width(), self.height()
        if w < 10 or h < 10: return
        self.frame = QPixmap.fromImage(img).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if self.backdrop is None or self.frames % 8 == 0:
            tiny = img.scaled(64, 36, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.backdrop = QPixmap.fromImage(tiny.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        self.frames += 1; self.note = ""; self.update()

    def set_boxes(self, found):
        """What the detector saw (detect.py): drawn as red boxes over the picture until it looks again."""
        self.boxes = found; self.boxes_at = time.monotonic(); self.update()

    def clear_video(self, note):
        self.frame = self.backdrop = None; self.boxes = []; self.note = note; self.update()

    def set_note(self, text):
        self.note = text; self.update()

    # ---------- layout ----------
    def showEvent(self, e):
        super().showEvent(e); self.pulse.start(50); self.place_buttons()

    def hideEvent(self, e):
        super().hideEvent(e); self.pulse.stop()

    def resizeEvent(self, e):
        super().resizeEvent(e); self.frame = self.backdrop = None; self.place_buttons()

    def ring_centre(self):
        return QPointF(self.width() - 120, self.height() - 120)

    def place_buttons(self):
        w, h = self.width(), self.height()
        right = w - 250 if self.ringing else w - 40  # the countdown ring sits at the far right while ringing
        self.stop_btn.setGeometry(int(right - 280), int(h - 156), 280, 104)
        self.talk_btn.setGeometry(int(right - 280 - 24 - 240), int(h - 156), 240, 104)  # left of STOP (when on)

    # ---------- painting ----------
    def _font(self, px, bold=False):
        f = QFont(self.font()); f.setPixelSize(px); f.setBold(bold); return f

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height(); t = time.monotonic()
        # the picture
        if self.frame is not None:
            if self.backdrop is not None:
                p.drawPixmap(0, 0, self.backdrop); p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 150))
            fx, fy = (w - self.frame.width()) // 2, (h - self.frame.height()) // 2
            p.drawPixmap(fx, fy, self.frame)
            if self.boxes and t - self.boxes_at < 1.0:  # a second old at most: no boxes left behind
                self._paint_boxes(p, QRectF(fx, fy, self.frame.width(), self.frame.height()))
        else:
            g = QRadialGradient(QPointF(w / 2, h / 2), w * 0.7); g.setColorAt(0, QColor("#1a2333")); g.setColorAt(1, QColor("#05080e"))
            p.fillRect(QRectF(0, 0, w, h), g)
            p.setPen(QColor(255, 255, 255, 60)); p.setFont(self._font(150))
            p.drawText(QRectF(0, h * 0.22, w, 200), Qt.AlignHCenter | Qt.AlignTop, "◉")
            p.setPen(QColor(255, 255, 255, 170)); p.setFont(self._font(24))
            p.drawText(QRectF(w * 0.2, h * 0.22 + 210, w * 0.6, 80), Qt.AlignHCenter | Qt.TextWordWrap, self.note or "Connecting to the camera…")
        # shades so the text reads on any picture
        for y0, y1, a0, a1 in ((0, 170, 200, 0), (h - 290, h, 0, 225)):
            g = QLinearGradient(0, y0, 0, y1); g.setColorAt(0, QColor(0, 0, 0, a0)); g.setColorAt(1, QColor(0, 0, 0, a1))
            p.fillRect(QRectF(0, y0, w, y1 - y0), g)
        if self.ringing:  # a soft red glow around the edge, breathing
            a = int(70 + 60 * math.sin(t * 4)); pen = QPen(QColor(229, 72, 77, a), 10); p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(5, 5, w - 10, h - 10))
        self._paint_top(p, w, t)
        self._paint_message(p, w, h)
        if self.ringing: self._paint_countdown(p, t)
        p.end()

    def _paint_boxes(self, p, pic):
        """A red box round each person, animal or vehicle, with what it is and how sure the detector is."""
        p.setFont(self._font(18, True)); fm = QFontMetrics(p.font())
        for d in self.boxes:
            x1, y1, x2, y2 = d["box"]
            r = QRectF(pic.x() + x1 * pic.width(), pic.y() + y1 * pic.height(), (x2 - x1) * pic.width(), (y2 - y1) * pic.height())
            p.setBrush(Qt.NoBrush); p.setPen(QPen(BOX, 4)); p.drawRoundedRect(r, 8, 8)
            text = f"{d['label']} {round(d['score'] * 100)}%"
            tag = QRectF(r.x(), max(pic.y(), r.y() - 34), fm.horizontalAdvance(text) + 22, 30)
            p.setPen(Qt.NoPen); p.setBrush(BOX); p.drawRoundedRect(tag, 6, 6)
            p.setPen(QColor("#ffffff")); p.drawText(tag, Qt.AlignCenter, text)

    def _paint_top(self, p, w, t):
        pulse = 0.5 + 0.5 * math.sin(t * 5)
        dot = QColor(RED if self.ringing else GREEN); dot.setAlphaF(0.45 + 0.55 * pulse)
        p.setPen(Qt.NoPen); p.setBrush(dot); p.drawEllipse(QPointF(46, 52), 10 + 3 * pulse, 10 + 3 * pulse)
        p.setPen(QColor("#ffffff")); p.setFont(self._font(26, True))
        title = "VISITOR AT THE DOOR" if self.ringing else "FRONT DOOR · LIVE"
        p.drawText(QRectF(72, 30, w / 2, 44), Qt.AlignLeft | Qt.AlignVCenter, title)
        p.setPen(QColor(255, 255, 255, 180)); p.setFont(self._font(19))
        when = time.strftime("%I:%M %p", time.localtime(self.rang_at)).lstrip("0")
        p.drawText(QRectF(74, 72, w / 2, 30), Qt.AlignLeft | Qt.AlignVCenter,
                   f"Rang at {when}" if self.ringing else "Live camera view")
        # right: REC pill while ringing with a picture, and the clock
        x = w - 40
        p.setFont(self._font(30, True)); clock = time.strftime("%I:%M %p").lstrip("0")
        cw = QFontMetrics(p.font()).horizontalAdvance(clock)
        p.setPen(QColor("#ffffff")); p.drawText(QRectF(x - cw, 32, cw + 4, 44), Qt.AlignRight | Qt.AlignVCenter, clock); x -= cw + 24
        if self.ringing and self.frame is not None:
            p.setPen(Qt.NoPen); p.setBrush(QColor(229, 72, 77, 220)); p.drawRoundedRect(QRectF(x - 104, 36, 104, 36), 18, 18)
            p.setBrush(QColor(255, 255, 255, int(120 + 135 * pulse))); p.drawEllipse(QPointF(x - 84, 54), 7, 7)
            p.setPen(QColor("#ffffff")); p.setFont(self._font(18, True))
            p.drawText(QRectF(x - 70, 36, 64, 36), Qt.AlignCenter, "REC")
        if self.note and self.frame is not None:  # e.g. "Camera stream lost · reconnecting"
            p.setPen(QColor("#ffd400")); p.setFont(self._font(18, True))
            p.drawText(QRectF(74, 104, w / 2, 28), Qt.AlignLeft | Qt.AlignVCenter, self.note)

    def _paint_message(self, p, w, h):
        left = 136  # right of the dashboard's voice button
        width = (w - 250 if self.ringing else w - 40) - 280 - (264 if self.talk_btn.isVisible() else 0) - left - 40
        p.setPen(QColor("#ffffff")); p.setFont(self._font(54, True))
        p.drawText(QRectF(left, h - 210, width, 70), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(p.font()).elidedText("Someone is at the door" if self.ringing else "Front door", Qt.ElideRight, int(width)))
        p.setPen(QColor(255, 255, 255, 200)); p.setFont(self._font(23))
        line = " · ".join(t for t in (self.subtitle if self.ringing else "", self.call_note.text(), self.sound_note) if t)
        p.drawText(QRectF(left + 2, h - 136, width, 40), Qt.AlignLeft | Qt.AlignVCenter, line)

    def _paint_countdown(self, p, t):
        c = self.ring_centre(); r = 78
        pulse = 0.5 + 0.5 * math.sin(t * 4)
        halo = QColor(RED); halo.setAlphaF(0.25 * (1 - pulse)); p.setPen(QPen(halo, 6)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, r + 10 + 14 * pulse, r + 10 + 14 * pulse)
        p.setPen(Qt.NoPen); p.setBrush(QColor(10, 14, 22, 200)); p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(255, 255, 255, 50), 10)); p.drawEllipse(c, r - 8, r - 8)
        frac = max(0.0, min(1.0, self.remaining / self.total))
        p.setPen(QPen(RED, 10, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(c.x() - r + 8, c.y() - r + 8, 2 * (r - 8), 2 * (r - 8)), 90 * 16, int(-360 * 16 * frac))
        p.setPen(QColor("#ffffff")); p.setFont(self._font(44, True))
        p.drawText(QRectF(c.x() - r, c.y() - 34, 2 * r, 50), Qt.AlignCenter, str(self.remaining))
        p.setPen(QColor(255, 255, 255, 160)); p.setFont(self._font(15, True))
        p.drawText(QRectF(c.x() - r, c.y() + 16, 2 * r, 24), Qt.AlignCenter, "SECONDS")
