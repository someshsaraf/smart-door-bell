"""Visitor descriptions: one line about who is in each recording ("A delivery
man in a red jacket leaving a parcel at the door"), with what they carried and
why they came, written on this Pi by a small vision-language model. The events,
the daily summary and the milk check (daily.py) use them. Nothing leaves the Pi.

The model runs in llama.cpp's llama-server, which setup_vlm.sh builds and
starts as a user service on 127.0.0.1:8090 (config.json "describe": {"url": ...}
points elsewhere). For each new clip, frames from its first LOOK_S seconds
after the press or movement are checked on the Hailo (detect.py); the one where
the visitor is largest is taken at full resolution and cropped around them, so
the model sees them up close. That close-up is kept next to the clip ("who").
Without the Hailo the whole picture at the press or movement is used.

Only rings and clips with a person are described (an animal or a vehicle has
its name already), and only when the Hailo finds the person in the frames:
shown a picture with nobody in it, the model would make a visitor up.
One clip takes ~1-2 minutes of 3 of the Pi's cores (the server runs at low
priority); clips wait in a queue, newest first. Clips of the last BACKFILL_DAYS
that have no description yet are done too. While the server is not there, nothing is
lost: the queue waits and is tried again every minute."""
import base64, json, subprocess, threading, time, urllib.error, urllib.request
import numpy as np
import cv2
from PySide6.QtCore import QObject, Signal
from recorder import DIR

URL = "http://127.0.0.1:8090"
LOOK_S = 20        # seconds after the press or movement searched for the best view
FPS = 2            # frames a second looked at, in that time
FW, FH = 960, 540  # the frames' size for the search
CROP_MAX = 512     # the close-up's longest side, as sent to the model (smaller is quicker)
BACKFILL_DAYS = 2
CARRYING = ("milk", "parcel", "newspaper", "food", "flowers", "other", "nothing")
ROLES = ("delivery", "visitor", "worker", "passer-by", "unknown")
PROMPT = """This picture is from a doorbell camera above the front door of a house in India, looking down at the doorstep{night}.
Look at the {what} and reply with JSON only, for example:
{{"about": "A delivery man in a red jacket leaving a parcel at the door", "carrying": "parcel", "role": "delivery"}}
- "about": one sentence of at most 14 words: who it is, what they wear, what they are doing or carrying.
- "carrying": what they bring, carry or leave: "milk" (milk packets or bottles, often in a bag hung on the door), "parcel", "newspaper", "food", "flowers", "other" or "nothing".
- "role": "delivery" (bringing something), "visitor", "worker" (cleaner, gardener, guard), "passer-by" or "unknown".
Say only what you can see."""
MILKMAN = ("\nThe house knows this is the milkman: what he carries or leaves is the morning milk (milk packets). "
           'Use "carrying": "milk" and "role": "delivery", and describe him.')


class Describer(QObject):
    described = Signal(object)  # the entry itself (not a copy), which now has "about", "carrying", "role" (and "who")

    def __init__(self, recorder, detector, url=None):
        super().__init__()
        self.rec = recorder; self.detector = detector; self.url = (url or URL).rstrip("/")
        self.cond = threading.Condition(); self.waiting = []; self.up = None; self.model = ""
        recorder.saved.connect(self.add)
        threading.Thread(target=self._run, daemon=True).start()

    def available(self):
        """Is the model there (None: not known yet)?"""
        return self.up

    def status(self):
        if self.up is None: return "Checking…"
        if not self.up: return "Not set up: run setup_vlm.sh on the Pi (see docs/recordings.md)"
        n = len(self.waiting)
        return f"Ready · {self.model}" + (f" · {n} clip{'s' if n > 1 else ''} waiting" if n else "")

    @staticmethod
    def wanted(entry):
        """A ring or a person, recorded, not described yet."""
        return (entry.get("video") and "about" not in entry
                and (entry.get("kind") == "ring" or "Person" in (entry.get("detected") or [])))

    def again(self, entry):
        """Describe once more, now that more is known (it is the milkman)."""
        for k in ("about", "carrying", "role"): entry.pop(k, None)
        self.add(entry)

    def add(self, entry):
        if self.wanted(entry):
            with self.cond:
                self.waiting.append(entry); self.cond.notify()

    def _run(self):
        cutoff = time.time() - BACKFILL_DAYS * 86400
        with self.cond:
            self.waiting += [e for e in list(self.rec.entries) if self.wanted(e) and e["time"] >= cutoff]
        while True:
            if not self._check():
                time.sleep(60); continue
            with self.cond:
                self.cond.wait_for(lambda: self.waiting)
                entry = max(self.waiting, key=lambda e: e["time"]); self.waiting.remove(entry)
            if not any(e is entry for e in self.rec.entries): continue  # deleted meanwhile
            try:
                self._describe(entry)
            except urllib.error.HTTPError as e:  # the server is there but refused this one
                print("Description failed:", e, e.read()[:200], flush=True); entry["about"] = ""
            except OSError as e:  # the server went away: again later
                print("Description not written:", e, flush=True); self.up = False
                with self.cond: self.waiting.append(entry)
                continue
            except Exception as e:
                print("Description failed:", e, flush=True); entry["about"] = ""
            self.rec.update(entry); self.described.emit(entry)

    def _check(self):
        try:
            with urllib.request.urlopen(self.url + "/v1/models", timeout=5) as r:
                data = json.load(r)
            self.model = (data.get("data") or [{}])[0].get("id", "").split("/")[-1].split(":")[0].replace("-GGUF", "")
            self.up = True
        except (OSError, ValueError):
            self.up = False
        return self.up

    # ---------- the picture ----------
    def _describe(self, entry):
        t0 = time.monotonic()
        crop, night = self._closeup(entry)
        if crop is None: entry["about"] = ""; return
        stem = DIR / entry["video"][:-4]
        who = stem.with_name(stem.name + "_who.jpg")
        if cv2.imwrite(str(who), crop, [cv2.IMWRITE_JPEG_QUALITY, 85]): entry["who"] = who.relative_to(DIR).as_posix()
        what = ", ".join(entry.get("detected") or []).lower() or "person at the door"
        jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        prompt = PROMPT.format(night=" (at night: an infrared picture, black and white)" if night else "", what=what)
        if entry.get("milk"): prompt += MILKMAN  # in infrared, milk packets look like anything white
        answer = self._ask(prompt, jpg)
        entry["about"] = str(answer.get("about") or "").strip().rstrip(".")[:160]
        entry["carrying"] = answer.get("carrying") if answer.get("carrying") in CARRYING else "other"
        entry["role"] = answer.get("role") if answer.get("role") in ROLES else "unknown"
        if entry.get("milk"): entry["carrying"], entry["role"] = "milk", "delivery"  # known from his walk, or from you
        print(f"Described {entry['video']} in {time.monotonic() - t0:.0f} s: {entry['about']} "
              f"[{entry['carrying']}, {entry['role']}]", flush=True)

    def _closeup(self, entry):
        """(BGR close-up of the visitor, taken at night?) from the clip; (None, False) when it cannot be read."""
        video = DIR / entry["video"]
        start = max(0.0, (entry.get("pre") or 0) - 1)
        r = subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{start:.1f}", "-t", str(LOOK_S),
                            "-i", str(video), "-an", "-vf", f"fps={FPS},scale={FW}:{FH}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           capture_output=True, timeout=120)
        frames = np.frombuffer(r.stdout, np.uint8)
        if r.returncode != 0 or not frames.size: return None, False
        frames = frames[:frames.size // (FW * FH * 3) * FW * FH * 3].reshape(-1, FH, FW, 3)
        best, box = self._best(frames, entry)
        if box is False: return None, False  # the Hailo looked and nobody is there
        at = start + (best / FPS if box else min(1.5, len(frames) / FPS))
        full = self._frame(video, at)
        if full is None: full = frames[min(best, len(frames) - 1)]
        h, w = full.shape[:2]
        if box:  # around the visitor, with room for what they carry and where they stand
            x1, y1, x2, y2 = box; bw, bh = x2 - x1, y2 - y1
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            hw, hh = max(bw * 0.85, 0.2), max(bh * 0.85, 0.2)
            x1, x2, y1, y2 = max(0.0, cx - hw), min(1.0, cx + hw), max(0.0, cy - hh), min(1.0, cy + hh)
            full = full[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
        h, w = full.shape[:2]; s = CROP_MAX / max(h, w)
        if s < 1: full = cv2.resize(full, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        b, g, r_ = (full[..., i].astype(np.int16) for i in range(3))
        night = float(np.mean(np.abs(b - g) + np.abs(g - r_))) < 6  # infrared: no colour
        return full, night

    def _best(self, frames, entry):
        """(index of the frame where the visitor is largest, their box in 0..1); the box is False when nobody
        is found, None without the Hailo."""
        labels = set(entry.get("detected") or ["Person"])
        best, area, box = 0, 0.0, None
        for i, f in enumerate(frames):
            found = self.detector.ask(f) if self.detector else None
            if found is None: return 0, None  # no Hailo: the picture at the press or movement
            people = [d for d in found if d["label"] == "Person"]
            hits = people if "Person" in labels and people else [d for d in found if d["label"] in labels]
            for d in hits:
                x1, y1, x2, y2 = d["box"]; a = (x2 - x1) * (y2 - y1) * (2 if d["label"] == "Person" else 1)
                if a > area: best, area, box = i, a, d["box"]
        return best, box if box else False

    @staticmethod
    def _frame(video, at):
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
                            "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True, timeout=30)
        if r.returncode != 0 or not r.stdout: return None
        return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)

    # ---------- the model ----------
    def _ask(self, prompt, jpg):
        body = {"messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()}},
                    {"type": "text", "text": prompt}]}],
                "temperature": 0.1, "max_tokens": 120, "response_format": {"type": "json_object"}}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            text = json.load(r)["choices"][0]["message"]["content"]
        try: return json.loads(text[text.index("{"):text.rindex("}") + 1])
        except ValueError: return {"about": text.strip().splitlines()[0] if text.strip() else ""}
