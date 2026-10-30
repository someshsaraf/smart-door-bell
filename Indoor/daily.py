"""What happened at the door, told to the phones (ntfy and ring alerts, see
Window.alert_phones), each part switched in Settings > Alerts:

- The daily summary, at the chosen hour ("summary_at", 0 = off): visitors,
  deliveries and rings, then each part of the day (night, early morning,
  morning, afternoon, evening, late evening) with when the visitors came and
  what they were doing (describe.py). A visitor is a ring or a person moving
  in view; clips less than VISIT_GAP apart are one visit.
- The milk delivery ("milk_window", e.g. "4:30-5:30", "" = off). Not just
  anyone who comes then: the milkman's walk, measured on the Hailo over the
  whole clip. He comes in from the gate, goes down to the door, stops briefly
  at the spot where the milk is left, and goes back out through the gate, all
  within a minute (milk_walk). Someone of the house going out starts at the
  door, someone coming home ends there, and a visitor stops elsewhere or stays
  longer. The spot is learned from the deliveries found or confirmed so far.
  The description model (describe.py) does not decide: in the dark its
  pictures are infrared, where milk packets look like newspapers; it is told
  it is looking at the milkman instead. The delivery goes to milk.json (date: time, clip, how, spot) and to the phones
  with the milkman's picture; when the window ends with no milk, the phones are
  told who did come. A wrong call is put right on the event (Milk delivery /
  Not the milk), which also teaches the spot.
- Night visitors ("night_window", e.g. "1-4", "" = off): a person moving in view
  in those hours is announced at once with a picture from the camera, and
  again with its description once the clip is in."""
import datetime as dt, json, statistics, subprocess, threading, time
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from recorder import DIR

ROOT = Path(__file__).resolve().parent
MILK_FILE = ROOT / "milk.json"
VISIT_GAP = 180  # seconds
NIGHT_GAP = 600  # one night alert per this many seconds
PARTS = (("Night", 0, 5, "🌙"), ("Early morning", 5, 8, "🌅"), ("Morning", 8, 12, "☀️"),
         ("Afternoon", 12, 17, "🌤️"), ("Evening", 17, 21, "🌆"), ("Late evening", 21, 24, "🌃"))
DELIVERED = ("milk", "parcel", "newspaper", "food")
SUMMARY_HOURS = (0, 20, 21, 22)
MILK_WINDOWS = ("", "4:30-5:30", "4-6", "5-7", "6-8")
MILK_DEFAULT = "4:30-5:30"
# The milkman's walk, in 0..1 of the picture (person box centres). Measured on this camera (VIGI C330I above the
# door, 30 Oct 2026): the gate and path are the top of the picture, the door the bottom.
GATE_Y = 0.45      # above this: outside (the gate and the path)
DOOR_Y = 0.65      # below this: at the door
MILK_SPOT = (0.57, 0.78)  # where the milk is left, until deliveries teach it
SPOT_NEAR = 0.15   # a stop counts as at the spot when this close to it
MILK_MAX_S = 60    # gate, door and gate again within this
MILK_STOP_S = 30   # at the door no longer than this
NIGHT_WINDOWS = ("", "1-4", "0-5", "23-5")


def clock(t):
    return time.strftime("%I:%M %p", time.localtime(t)).lstrip("0").lower()


def hours(window):
    """"4:30-5:30" -> (4.5, 5.5); "23-5" -> (23, 5); "" -> None"""
    def h(x):
        hh, _, mm = x.partition(":"); return int(hh) + int(mm or 0) / 60
    try: a, b = (h(x) for x in window.split("-")); return a, b
    except (AttributeError, ValueError): return None


def hour_of(t):
    lt = time.localtime(t); return lt.tm_hour + lt.tm_min / 60


def in_hours(t, window):
    """Is time t inside the hours "a-b" (which may run past midnight: "23-5")?"""
    h = hours(window)
    if not h: return False
    x = hour_of(t); a, b = h
    return a <= x < b if a < b else x >= a or x < b


def window_text(window):
    """"4:30-5:30" -> 4:30 am to 5:30 am; "23-5" -> 11 pm to 5 am"""
    def f(h):
        hh, mm = int(h) % 24, round(h % 1 * 60)
        if not mm and hh in (0, 12): return "midnight" if hh == 0 else "noon"
        return f"{(hh - 1) % 12 + 1}{f':{mm:02d}' if mm else ''} {'am' if hh < 12 else 'pm'}"
    a, b = hours(window); return f"{f(a)} to {f(b)}"


def person_path(video, detector, fps=2):
    """[(seconds, centre x, centre y)] of the largest person in each frame of the clip, on the Hailo;
    None without it."""
    w, h = 640, 360
    r = subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(video), "-an",
                        "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, timeout=180)
    frames = np.frombuffer(r.stdout, np.uint8)
    frames = frames[:frames.size // (w * h * 3) * w * h * 3].reshape(-1, h, w, 3)
    path = []
    for i, f in enumerate(frames):
        found = detector.ask(f)
        if found is None: return None
        people = [d["box"] for d in found if d["label"] == "Person"]
        if people:
            x1, y1, x2, y2 = max(people, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            path.append((i / fps, (x1 + x2) / 2, (y1 + y2) / 2))
    return path


def milk_walk(path, spot):
    """(the milkman's walk?, where they stopped at the door (x, y) or None, why not)"""
    if not path: return False, None, "nobody seen"
    (t0, _, y0), (t1, _, y1) = path[0], path[-1]
    door = [(t, x, y) for t, x, y in path if y >= DOOR_Y]
    stop = (statistics.median(x for _, x, _ in door), statistics.median(y for _, _, y in door)) if door else None
    if y0 > GATE_Y: return False, stop, "came out of the house, not in from the gate"
    if not door: return False, stop, "did not come to the door"
    if y1 > GATE_Y: return False, stop, "went into the house, not back out of the gate"
    if t1 - t0 > MILK_MAX_S: return False, stop, f"stayed {t1 - t0:.0f} s"
    if door[-1][0] - door[0][0] > MILK_STOP_S: return False, stop, f"stood at the door {door[-1][0] - door[0][0]:.0f} s"
    if abs(stop[0] - spot[0]) > SPOT_NEAR or abs(stop[1] - spot[1]) > SPOT_NEAR:
        return False, stop, f"stopped at {stop[0]:.2f}, {stop[1]:.2f}, not where the milk is left ({spot[0]:.2f}, {spot[1]:.2f})"
    return True, stop, ""


def times(n):
    return {0: "did not ring", 1: "rang once", 2: "rang twice"}.get(n, f"rang {n} times")


def plural(n, word):
    """1 visitor, 2 visitors, 2 deliveries, 2 buses"""
    if n == 1: return f"1 {word}"
    if word.endswith("y") and word[-2] not in "aeiou": return f"{n} {word[:-1]}ies"
    return f"{n} {word}{'es' if word.endswith('s') else 's'}"


def is_visitor(e):
    return e.get("kind") == "ring" or "Person" in (e.get("detected") or [])


def visits(entries):
    """Visitor events grouped into visits: [[entry, ...], ...], oldest first."""
    out = []
    for e in sorted((e for e in entries if is_visitor(e)), key=lambda e: e["time"]):
        if out and e["time"] - out[-1][-1]["time"] < VISIT_GAP: out[-1].append(e)
        else: out.append([e])
    return out


def passing(v):
    """Only walked past (as the description model saw it), and did not ring."""
    return all(e.get("role") == "passer-by" for e in v) and not any(e.get("kind") == "ring" for e in v)


def visit_line(v):
    """4:54 am · milk · A man hanging a bag on the door (rang)"""
    about = next((e["about"] for e in v if e.get("about")), "")
    milk = any(e.get("milk") for e in v)
    brought = next((e["carrying"] for e in v if e.get("carrying") in DELIVERED), "")
    rang = any(e.get("kind") == "ring" for e in v)
    tags = ["milk delivery" if milk else f"{brought} delivery" if brought else "", "rang the bell" if rang else ""]
    return " · ".join(x for x in [clock(v[0]["time"]), *tags, about] if x)


def delivered(v):
    return any(e.get("milk") or e.get("carrying") in DELIVERED or e.get("role") == "delivery" for e in v)


class Daily(QObject):
    changed = Signal()  # the milk record changed (settings pages, events)
    milk_found = Signal(object, str, object)  # from the checking thread: entry, how, where he stopped

    def __init__(self, settings, save, recorder, describer, detector, phone, log):
        """phone(title, text, tags, priority, image_bytes): to the phones; log(text): the home screen's events."""
        super().__init__()
        self.settings = settings; self.save = save; self.rec = recorder; self.describer = describer; self.detector = detector
        self.phone = phone; self.log = log
        try: self.milk = json.loads(MILK_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError): self.milk = {}
        self.night_sent = 0.0; self.checking = 0; self.lock = threading.Lock()
        recorder.saved.connect(self.on_saved); describer.described.connect(self.on_described)
        self.milk_found.connect(self._milk_came)
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(30000)
        QTimer.singleShot(20000, self.recheck_today)  # this morning's clips, when the dashboard was restarted since

    # ---------- milk ----------
    def milk_today(self, day=None):
        """{"time", "video", "how": "seen" | "guess" | "marked"} of the day's delivery, or None."""
        return self.milk.get((day or dt.date.today()).isoformat())

    def milk_status(self):
        """Milk today: delivered at 4:54 am / not yet / off - for the settings pages."""
        w = self.settings.get("milk_window", MILK_DEFAULT)
        if not hours(w): return "Not tracked"
        m = self.milk_today()
        if m: return f"Delivered today at {clock(m['time'])}" + (" (marked by you)" if m.get("how") == "marked" else "")
        return f"Not seen yet today (looked for from {window_text(w)})"

    def spot(self):
        """Where the milk is left: the middle of where the milkman stopped on the last deliveries."""
        spots = [m["spot"] for _, m in sorted(self.milk.items()) if m.get("spot")][-10:]
        if not spots: return MILK_SPOT
        return statistics.median(s[0] for s in spots), statistics.median(s[1] for s in spots)

    def _write_milk(self):
        cutoff = (dt.date.today() - dt.timedelta(days=60)).isoformat()
        self.milk = {d: m for d, m in self.milk.items() if d >= cutoff}
        tmp = MILK_FILE.with_suffix(".tmp"); tmp.write_text(json.dumps(self.milk, indent=1), encoding="utf-8"); tmp.replace(MILK_FILE)

    def _milk_came(self, entry, how, stop):
        day = dt.date.fromtimestamp(entry["time"]).isoformat()
        if day in self.milk: return  # found by an earlier clip meanwhile
        self.milk[day] = {"time": entry["time"], "video": entry.get("video", ""), "how": how,
                          "spot": [round(stop[0], 3), round(stop[1], 3)] if stop else None}
        entry["milk"] = True; self.rec.update(entry); self._write_milk(); self.changed.emit()
        if "about" in entry: self.describer.again(entry)  # described before it was known to be the milkman
        what = f"Milk delivered at {clock(entry['time'])}"; self.log(what)
        if time.time() - entry["time"] < 3600:  # not for this morning's, found again after a restart hours later
            self.phone("Milk delivered", what + "." + (f" {entry['about']}." if entry.get("about") else ""),
                       "glass_of_milk", "default", self.picture(entry))

    def mark_milk(self, entry, on):
        """Put right from an event: this was (not) the milk delivery."""
        day = dt.date.fromtimestamp(entry["time"]).isoformat()
        if on:
            for e in self.rec.entries:  # one delivery a day
                if e.get("milk") and e is not entry and dt.date.fromtimestamp(e["time"]).isoformat() == day:
                    e.pop("milk"); self.rec.update(e)
            self.milk[day] = {"time": entry["time"], "video": entry.get("video", ""), "how": "marked"}; entry["milk"] = True
            threading.Thread(target=self._learn_spot, args=(entry, day), daemon=True).start()
            if "about" in entry: self.describer.again(entry)
        else:
            entry.pop("milk", None)
            if (self.milk.get(day) or {}).get("time") == entry["time"]: self.milk.pop(day)
        self.rec.update(entry); self._write_milk(); self.changed.emit()

    def _learn_spot(self, entry, day):
        """A delivery marked by hand: where did the milkman stop? (teaches the spot)"""
        path = person_path(DIR / entry["video"], self.detector) if entry.get("video") else None
        door = [(x, y) for _, x, y in path or [] if y >= DOOR_Y]
        if door and (self.milk.get(day) or {}).get("time") == entry["time"]:
            self.milk[day]["spot"] = [round(statistics.median(x for x, _ in door), 3), round(statistics.median(y for _, y in door), 3)]
            self._write_milk()

    def check_milk(self, entry):
        """A motion clip of a person in the milk window: is it the milkman? (in the background)"""
        w = self.settings.get("milk_window", MILK_DEFAULT)
        if not hours(w) or entry.get("kind") != "motion" or "Person" not in (entry.get("detected") or []): return
        if not in_hours(entry["time"], w) or not entry.get("video"): return
        if dt.date.fromtimestamp(entry["time"]) != dt.date.today() or self.milk_today(): return
        with self.lock: self.checking += 1
        threading.Thread(target=self._check, args=(entry,), daemon=True).start()

    def _check(self, entry):
        try:
            path = person_path(DIR / entry["video"], self.detector)
            if path is None: print("Milk check: no Hailo", flush=True); return
            ok, stop, why = milk_walk(path, self.spot())
            print(f"Milk check {clock(entry['time'])}: " + ("the milkman" if ok else f"not the milkman ({why})"), flush=True)
            if ok: self.milk_found.emit(entry, "walk", stop)
        except Exception as e:
            print("Milk check failed:", e, flush=True)
        finally:
            with self.lock: self.checking -= 1

    def recheck_today(self):
        t0 = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
        for e in sorted((e for e in self.rec.entries if e["time"] >= t0), key=lambda e: e["time"]): self.check_milk(e)

    # ---------- night ----------
    def on_motion(self, labels):
        """Something moved in view just now (watch.py)."""
        w = self.settings.get("night_window", "1-4")
        if "Person" not in labels or not in_hours(time.time(), w) or time.time() - self.night_sent < NIGHT_GAP: return
        self.night_sent = time.time()
        self.log(f"Someone at the door at night ({clock(time.time())})")
        def send():
            self.phone("Someone at the door", f"A person is at the front door at {clock(time.time())}. "
                       "The recording follows in a minute.", "rotating_light", "urgent", self.rec.snapshot())
        threading.Thread(target=send, daemon=True).start()

    def _night_followup(self, entry):
        if not entry.get("about") or not self.night_sent or not 0 <= entry["time"] - self.night_sent < 120: return
        self.phone(f"Night visitor at {clock(entry['time'])}", entry["about"] + ".", "rotating_light", "high", self.picture(entry))

    # ---------- the day's summary ----------
    def summary(self, day=None):
        """(title, text) of one day."""
        day = day or dt.date.today()
        t0 = dt.datetime.combine(day, dt.time()).timestamp(); t1 = t0 + 86400
        entries = [e for e in self.rec.entries if t0 <= e["time"] < t1]
        everyone = visits(entries); vs = [v for v in everyone if not passing(v)]; passed = len(everyone) - len(vs)
        rings = sum(1 for e in entries if e.get("kind") == "ring"); n_del = sum(1 for v in vs if delivered(v))
        head = (f"{plural(len(vs), 'visit')}, {plural(n_del, 'delivery')}, the bell {times(rings)}." if vs else
                f"No visits; the bell {times(rings)}.")
        if passed: head += f" {plural(passed, 'person')} walked past.".replace("persons", "people")
        lines = [head]
        m = self.milk_today(day)
        if hours(self.settings.get("milk_window", MILK_DEFAULT)):
            lines.append(f"🥛 Milk: {'came at ' + clock(m['time']) if m else 'not seen'}")
        lines.append("")
        for name, a, b, icon in PARTS:
            part = [v for v in vs if a <= time.localtime(v[0]["time"]).tm_hour < b]
            if not part: lines.append(f"{icon} {name}: none"); continue
            lines.append(f"{icon} {name}: {plural(len(part), 'visit')}")
            told = [v for v in part if visit_line(v) != clock(v[0]["time"])][:4]  # with something to say first
            lines += [f"   {visit_line(v)}" for v in told]
            rest = [v for v in part if not any(v is t for t in told)]
            if rest:
                lines.append("   " + ("also " if told else "") + ", ".join(clock(v[0]["time"]) for v in rest[:8])
                             + (f" and {len(rest) - 8} more" if len(rest) > 8 else ""))
        others = {}
        for e in entries:
            for label in e.get("detected") or []:
                if label != "Person": others[label] = others.get(label, 0) + 1
        if others: lines += ["", "Also seen: " + ", ".join(f"{plural(n, l.lower())}" for l, n in sorted(others.items()))]
        name = "Today" if day == dt.date.today() else f"{day:%a %d %b}"
        return f"{name} at the door", "\n".join(lines)

    def send_summary(self, day=None):
        title, text = self.summary(day); self.phone(title, text, "house", "default", None)

    # ---------- every half minute, and as clips come in ----------
    def tick(self):
        now = dt.datetime.now(); today = now.date().isoformat()
        at = self.settings.get("summary_at", 21)
        if at and now.hour >= at and self.settings.get("summary_sent") != today:
            self.settings["summary_sent"] = today; self.save()
            if now.hour == at: self.send_summary()  # not when the Pi was off at that hour
        w = self.settings.get("milk_window", MILK_DEFAULT); h = hours(w); x = now.hour + now.minute / 60
        if h and x >= h[1] + 0.1 and self.settings.get("milk_reported") != today:  # a few minutes for the last clip
            due = x < h[1] + 2  # not when the Pi was off then
            if due and self.checking: return  # clips still being looked at
            self.settings["milk_reported"] = today; self.save()
            if due and not self.milk_today():
                t0 = dt.datetime.combine(now.date(), dt.time()).timestamp()
                came = [v for v in visits(e for e in self.rec.entries if e["time"] >= t0) if in_hours(v[0]["time"], w)]
                text = f"No milk delivery was seen from {window_text(w)}."
                if came: text += " Who came: " + "; ".join(visit_line(v) for v in came[:3]) + ". If one was the milk, mark it in Events."
                self.phone("No milk today?", text, "warning", "default", self.picture(came[0][0]) if came else None)
                self.log("No milk delivery seen")

    def on_saved(self, entry):
        self.check_milk(entry)

    def on_described(self, entry):
        self._night_followup(entry)

    @staticmethod
    def picture(entry):
        """The close-up of the visitor (describe.py), else the clip's picture, as JPEG bytes."""
        for key in ("who", "thumb"):
            if entry.get(key):
                try: return (DIR / entry[key]).read_bytes()
                except OSError: pass
        return None
