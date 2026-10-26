"""The news screen, drawn like a TV news channel: one big story at a time
(its photo, the channel's badge, headline and summary over a blurred copy of
the photo) and a ticker of the newest headlines along the bottom, under a red
BREAKING label while any of them is fresh (else LATEST).

NewsPainter only paints; Scenic in app.py owns the timers, the slide
animation and the swipes. Pictures are scaled once per size and cached; the
ticker text is rendered once into a strip that is then only shifted."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from news import CHANNELS, ago, is_breaking

TICKER_H = 72
MARKET_H = 48      # the market band, just above the ticker
BOTTOM_H = TICKER_H + MARKET_H
LABEL_W = 250
FLASH_MIN = 20  # a story this fresh, new since the last refresh, is flashed big
STORY_LEFT = 230   # right of the dashboard's shortcut rail
STORY_TOP = 225    # below the big clock
PHOTO_W, PHOTO_H = 640, 360
ARROW_R = 30
RED = QColor("#d0021b")


def badge_color(item):
    for name, color, _, _ in CHANNELS.values():
        if item.get("source") == name: return QColor(color)
    return QColor("#4285f4")


class NewsPainter:
    def __init__(self):
        self.cache = {}; self.strip = None; self.strip_key = None

    def _font(self, base, px, bold=False):
        f = QFont(base); f.setPixelSize(px); f.setBold(bold); return f

    def _cached(self, key, make):
        if key not in self.cache:
            if len(self.cache) > 12: self.cache.clear()
            self.cache[key] = make()
        return self.cache[key]

    # ---------- the big story ----------
    def backdrop(self, item, w, h):
        """The story's photo blurred (scaled down, then up) and darkened; a dark gradient without one."""
        def make():
            pm = QPixmap(w, h); pm.fill(QColor("#070b14")); p = QPainter(pm)
            img = QImage(item["image"]) if item.get("image") else QImage()
            if not img.isNull():
                tiny = img.scaled(48, 27, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                p.drawImage(QRectF(0, 0, w, h), tiny.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, QColor(4, 7, 14, 245)); g.setColorAt(0.55, QColor(4, 7, 14, 215)); g.setColorAt(1, QColor(4, 7, 14, 165))
            p.fillRect(QRectF(0, 0, w, h), g); p.end(); return pm
        return self._cached(("bg", item.get("image"), item.get("source"), w, h), make)

    def photo(self, item, base_font):
        """The story's photo cropped to PHOTO_W x PHOTO_H, or a card in the channel's colour."""
        def make():
            pm = QPixmap(PHOTO_W, PHOTO_H); pm.fill(Qt.transparent); p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
            clip = QPainterPath(); clip.addRoundedRect(QRectF(0, 0, PHOTO_W, PHOTO_H), 22, 22); p.setClipPath(clip)
            img = QImage(item["image"]) if item.get("image") else QImage()
            if img.isNull():  # e.g. NDTV, whose image server refuses other sites
                c = badge_color(item); g = QLinearGradient(0, 0, PHOTO_W, PHOTO_H)
                g.setColorAt(0, c.darker(120)); g.setColorAt(1, c.darker(260)); p.fillRect(QRectF(0, 0, PHOTO_W, PHOTO_H), g)
                p.setPen(QColor(255, 255, 255, 235)); p.setFont(self._font(base_font, 64, True))
                p.drawText(QRectF(0, 0, PHOTO_W, PHOTO_H), Qt.AlignCenter, item.get("source", ""))
            else:
                s = img.scaled(PHOTO_W, PHOTO_H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                p.drawImage(0, 0, s, (s.width() - PHOTO_W) // 2, (s.height() - PHOTO_H) // 2, PHOTO_W, PHOTO_H)
            p.end(); return pm
        return self._cached(("photo", item.get("image"), item.get("source")), make)

    def paint_story(self, p, item, w, h, dx, base_font, index, total):
        """One story, shifted dx pixels sideways (for the slide)."""
        bottom = h - BOTTOM_H - 60
        x = STORY_LEFT + dx
        p.drawPixmap(int(x), STORY_TOP, self.photo(item, base_font))
        tx = x + PHOTO_W + 44; tw = w - 100 - (STORY_LEFT + PHOTO_W + 44)
        # badge: channel, age, BREAKING
        p.setFont(self._font(base_font, 17, True)); fm = p.fontMetrics()
        name = item.get("source", "").upper(); bw = fm.horizontalAdvance(name) + 28
        p.setPen(Qt.NoPen); p.setBrush(badge_color(item)); p.drawRoundedRect(QRectF(tx, STORY_TOP, bw, 34), 8, 8)
        p.setPen(QColor("#ffffff")); p.drawText(QRectF(tx, STORY_TOP, bw, 34), Qt.AlignCenter, name)
        bx = tx + bw + 14
        if is_breaking(item):
            p.setBrush(RED); p.setPen(Qt.NoPen); p.drawRoundedRect(QRectF(bx, STORY_TOP, 130, 34), 8, 8)
            p.setPen(QColor("#ffffff")); p.drawText(QRectF(bx, STORY_TOP, 130, 34), Qt.AlignCenter, "BREAKING"); bx += 144
        p.setFont(self._font(base_font, 17)); p.setPen(QColor(255, 255, 255, 170))
        tag = "   ·   ".join(t for t in (item.get("region", ""), item.get("genre", ""), ago(item.get("time", 0))) if t)
        p.drawText(QRectF(bx, STORY_TOP, tx + tw - bx, 34), Qt.AlignLeft | Qt.AlignVCenter, tag)
        # headline (up to 4 lines) and summary below it
        p.setFont(self._font(base_font, 40, True)); p.setPen(QColor("#ffffff"))
        head = QRectF(tx, STORY_TOP + 56, tw, 4 * 50)
        used = p.boundingRect(head, Qt.TextWordWrap, item["title"])
        p.drawText(head, Qt.TextWordWrap, item["title"])
        sy = STORY_TOP + 56 + min(used.height(), head.height()) + 18
        if item.get("summary") and item["summary"] != item["title"]:
            p.setFont(self._font(base_font, 21)); p.setPen(QColor(255, 255, 255, 200))
            p.drawText(QRectF(tx, sy, tw, max(0, bottom - sy)), Qt.TextWordWrap, item["summary"])
        # position, under the photo
        p.setFont(self._font(base_font, 15)); p.setPen(QColor(255, 255, 255, 140))
        p.drawText(QRectF(x, STORY_TOP + PHOTO_H + 14, PHOTO_W, 24), Qt.AlignLeft,
                   f"{index + 1} / {total}    ·    swipe or tap ‹ › for more")

    def paint_arrows(self, p, w, base_font=None):
        cy = STORY_TOP + PHOTO_H / 2
        p.setFont(self._font(base_font or p.font(), 44, True))
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 40))
        for cx, glyph in ((STORY_LEFT - 44, "‹"), (w - 56, "›")):
            p.drawEllipse(QPointF(cx, cy), ARROW_R, ARROW_R)
            p.setPen(QColor(255, 255, 255, 220)); p.drawText(QRectF(cx - ARROW_R, cy - ARROW_R - 4, 2 * ARROW_R, 2 * ARROW_R), Qt.AlignCenter, glyph)
            p.setPen(Qt.NoPen)

    def arrow_at(self, x, y, w):
        """-1 / +1 when (x, y) is on the left / right arrow, else 0."""
        cy = STORY_TOP + PHOTO_H / 2
        for cx, d in ((STORY_LEFT - 44, -1), (w - 56, 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= (ARROW_R + 14) ** 2: return d
        return 0

    # ---------- ticker ----------
    def ticker_strip(self, items, base_font):
        """All ticker headlines rendered once into one strip (white channel pill, bold
        headline, separator); returns (pixmap, its width). Re-rendered only when they change."""
        key = tuple(i["title"] for i in items)
        if key != self.strip_key or self.strip is None:
            f_src, f_txt = self._font(base_font, 19, True), self._font(base_font, 28, True)
            m_src, m_txt = QFontMetrics(f_src), QFontMetrics(f_txt)
            parts = []; width = 0
            for i in items:
                name = i.get("source", "").upper(); pill = m_src.horizontalAdvance(name) + 24
                parts.append(("pill", width, name, badge_color(i), pill)); width += pill + 16
                parts.append(("text", width, i["title"], None, 0)); width += m_txt.horizontalAdvance(i["title"])
                parts.append(("sep", width, "", None, 0)); width += 70
            pm = QPixmap(max(1, width), TICKER_H); pm.fill(Qt.transparent); p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
            for kind, x, text, color, pw in parts:
                if kind == "pill":
                    p.setPen(Qt.NoPen); p.setBrush(QColor("#ffffff")); p.drawRoundedRect(QRectF(x, 18, pw, TICKER_H - 36), 7, 7)
                    p.setFont(f_src); p.setPen(color.darker(110)); p.drawText(QRectF(x, 18, pw, TICKER_H - 36), Qt.AlignCenter, text)
                elif kind == "text":
                    p.setFont(f_txt); p.setPen(QColor("#ffffff"))
                    p.drawText(QRectF(x, 0, width - x, TICKER_H), Qt.AlignLeft | Qt.AlignVCenter, text)
                else:  # a small diamond between headlines
                    cx, cy = x + 35, TICKER_H / 2; p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 170))
                    p.drawPolygon([QPointF(cx, cy - 7), QPointF(cx + 7, cy), QPointF(cx, cy + 7), QPointF(cx - 7, cy)])
            p.end(); self.strip, self.strip_key = pm, key
        return self.strip, self.strip.width()

    def paint_ticker(self, p, items, w, h, offset, base_font, t):
        """The band along the bottom; t (seconds) makes the BREAKING dot pulse."""
        y = h - TICKER_H
        breaking = any(is_breaking(i) for i in items)
        g = QLinearGradient(0, y, 0, y + TICKER_H)
        if breaking: g.setColorAt(0, QColor("#c8001e")); g.setColorAt(1, QColor("#7d0012"))
        else: g.setColorAt(0, QColor("#16233d")); g.setColorAt(1, QColor("#0a1222"))
        p.fillRect(QRectF(0, y, w, TICKER_H), g)
        p.fillRect(QRectF(0, y, w, 3), QColor("#ffd400") if breaking else QColor(255, 255, 255, 60))
        if items:
            strip, sw = self.ticker_strip(items, base_font)
            p.save(); p.setClipRect(QRectF(LABEL_W, y, w - LABEL_W, TICKER_H))
            x = LABEL_W + 20 - (offset % sw)
            while x < w: p.drawPixmap(int(x), y, strip); x += sw
            p.restore()
        # the label: white with red letters and a pulsing dot while breaking
        p.fillRect(QRectF(0, y, LABEL_W, TICKER_H), QColor("#ffffff") if breaking else QColor("#2a3a5c"))
        p.setPen(Qt.NoPen)
        if breaking:
            pulse = 0.5 + 0.5 * math.sin(t * 6.0)
            c = QColor(RED); c.setAlphaF(0.35 + 0.65 * pulse); p.setBrush(c)
            p.drawEllipse(QPointF(30, y + TICKER_H / 2), 9 + 3 * pulse, 9 + 3 * pulse)
        p.setPen(RED if breaking else QColor("#ffffff")); p.setFont(self._font(base_font, 26, True))
        p.drawText(QRectF(48 if breaking else 0, y, LABEL_W - (48 if breaking else 0), TICKER_H), Qt.AlignCenter,
                   "BREAKING" if breaking else "LATEST")

    # ---------- the big flash for a new breaking story ----------
    def paint_flash(self, p, item, w, base_font, alpha, t):
        """A red banner over the story area: BREAKING NEWS, the channel and the headline."""
        x, y, bw, bh = 150, STORY_TOP - 10, w - 150 - 30, 200
        p.save(); p.setOpacity(alpha)
        g = QLinearGradient(x, y, x, y + bh); g.setColorAt(0, QColor("#d8001f")); g.setColorAt(1, QColor("#8a0014"))
        p.setPen(Qt.NoPen); p.setBrush(g); p.drawRoundedRect(QRectF(x, y, bw, bh), 18, 18)
        pulse = 0.5 + 0.5 * math.sin(t * 6.0)
        p.setBrush(QColor(255, 212, 0, int(120 + 135 * pulse))); p.drawRoundedRect(QRectF(x, y, bw, 8), 4, 4)
        p.setBrush(QColor("#ffffff")); p.drawRoundedRect(QRectF(x + 28, y + 30, 300, 48), 10, 10)
        p.setPen(RED); p.setFont(self._font(base_font, 28, True))
        p.drawText(QRectF(x + 28, y + 30, 300, 48), Qt.AlignCenter, "BREAKING NEWS")
        p.setPen(QColor(255, 255, 255, 230)); p.setFont(self._font(base_font, 22, True))
        p.drawText(QRectF(x + 348, y + 30, bw - 380, 48), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{item.get('source', '')}   ·   {ago(item.get('time', 0))}")
        p.setPen(QColor("#ffffff")); p.setFont(self._font(base_font, 40, True))
        p.drawText(QRectF(x + 28, y + 90, bw - 56, bh - 100), Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, item["title"])
        p.restore()

    # ---------- market band ----------
    def paint_market(self, p, data, note, w, h, base_font):
        """NIFTY 50 / SENSEX and the NIFTY's top gainers and losers, above the ticker."""
        y = h - BOTTOM_H; GREEN, REDM, DIM = QColor("#2ed47a"), QColor("#ff5a5f"), QColor(255, 255, 255, 150)
        p.fillRect(QRectF(0, y, w, MARKET_H), QColor(6, 12, 24, 235))
        p.fillRect(QRectF(0, y, w, 1), QColor(255, 255, 255, 40))
        f_lab, f_val = self._font(base_font, 15, True), self._font(base_font, 19, True)
        if not data:
            p.setFont(f_lab); p.setPen(DIM)
            p.drawText(QRectF(24, y, w - 48, MARKET_H), Qt.AlignLeft | Qt.AlignVCenter,
                       "MARKETS   ·   " + (note or "loading NIFTY, SENSEX and the top movers…"))
            return
        x = 24
        def put(text, font, color, gap=10):
            nonlocal x
            p.setFont(font); p.setPen(color); adv = QFontMetrics(font).horizontalAdvance(text)
            p.drawText(QRectF(x, y, adv + 4, MARKET_H), Qt.AlignLeft | Qt.AlignVCenter, text); x += adv + gap
        def arrow(v): return "▲" if v >= 0 else "▼"
        for i in data.get("indices", []):
            put(i["name"], f_lab, DIM)
            put(f"{i['ltp']:,.2f}", f_val, QColor("#ffffff"))
            c = GREEN if i["change"] >= 0 else REDM
            put(f"{arrow(i['change'])} {abs(i['pct']):.2f}%", f_val, c, 34)
        # status at the right; movers fill the room between
        status = "● LIVE" if data.get("open") else f"CLOSED · {data.get('session', '')} close".replace("  ", " ")
        sw = QFontMetrics(f_lab).horizontalAdvance(status)
        p.setFont(f_lab); p.setPen(GREEN if data.get("open") else DIM)
        p.drawText(QRectF(w - sw - 24, y, sw + 4, MARKET_H), Qt.AlignLeft | Qt.AlignVCenter, status)
        # gainers and losers share the room left: add one of each in turn while they fit
        f_mov, f_tit = self._font(base_font, 17, True), self._font(base_font, 13, True)
        m_mov, m_tit = QFontMetrics(f_mov), QFontMetrics(f_tit)
        groups = [("GAINERS", [f"{m['symbol']} {m['pct']:+.1f}%" for m in data.get("gainers", [])], GREEN),
                  ("LOSERS", [f"{m['symbol']} {m['pct']:+.1f}%" for m in data.get("losers", [])], REDM)]
        groups = [g for g in groups if g[1]]
        room = w - sw - 60 - x
        used = sum(m_tit.horizontalAdvance(t) + 10 + 30 for t, _, _ in groups)  # titles and the gap between groups
        shown = [0] * len(groups)
        for k in range(max((len(g[1]) for g in groups), default=0)):
            for gi, (_, items, _) in enumerate(groups):
                if k < len(items) and shown[gi] == k:
                    width = m_mov.horizontalAdvance(items[k]) + 14
                    if used + width <= room: used += width; shown[gi] += 1
        for (title, items, color), n in zip(groups, shown):
            if not n: continue
            put(title, f_tit, DIM, 10)
            for t in items[:n]: put(t, f_mov, color, 14)
            x += 16
