"""News for the dashboard: stories from news channels' own RSS feeds (NDTV,
Times of India, BBC, Yahoo News, The Hindu, Hindustan Times; no account needed)
and Google News by region and topic.

Two lists come out of every refresh:
  stories   the channels' top stories, interleaved so every channel shows up
            early, with a summary and a photo (downloaded once into
            news_images/), for the big rotating story
  breaking  the newest stories of all chosen channels, newest first, for the
            ticker; stories from the last BREAKING_MIN minutes are "breaking"
Both are cached so the screen has news right after a restart or offline.
"""
import hashlib, html, json, re, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from PySide6.QtCore import QThread, Signal

# key: (name, badge colour, top-stories feed, latest-stories feed)
CHANNELS = {
    "ndtv": ("NDTV", "#d0021b", "https://feeds.feedburner.com/ndtvnews-top-stories",
             "https://feeds.feedburner.com/ndtvnews-latest"),
    "toi": ("Times of India", "#e21b22", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
            "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
    "bbc": ("BBC News", "#b80000", "https://feeds.bbci.co.uk/news/rss.xml", "https://feeds.bbci.co.uk/news/rss.xml"),
    "hindu": ("The Hindu", "#1d4f91", "https://www.thehindu.com/news/national/feeder/default.rss",
              "https://www.thehindu.com/news/national/feeder/default.rss"),
    "ht": ("Hindustan Times", "#00a0c6", "https://www.hindustantimes.com/feeds/rss/latest/rssfeed.xml",
           "https://www.hindustantimes.com/feeds/rss/latest/rssfeed.xml"),
    "yahoo": ("Yahoo News", "#6001d2", "https://news.yahoo.com/rss/", "https://news.yahoo.com/rss/"),
    "google": ("Google News", "#4285f4", None, None),  # by the regions and topics chosen in Settings
}
DEFAULT_CHANNELS = ["ndtv", "toi", "bbc", "yahoo", "google"]
BROWSER_ONLY = {"yahoo"}  # feeds that refuse anything but a web browser

REGIONS = {  # Google News: key: (label, place searched for, edition)
    "global": ("Global", "", "hl=en-US&gl=US&ceid=US:en"),
    "india": ("India", "India", "hl=en-IN&gl=IN&ceid=IN:en"),
    "karnataka": ("Karnataka", "Karnataka", "hl=en-IN&gl=IN&ceid=IN:en"),
    "bangalore": ("Bangalore", "Bengaluru", "hl=en-IN&gl=IN&ceid=IN:en"),
}
GENRES = {  # Google News: key: (label, search terms; None = the edition's top stories)
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
REFRESH_S = 10 * 60
PER_FEED = 15
MAX_ITEMS = 60
BREAKING_MIN = 90
TICKER_ITEMS = 15
IMAGES = Path(__file__).resolve().parent / "news_images"
MEDIA = "{http://search.yahoo.com/mrss/}"
UA = {"User-Agent": "Mozilla/5.0 (indoor doorbell dashboard)"}
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def google_url(region, genre):
    _, place, edition = REGIONS[region]
    terms = GENRES[genre][1]
    if terms is None and (not place or region == "india"):
        return f"https://news.google.com/rss?{edition}"  # the edition's front page
    q = " ".join(t for t in (place, f"({terms})" if terms else "") if t) + " when:1d"
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&{edition}"


def when(it):
    for tag in ("pubDate", "{http://purl.org/dc/elements/1.1/}date", "updated"):
        text = (it.findtext(tag) or "").strip()
        if not text: continue
        try: return parsedate_to_datetime(text).timestamp()
        except (TypeError, ValueError): pass
        try: return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError: pass
    return 0


def plain(text, limit=240):
    """Feed HTML (summaries carry tags and entities) as one clean line."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    t = " ".join(t.split())
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


def photo(it):
    for el in (it.find(MEDIA + "content"), it.find(MEDIA + "thumbnail"), it.find("enclosure")):
        if el is not None and el.get("url") and el.get("type", "image").startswith("image"):
            url = el.get("url")
            return re.sub(r"ichef\.bbci\.co\.uk/(ace/standard|news)/\d+/", r"ichef.bbci.co.uk/\1/800/", url)  # BBC: a larger size
    m = re.search(r'<img[^>]+src="([^"]+)"', it.findtext("description") or "")
    return m.group(1) if m else ""


def fetch(url, source, headers=UA, **extra):
    root = ET.fromstring(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15).read())
    items = []
    for it in root.iter("item"):
        title = plain(it.findtext("title"), 200)
        src = (it.findtext("source") or "").strip() or source  # Google names the outlet per story
        if src and title.endswith(" - " + src): title = title[: -len(src) - 3]  # Google appends " - Source"
        if title:
            items.append({"title": title, "source": src, "time": when(it), "summary": plain(it.findtext("description")),
                          "image_url": photo(it), "image": "", **extra})
        if len(items) >= PER_FEED: break
    return items


def merge(feeds, limit=MAX_ITEMS):
    """Round-robin across feeds, newest first within each, without repeats."""
    feeds = [sorted(f, key=lambda i: -i["time"]) for f in feeds if f]
    out, seen = [], set()
    for row in range(PER_FEED):
        for f in feeds:
            if row < len(f):
                key = re.sub(r"\W", "", f[row]["title"].lower())[:60]
                if key not in seen: seen.add(key); out.append(f[row])
    return out[:limit]


def ago(ts):
    if not ts: return ""
    m = int((time.time() - ts) // 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago" if m < 1440 else f"{m // 1440} d ago"


def is_breaking(item):
    return bool(item.get("time")) and time.time() - item["time"] < BREAKING_MIN * 60


class News(QThread):
    updated = Signal(list)   # stories for the big rotating story
    breaking = Signal(list)  # newest stories for the ticker
    failed = Signal(str)

    def __init__(self, settings, cache_file):
        super().__init__(); self.settings = settings; self.cache_file = cache_file; self.wake = threading.Event()
        try: self.cached = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError): self.cached = {}

    def choice(self):
        channels = [c for c in CHANNELS if c in self.settings.get("news_channels", DEFAULT_CHANNELS)] or DEFAULT_CHANNELS
        regions = self.settings.get("news_regions") or [self.settings.get("news_region", "india")]  # older single choice
        regions = [r for r in REGIONS if r in regions] or ["india"]
        genres = [g for g in GENRES if g in self.settings.get("news_genres", ["top"])] or ["top"]
        return channels, regions, genres

    def refresh(self): self.wake.set()

    def _jobs(self, channels, regions, genres):
        """(what, url, source, extra) for every feed to read."""
        jobs = []
        for c in channels:
            name, _, top, latest = CHANNELS[c]
            if c == "google":
                for g in genres:
                    for r in regions:
                        jobs.append(("top", google_url(r, g), "", {"genre": GENRES[g][0], "region": REGIONS[r][0]}))
            else:
                jobs.append(("top", top, name, {"channel": c}))
                if latest != top: jobs.append(("latest", latest, name, {"channel": c}))
        return jobs

    def _run_job(self, job):
        what, url, source, extra = job
        headers = BROWSER_UA if extra.get("channel") in BROWSER_ONLY else UA
        try: return what, fetch(url, source, headers, **extra), None
        except Exception as e: return what, [], f"{source or 'Google News'}: {e}"

    def _images(self, items):
        """Downloads the photos of `items` (once; reused while cached) and drops unused ones."""
        IMAGES.mkdir(exist_ok=True)
        def get(item):
            url = item.get("image_url")
            if not url: return
            f = IMAGES / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
            if not f.exists():
                try:
                    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15).read()
                    if len(data) > 2000: f.write_bytes(data)
                except Exception: return
            if f.exists(): item["image"] = str(f)
        with ThreadPoolExecutor(6) as pool: list(pool.map(get, items))
        keep = {Path(i["image"]).name for i in items if i.get("image")}
        for f in IMAGES.glob("*.jpg"):
            if f.name not in keep and time.time() - f.stat().st_mtime > 3600: f.unlink(missing_ok=True)

    def run(self):
        if self.cached.get("key") == list(self.choice()):
            if self.cached.get("items"): self.updated.emit(self.cached["items"])
            if self.cached.get("breaking"): self.breaking.emit(self.cached["breaking"])
        while not self.isInterruptionRequested():
            channels, regions, genres = self.choice()
            jobs = self._jobs(channels, regions, genres)
            with ThreadPoolExecutor(6) as pool: results = list(pool.map(self._run_job, jobs))
            errors = [e for _, _, e in results if e]
            items = merge([f for what, f, _ in results if what == "top"])
            newest = sorted({i["title"]: i for _, f, _ in results for i in f if i.get("time")}.values(),
                            key=lambda i: -i["time"])[:TICKER_ITEMS]
            if items:
                self._images(items)
                self.updated.emit(items); self.breaking.emit(newest)
                try:
                    self.cache_file.write_text(json.dumps({"key": [channels, regions, genres], "items": items,
                                                           "breaking": newest}), encoding="utf-8")
                except OSError: pass
            else:
                self.failed.emit("; ".join(errors) or "no headlines found")
            self.wake.wait(REFRESH_S if items else 60); self.wake.clear()

    def stop(self):
        self.requestInterruption(); self.wake.set(); self.wait(3000)
