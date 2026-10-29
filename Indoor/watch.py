"""Motion recording: watches the camera all the time for people, animals and
vehicles that move, and says when one does.

Frames: ffmpeg decodes the camera's small stream at FPS frames a second
(640 x 360) and offers them to the detector (detect.py, on the Hailo). While
the Front door view is open its own camera frames go to the detector instead,
so the small stream is paused then; their detections arrive here all the same.

What counts as movement: every detection is matched to what was seen before
(same kind, overlapping or close by). Something moves when its centre has
travelled more than MOVE (of the frame, or a share of its own size when it is
big) from where it was first seen or last moved, in at least CONFIRM frames.
So a car parked in view, or a box that flickers on a still object, never
counts; a person walking in, a dog crossing or a car driving up does. Leaves,
shadows and insects are not detected as any of these kinds in the first place."""
import shutil, subprocess, threading, time
import numpy as np
from PySide6.QtCore import QObject, Signal

FPS = 5
W, H = 640, 360
MOVE = 0.05        # of the frame's width or height
MOVE_SIZE = 0.12   # ... or of the object's own width, when that is more
CONFIRM = 3        # frames an object must be seen in before it counts
FORGET_S = 30      # what has not been seen for this long is forgotten


class Track:
    def __init__(self, d, now):
        self.kind, self.label = d["kind"], d["label"]
        self.box = d["box"]; self.anchor = centre(d["box"]); self.hits = 1; self.seen = now; self.moved = False

    def update(self, d, now):
        self.box = d["box"]; self.hits += 1; self.seen = now
        cx, cy = centre(d["box"]); ax, ay = self.anchor
        far = max(MOVE, MOVE_SIZE * (d["box"][2] - d["box"][0]))
        if abs(cx - ax) > far or abs(cy - ay) > far:
            self.anchor = (cx, cy); return True
        return False


def centre(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def overlap(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy; union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class Watcher(QObject):
    moved = Signal(list)  # labels of what moved just now, e.g. ["Person"]

    def __init__(self, detector, url_fn, paused_fn):
        super().__init__()
        self.detector = detector; self.url_fn = url_fn; self.paused_fn = paused_fn
        self.tracks = []; self.proc = None; self.running = True
        detector.found.connect(self.on_found)
        threading.Thread(target=self._feed, daemon=True).start()

    # ---------- frames for the detector ----------
    def _feed(self):
        while self.running:
            url = self.url_fn()
            if not url or not shutil.which("ffmpeg") or self.paused_fn() or not self.detector.ready:
                time.sleep(1); continue
            self.proc = subprocess.Popen(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url, "-an",
                 "-vf", f"fps={FPS},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            size = W * H * 3
            while self.running and not self.paused_fn():
                data = self.proc.stdout.read(size)
                if len(data) < size: break
                self.detector.offer(np.frombuffer(data, np.uint8).reshape(H, W, 3))
            self.proc.kill(); self.proc.wait()
            if self.running and not self.paused_fn(): time.sleep(5)  # the stream broke: try again shortly

    def stop(self):
        self.running = False
        if self.proc: self.proc.kill()

    # ---------- what moved ----------
    def on_found(self, found):
        now = time.monotonic(); moved = []
        free = list(self.tracks)
        for d in found:
            best, score = None, 0.0
            for t in free:
                if t.kind != d["kind"]: continue
                s = overlap(t.box, d["box"])
                if s < 0.15:  # not overlapping: close enough to be the same thing a moment later?
                    (cx, cy), (tx, ty) = centre(d["box"]), centre(t.box)
                    s = 0.1 if abs(cx - tx) < 0.15 and abs(cy - ty) < 0.15 else 0.0
                if s > score: best, score = t, s
            if best is None:
                self.tracks.append(Track(d, now)); continue
            free.remove(best)
            if best.update(d, now): best.moved = True
            if best.moved and best.hits >= CONFIRM:
                moved.append(best.label); best.moved = False
        self.tracks = [t for t in self.tracks if now - t.seen < FORGET_S]
        if moved: self.moved.emit(sorted(set(moved)))
