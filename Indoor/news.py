"""Headlines from Google News RSS (no account or API key needed).

Each selected region picks the edition and, for Karnataka/Bangalore, a place
search; every region x genre pair is one feed. Feeds are interleaved so every
region and genre shows up early, duplicates are dropped, and the result is
cached so the screen has news immediately after a restart or while offline.
"""
import json, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from PySide6.QtCore import QThread, Signal

REGIONS = {  # key: (label, place searched for, edition)
    "global": ("Global", "", "hl=en-US&gl=US&ceid=US:en"),
    "india": ("India", "India", "hl=en-IN&gl=IN&ceid=IN:en"),
    "karnataka": ("Karnataka", "Karnataka", "hl=en-IN&gl=IN&ceid=IN:en"),
    "bangalore": ("Bangalore", "Bengaluru", "hl=en-IN&gl=IN&ceid=IN:en"),
}
GENRES = {  # key: (label, search terms; None = the edition's top stories)
    "top": ("Top stories", None),
    "politics": ("Politics", "politics"),
    "business": ("Business", "business OR economy"),
    "technology": ("Technology", "technology"),
    "sports": ("Sports", "sports"),
    "automobiles": ("Automobiles", "automobile OR cars OR EV"),
    "entertainment": ("Entertainment", "entertainment OR movies"),
    "science": ("Science", "science"),
    "health": ("Health", "health"),
}
REFRESH_S = 15 * 60
PER_FEED = 15
MAX_ITEMS = 60

def feed_url(region, genre):
    _, place, edition = REGIONS[region]
    terms = GENRES[genre][1]
    if terms is None and not place:
        return f"https://news.google.com/rss?{edition}"
    if terms is None and region == "india":
        return f"https://news.google.com/rss?{edition}"  # the Indian edition's front page
    q = " ".join(t for t in (place, f"({terms})" if terms else "") if t) + " when:1d"
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&{edition}"

def fetch(region, genre):
    req = urllib.request.Request(feed_url(region, genre), headers={"User-Agent": "Mozilla/5.0 (indoor doorbell dashboard)"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=15).read())
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(" - " + source): title = title[: -len(source) - 3]  # Google appends " - Source"
        if len(title) >= 100 and title[-1].isalnum(): title += "…"  # Google cuts long titles mid-word
        try: ts = parsedate_to_datetime(it.findtext("pubDate")).timestamp()
        except (TypeError, ValueError): ts = 0
        if title: items.append({"title": title, "source": source, "time": ts, "genre": GENRES[genre][0], "region": REGIONS[region][0]})
        if len(items) >= PER_FEED: break
    return items

def merge(feeds):
    """Round-robin across feeds (regions x genres), newest first within each, without repeats."""
    feeds = [sorted(f, key=lambda i: -i["time"]) for f in feeds if f]
    out, seen = [], set()
    for row in range(PER_FEED):
        for f in feeds:
            if row < len(f):
                key = f[row]["title"].lower()[:80]
                if key not in seen: seen.add(key); out.append(f[row])
    return out[:MAX_ITEMS]

def ago(ts):
    if not ts: return ""
    m = int((time.time() - ts) // 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago" if m < 1440 else f"{m // 1440} d ago"

class News(QThread):
    updated = Signal(list)  # merged headline dicts
    failed = Signal(str)

    def __init__(self, settings, cache_file):
        super().__init__(); self.settings = settings; self.cache_file = cache_file; self.wake = threading.Event()
        try: self.cached = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError): self.cached = {}

    def choice(self):
        regions = self.settings.get("news_regions") or [self.settings.get("news_region", "india")]  # older single choice
        regions = [r for r in REGIONS if r in regions] or ["india"]
        genres = [g for g in GENRES if g in self.settings.get("news_genres", ["top"])] or ["top"]
        return regions, genres

    def refresh(self): self.wake.set()

    def _fetch(self, pair):
        try: return fetch(*pair), None
        except Exception as e: return [], f"{REGIONS[pair[0]][0]} {GENRES[pair[1]][0]}: {e}"

    def run(self):
        key = list(self.choice())
        if self.cached.get("key") == key and self.cached.get("items"): self.updated.emit(self.cached["items"])
        while not self.isInterruptionRequested():
            regions, genres = self.choice(); key = [regions, genres]
            # genre-major order so the round-robin alternates regions within each genre
            pairs = [(r, g) for g in genres for r in regions]
            with ThreadPoolExecutor(6) as pool: results = list(pool.map(self._fetch, pairs))
            items = merge([f for f, _ in results]); errors = [e for _, e in results if e]
            if items:
                self.updated.emit(items)
                try: self.cache_file.write_text(json.dumps({"key": key, "items": items}), encoding="utf-8")
                except OSError: pass
            else:
                self.failed.emit("; ".join(errors) or "no headlines found")
            self.wake.wait(REFRESH_S if items else 60); self.wake.clear()

    def stop(self):
        self.requestInterruption(); self.wake.set(); self.wait(3000)
