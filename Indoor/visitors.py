"""Visitor log and parcel watch, all on the Pi (nothing leaves the house).

Visitor log: for VISIT_S after a ring, frames from the ring screen's camera
stream are searched for faces (OpenCV's YuNet detector); the clearest face
and a snapshot are saved under visitors/ and listed in visitors/log.json.
Faces are only cut out and kept, never identified. Entries older than
KEEP_DAYS are deleted.

Parcel watch: a separate low-rate reader of the camera's substream checks a
porch zone once a second. Something new that stays still in the zone after
there was movement (someone came and went) is a parcel; when the zone looks
like the empty porch again, it was picked up. Slow light changes are
followed; a sudden change of the whole picture (day/night switch) resets
the reference instead of raising an alarm. Zone in config.json:
    "porch": {"zone": [0.2, 0.55, 0.8, 1.0]}    (left, top, right, bottom; 0..1)"""
import json, threading, time, urllib.request
from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal
try:
    import cv2, numpy as np
except ImportError:
    cv2 = np = None

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "visitors"
MODEL = ROOT / "models" / "face_detection_yunet_2023mar.onnx"
MODEL_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
VISIT_S = 12        # look for a face this long after a ring
FACE_EVERY_S = 0.4  # at most this often (the camera gives ~25 frames/s)
KEEP_DAYS = 30


def face_detector():
    """YuNet (downloaded once, ~230 kB) or, offline, OpenCV's older Haar cascade; None if neither."""
    if cv2 is None: return None
    if not MODEL.exists():
        try:
            MODEL.parent.mkdir(exist_ok=True)
            urllib.request.urlretrieve(MODEL_URL, MODEL)
            if MODEL.stat().st_size < 100_000: MODEL.unlink()  # an error page, not the model
        except Exception as e:
            print("Face model download failed:", e, flush=True)
    if MODEL.exists() and hasattr(cv2, "FaceDetectorYN"):
        det = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), 0.75, 0.3, 50)
        def yunet(img):
            det.setInputSize((img.shape[1], img.shape[0]))
            _, faces = det.detect(img)
            return [(int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[14])) for f in (faces if faces is not None else [])]
        return yunet
    for xml in ("/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
                getattr(getattr(cv2, "data", None), "haarcascades", "") + "haarcascade_frontalface_default.xml"):
        if Path(xml).exists():
            haar = cv2.CascadeClassifier(xml)
            def cascade(img):
                g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                return [(x, y, w, h, 0.8) for x, y, w, h in haar.detectMultiScale(g, 1.1, 5, minSize=(40, 40))]
            return cascade
    return None


class VisitorLog(QObject):
    """Saved rings with a snapshot and, when one was seen, the visitor's face."""
    saved = Signal(dict)

    def __init__(self):
        super().__init__(); self.lock = threading.Lock(); self.active = None; self.detect = None
        LOG_DIR.mkdir(exist_ok=True); self.file = LOG_DIR / "log.json"
        try: self.entries = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError): self.entries = []
        threading.Thread(target=self._load_detector, daemon=True).start()
        self.prune()

    def _load_detector(self):
        self.detect = face_detector()
        print("Face detector:", "ready" if self.detect else "unavailable", flush=True)

    def begin(self, kind="ring", note=""):
        """A ring started: collect frames for VISIT_S (finish() saves earlier)."""
        with self.lock:
            self.active = {"time": time.time(), "kind": kind, "note": note, "best": None, "score": 0.0,
                           "frame": None, "next": 0.0, "until": time.monotonic() + VISIT_S}

    def offer(self, frame):
        """Called from the camera thread with each BGR frame; cheap when nothing is collected."""
        with self.lock:
            a = self.active
            if not a or time.monotonic() < a["next"]: return
            if time.monotonic() > a["until"]: return
            a["next"] = time.monotonic() + FACE_EVERY_S
            if a["frame"] is None: a["frame"] = frame.copy()
        small, k = self._small(frame)
        faces = self.detect(small) if self.detect else []
        if not faces: return
        x, y, w, h, s = max(faces, key=lambda f: f[4] * f[2] * f[3])
        score = s * w * h
        with self.lock:
            if self.active is a and score > a["score"]:
                a["score"] = score; a["frame"] = frame.copy(); a["best"] = (int(x / k), int(y / k), int(w / k), int(h / k))

    @staticmethod
    def _small(frame, width=640):
        k = min(1.0, width / frame.shape[1])
        return (cv2.resize(frame, None, fx=k, fy=k) if k < 1 else frame), k

    def finish(self):
        """Saves what was collected (in the background) and stops collecting."""
        with self.lock:
            a, self.active = self.active, None
        if a:  # also without a picture (no camera): the ring is still logged
            threading.Thread(target=self._save, args=(a,), daemon=True).start()

    def add_snapshot(self, frame, kind, note):
        """An event with a ready picture (the parcel watch)."""
        self._save({"time": time.time(), "kind": kind, "note": note, "frame": frame, "best": None})

    def _save(self, a):
        t = time.localtime(a["time"]); day = LOG_DIR / time.strftime("%Y-%m-%d", t); day.mkdir(parents=True, exist_ok=True)
        stem = time.strftime("%H%M%S", t) + "_" + a["kind"]
        frame = a["frame"]
        entry = {"time": a["time"], "kind": a["kind"], "note": a.get("note", ""), "photo": "", "face": ""}
        if frame is not None and cv2 is not None:
            big, _ = self._small(frame, 1280)
            cv2.imwrite(str(day / f"{stem}.jpg"), big, [cv2.IMWRITE_JPEG_QUALITY, 85])
            entry["photo"] = (day / f"{stem}.jpg").relative_to(LOG_DIR).as_posix()
        if frame is not None and a["best"]:
            x, y, w, h = a["best"]; m = int(0.35 * max(w, h))  # a margin around the face
            crop = frame[max(0, y - m):y + h + m, max(0, x - m):x + w + m]
            if crop.size:
                cv2.imwrite(str(day / f"{stem}_face.jpg"), cv2.resize(crop, (240, int(240 * crop.shape[0] / crop.shape[1]))),
                            [cv2.IMWRITE_JPEG_QUALITY, 90])
                entry["face"] = (day / f"{stem}_face.jpg").relative_to(LOG_DIR).as_posix()
        with self.lock:
            self.entries.insert(0, entry); self._write()
        self.saved.emit(entry)

    def _write(self):
        tmp = self.file.with_suffix(".tmp"); tmp.write_text(json.dumps(self.entries, indent=1), encoding="utf-8"); tmp.replace(self.file)

    def prune(self):
        cutoff = time.time() - KEEP_DAYS * 86400
        with self.lock:
            old = [e for e in self.entries if e["time"] < cutoff]
            self.entries = [e for e in self.entries if e["time"] >= cutoff]
            if old: self._write()
        for e in old:
            for key in ("photo", "face"):
                if e.get(key): (LOG_DIR / e[key]).unlink(missing_ok=True)
        for d in LOG_DIR.iterdir():
            if d.is_dir() and not any(d.iterdir()): d.rmdir()


class PorchDetector:
    """Decides 'parcel left' / 'parcel taken' from one frame a second (pure logic, easy to test)."""
    STILL_S = 20        # no movement this long before judging the zone
    VISIT_WINDOW_S = 600  # a parcel must follow movement (someone came) within this
    MIN_AREA, MAX_AREA = 0.015, 0.6  # of the zone

    def __init__(self, zone=(0.2, 0.55, 0.8, 1.0)):
        self.zone = zone; self.ref = None; self.prev = None; self.last_motion = -1e9; self.light = None
        self.parcel = None  # (x, y, w, h) in zone pixels while one is there
        self.ref_has_parcel = False  # the reference was retaken with the parcel in it (light change)
        self.candidate = 0; self.gone = 0

    def _zone(self, frame):
        h, w = frame.shape[:2]; x0, y0, x1, y1 = self.zone
        z = cv2.cvtColor(frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)], cv2.COLOR_BGR2GRAY)
        z = cv2.resize(z, (160, max(1, int(160 * z.shape[0] / max(1, z.shape[1])))))
        return cv2.GaussianBlur(z, (5, 5), 0)

    def _changed(self, a, b):
        """Mask of real change between two zone images, ignoring an overall brightness shift."""
        gain = float((b.mean() + 1) / (a.mean() + 1))
        a = (a.astype(np.float32) * gain).astype(np.float32)
        threshold = max(10.0, 28.0 * float(b.mean()) / 120.0)  # a dark scene has less contrast
        mask = (cv2.absdiff(a, b.astype(np.float32)) > threshold).astype(np.uint8)
        return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    def step(self, frame, now):
        """Returns "delivered", "taken" or None."""
        z = self._zone(frame); bright = float(frame.mean())
        if self.ref is None or self.ref.shape != z.shape:  # first frame, or the stream changed size
            self.ref = self.prev = z; self.light = bright; return None
        moving = self._changed(z, self.prev).mean() > 0.01
        self.prev = z
        if moving: self.last_motion = now; self.candidate = self.gone = 0; return None
        if abs(bright - self.light) > 35:  # day/night switch or lights on: new reference
            self.light = bright; self.ref = z; self.candidate = 0
            self.ref_has_parcel = self.parcel is not None
            return None
        self.light = 0.98 * self.light + 0.02 * bright
        if now - self.last_motion < self.STILL_S: return None
        mask = self._changed(z, self.ref)
        if self.parcel:
            x, y, w, h = self.parcel
            changed = mask[y:y + h, x:x + w].mean()
            # gone: the spot looks like the empty porch again (or, with the parcel in
            # the reference, no longer like the parcel)
            if (changed > 0.4) if self.ref_has_parcel else (changed < 0.15):
                self.gone += 1
                if self.gone >= 3:
                    self.parcel = None; self.gone = 0
                    if self.ref_has_parcel: self.ref = z; self.ref_has_parcel = False
                    return "taken"
            else: self.gone = 0
            return None
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        area = z.shape[0] * z.shape[1]
        blobs = [s for s in stats[1:] if self.MIN_AREA * area < s[cv2.CC_STAT_AREA] < self.MAX_AREA * area]
        if not blobs:
            self.candidate = 0
            self.ref = cv2.addWeighted(self.ref, 0.95, z, 0.05, 0)  # follow slow daylight changes
            return None
        if now - self.last_motion > self.VISIT_WINDOW_S:
            self.ref = z; return None  # a change nobody brought (e.g. a shadow settled): new normal
        self.candidate += 1
        if self.candidate < 3: return None  # still there after three checks
        b = max(blobs, key=lambda s: s[cv2.CC_STAT_AREA])
        self.parcel = (b[0], b[1], b[2], b[3]); self.candidate = 0
        return "delivered"

    def box_in_frame(self, frame):
        """The parcel's rectangle in full-frame pixels, for the snapshot."""
        if not self.parcel: return None
        h, w = frame.shape[:2]; x0, y0, x1, y1 = self.zone
        zw, zh = (x1 - x0) * w, (y1 - y0) * h; k = zw / 160
        x, y, bw, bh = self.parcel
        return int(x0 * w + x * k), int(y0 * h + y * k), int(bw * k), int(bh * k)


class PorchWatch(QThread):
    """Reads the camera's substream all the time and runs the PorchDetector once a second."""
    event = Signal(str, object)  # "delivered"/"taken", BGR snapshot
    state = Signal(str)

    def __init__(self, url, zone):
        super().__init__(); self.url = url; self.det = PorchDetector(tuple(zone)); self.running = True

    def run(self):
        while self.running:
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                self.state.emit("Porch camera not reachable"); time.sleep(30); continue
            self.state.emit("Watching the porch"); last = 0.0
            while self.running:
                if not cap.grab(): break  # keeps the stream current; decoding every frame is cheap at substream size
                if time.monotonic() - last < 1.0: continue
                last = time.monotonic(); ok, frame = cap.retrieve()
                if not ok: break
                what = self.det.step(frame, last)
                if what:
                    snap = frame.copy(); box = self.det.box_in_frame(frame)
                    if box and what == "delivered":
                        x, y, w, h = box; cv2.rectangle(snap, (x, y), (x + w, y + h), (0, 200, 255), 3)
                    self.event.emit(what, snap)
            cap.release()
            if self.running: self.state.emit("Porch camera reconnecting…"); time.sleep(5)

    def stop(self):
        self.running = False; self.wait(3000)
