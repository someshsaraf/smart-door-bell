"""Festival wallpapers painted in code, used when assets/festivals/<key>/ has no
pictures of its own. Dark, calm scenes so the clock and news stay readable;
the same seed gives the same picture at every size."""
import math, random
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap, QRadialGradient


def paint(key, w, h):
    pm = QPixmap(w, h); pm.fill(Qt.black)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
    {"diwali": _diwali, "christmas": _christmas, "new_year": _new_year}[key](p, w, h, random.Random(key))
    p.end()
    return pm


def _sky(p, w, h, stops):
    g = QLinearGradient(0, 0, 0, h)
    for at, color in stops: g.setColorAt(at, QColor(color))
    p.fillRect(QRectF(0, 0, w, h), g)


def _glow(p, x, y, r, color, alpha=200):
    c = QColor(color); g = QRadialGradient(QPointF(x, y), r)
    c.setAlpha(alpha); g.setColorAt(0, c); c.setAlpha(alpha // 3); g.setColorAt(0.35, c); c.setAlpha(0); g.setColorAt(1, c)
    p.setBrush(g); p.drawEllipse(QPointF(x, y), r, r)


def _stars(p, w, h, rnd, count, top):
    for _ in range(count):
        p.setBrush(QColor(255, 255, 255, rnd.randint(60, 200)))
        p.drawEllipse(QPointF(rnd.uniform(0, w), rnd.uniform(0, h * top)), *(2 * [rnd.uniform(0.6, 1.8)]))


def _diwali(p, w, h, rnd):
    _sky(p, w, h, [(0, "#14040a"), (0.55, "#3a0b10"), (1, "#5a1a0c")])
    # faint mandala on the right
    cx, cy = w * 0.78, h * 0.42
    for ring, (n, r) in enumerate(((12, h * 0.34), (12, h * 0.25), (8, h * 0.15))):
        p.setBrush(QColor(255, 180, 80, 14 + ring * 6))
        for k in range(n):
            a = 2 * math.pi * k / n + ring * 0.26
            p.save(); p.translate(cx, cy); p.rotate(math.degrees(a))
            path = QPainterPath(QPointF(0, 0)); path.quadTo(r * 0.28, -r * 0.5, 0, -r); path.quadTo(-r * 0.28, -r * 0.5, 0, 0)
            p.drawPath(path); p.restore()
    _glow(p, cx, cy, h * 0.12, "#ffb43a", 70)
    # two strings of warm lights across the top
    for sag, y0, colors in ((h * 0.10, h * 0.02, ("#ffc24a", "#ff8a1e")), (h * 0.08, h * 0.12, ("#ff5c8a", "#ffd54a"))):
        n = 34
        for k in range(n + 1):
            t = k / n; x = t * w; y = y0 + sag * 4 * t * (1 - t)
            _glow(p, x, y, 14, colors[k % 2], 170)
            p.setBrush(QColor(255, 240, 200)); p.drawEllipse(QPointF(x, y), 2.6, 2.6)
    # a row of diyas on a ledge
    ledge = h * 0.88
    p.setBrush(QColor("#2a0c06")); p.drawRect(QRectF(0, ledge, w, h - ledge))
    p.setBrush(QColor(255, 150, 60, 40)); p.drawRect(QRectF(0, ledge, w, 3))
    n = 9
    for k in range(n):
        x = (k + 0.5) * w / n; s = 1.6 + 0.2 * math.sin(k * 1.7)
        _glow(p, x, ledge - 36 * s, 70 * s, "#ff9a2a", 120)
        bowl = QPainterPath(QPointF(x - 30 * s, ledge - 14 * s))
        bowl.cubicTo(x - 26 * s, ledge + 4 * s, x + 26 * s, ledge + 4 * s, x + 30 * s, ledge - 14 * s)
        bowl.quadTo(x + 34 * s, ledge - 18 * s, x + 40 * s, ledge - 20 * s)  # spout
        bowl.lineTo(x - 30 * s, ledge - 14 * s)
        g = QLinearGradient(0, ledge - 18 * s, 0, ledge + 4 * s); g.setColorAt(0, QColor("#c0612a")); g.setColorAt(1, QColor("#5a2410"))
        p.setBrush(g); p.drawPath(bowl)
        p.setBrush(QColor("#ffcf6a")); p.drawEllipse(QRectF(x - 30 * s, ledge - 18 * s, 60 * s, 8 * s))
        fx, fy = x + 34 * s, ledge - 22 * s  # flame on the spout
        flame = QPainterPath(QPointF(fx, fy)); flame.cubicTo(fx - 10 * s, fy - 8 * s, fx - 2 * s, fy - 20 * s, fx, fy - 30 * s)
        flame.cubicTo(fx + 2 * s, fy - 20 * s, fx + 10 * s, fy - 8 * s, fx, fy)
        g = QRadialGradient(QPointF(fx, fy - 8 * s), 22 * s); g.setColorAt(0, QColor("#fff6c8")); g.setColorAt(0.5, QColor("#ffb43a")); g.setColorAt(1, QColor("#ff6a1a"))
        _glow(p, fx, fy - 12 * s, 40 * s, "#ffb43a", 150)
        p.setBrush(g); p.drawPath(flame)


def _pine(p, x, base, height, color, snow=True):
    for i in range(4):
        top = base - height * (0.35 + 0.22 * i); wid = height * (0.42 - 0.08 * i); y = base - height * (0.22 * i)
        path = QPainterPath(QPointF(x, top)); path.lineTo(x + wid, y); path.lineTo(x - wid, y); path.closeSubpath()
        p.setBrush(QColor(color)); p.drawPath(path)
        if snow:
            p.setBrush(QColor(235, 245, 255, 210))
            cap = QPainterPath(QPointF(x, top)); cap.lineTo(x + wid * 0.25, top + (y - top) * 0.25); cap.lineTo(x - wid * 0.25, top + (y - top) * 0.25)
            p.drawPath(cap)
    p.setBrush(QColor("#3a2412")); p.drawRect(QRectF(x - height * 0.04, base, height * 0.08, height * 0.06))


def _christmas(p, w, h, rnd):
    _sky(p, w, h, [(0, "#050b1c"), (0.6, "#0c2038"), (1, "#123a3a")])
    _stars(p, w, h, rnd, 160, 0.6)
    _glow(p, w * 0.62, h * 0.16, 90, "#e8f0ff", 60)
    p.setBrush(QColor("#f2f6ff")); p.drawEllipse(QPointF(w * 0.62, h * 0.16), 34, 34)
    # snowy hills
    for y0, color in ((0.80, "#c9d8ea"), (0.86, "#e6eef8")):
        path = QPainterPath(QPointF(0, h)); path.lineTo(0, h * y0)
        for k in range(7):
            x1 = w * (k + 0.5) / 6; x2 = w * (k + 1) / 6
            path.quadTo(x1, h * (y0 - 0.05 * (1 + (k % 2))), x2, h * y0)
        path.lineTo(w, h); path.closeSubpath(); p.setBrush(QColor(color)); p.drawPath(path)
    for x, s in ((0.04, 0.35), (0.09, 0.27), (0.48, 0.22), (0.55, 0.3), (0.70, 0.24), (0.97, 0.33)):
        _pine(p, w * x, h * 0.84, h * s, "#0f3a26")
    # the decorated tree
    tx, base, th = w * 0.84, h * 0.86, h * 0.62
    _pine(p, tx, base, th, "#145233", snow=False)
    colors = ["#ff3b3b", "#ffd54a", "#3bb2ff", "#ff7ad9", "#ffffff"]
    for i in range(46):
        t = rnd.uniform(0.12, 0.98); y = base - th * (1 - t) * 0.98; half = th * 0.42 * t * 0.9
        x = tx + rnd.uniform(-half, half); c = colors[i % len(colors)]
        _glow(p, x, y, 12, c, 150); p.setBrush(QColor(c)); p.drawEllipse(QPointF(x, y), 4, 4)
    sx, sy = tx, base - th * 1.0  # star on top
    _glow(p, sx, sy, 60, "#ffd54a", 170)
    star = QPainterPath()
    for k in range(10):
        r = 22 if k % 2 == 0 else 9; a = -math.pi / 2 + k * math.pi / 5
        (star.moveTo if k == 0 else star.lineTo)(QPointF(sx + r * math.cos(a), sy + r * math.sin(a)))
    star.closeSubpath(); p.setBrush(QColor("#ffe27a")); p.drawPath(star)


def _new_year(p, w, h, rnd):
    _sky(p, w, h, [(0, "#04061a"), (0.65, "#0d1640"), (1, "#1c1650")])
    _stars(p, w, h, rnd, 120, 0.7)
    # fireworks
    for cx, cy, r, color in ((0.62, 0.22, 0.16, "#ffd54a"), (0.82, 0.34, 0.12, "#ff3dcb"), (0.46, 0.40, 0.09, "#2ee6ff"),
                             (0.93, 0.14, 0.08, "#9dff6e"), (0.72, 0.10, 0.06, "#ffffff")):
        cx, cy, r = w * cx, h * cy, h * r * 1.6
        _glow(p, cx, cy, r * 0.9, color, 60)
        n = 28
        for k in range(n):
            a = 2 * math.pi * k / n + rnd.uniform(-0.05, 0.05); rr = r * rnd.uniform(0.8, 1.0)
            for j in range(6):
                f = 0.3 + 0.7 * j / 5; c = QColor(color); c.setAlpha(int(60 + 190 * f))
                p.setBrush(c); p.drawEllipse(QPointF(cx + rr * f * math.cos(a), cy + rr * f * math.sin(a) + 6 * f * f), 1.2 + 1.6 * f, 1.2 + 1.6 * f)
    # city skyline with lit windows
    x = 0.0
    while x < w:
        bw = rnd.uniform(40, 110); bh = h * rnd.uniform(0.12, 0.36); top = h - bh
        p.setBrush(QColor("#070914")); p.drawRect(QRectF(x, top, bw + 1, bh))
        for wy in range(int(top + 10), int(h - 8), 16):
            for wx in range(int(x + 8), int(x + bw - 8), 14):
                if rnd.random() < 0.35:
                    p.setBrush(QColor(255, 214, 120, rnd.randint(90, 220))); p.drawRect(QRectF(wx, wy, 6, 8))
        x += bw
    g = QLinearGradient(0, h * 0.62, 0, h); g.setColorAt(0, QColor(255, 120, 200, 0)); g.setColorAt(1, QColor(255, 120, 200, 40))
    p.fillRect(QRectF(0, h * 0.62, w, h * 0.38), g)
