"""Records clips of the camera onto the Pi's SD card under recordings/<date>/,
with a thumbnail, listed in recordings/index.json:
- "ring": when the bell rings, PRE_S seconds from before the press plus the
  length chosen under Settings > Camera (settings.json "record_seconds",
  CLIP_S by default, at most the ring's length) after it;
- "motion": when a person, animal or vehicle moves in view (watch.py),
  MOTION_PRE_S before it and MOTION_S after it, with what was seen (the
  doorbell is asked for its sound from before the movement as well).
That is possible because Buffer keeps the last minute and a half of the camera
all the time: ffmpeg copies the camera's own H.264 stream (no re-encoding: full
quality, ~1 % CPU) into short MPEG-TS segments in RAM (/dev/shm, so the SD
card is not worn by constant writing). On a press the segments around it are
joined and cut into an MP4. Segments start at the camera's key frames (every
2 s on the VIGI), so a clip can start up to one key frame earlier than asked.

Sound: the doorbell's own microphone (door_audio.py), lined up with the picture
by matching it against the camera's microphone; the camera's sound when no
doorbell audio arrived (older doorbell firmware, doorbell offline). Settings >
Camera can switch sound recording off.

Without a running buffer (camera offline, just started) the clip is recorded
straight from the camera instead, from the next key frame on. Rings are listed
even when nothing could be recorded. Old clips go after KEEP_DAYS; when the SD
card runs short of space (under MIN_FREE_GB free), the oldest motion clips go
first, and rings only when no motion clips are left."""
import json, os, shutil, signal, subprocess, threading, time
import numpy as np
from pathlib import Path
from PySide6.QtCore import QObject, Signal

DIR = Path(__file__).resolve().parent / "recordings"
BUF = Path("/dev/shm/doorbell_buffer")
CLIP_S = 5  # default length after the press; any whole number of seconds up to the ring's own length
RING_S = 30  # the doorbell's ring length until it reports its own (Settings > Outdoor unit)
PRE_S = 3   # before the press, from the buffer
LAG_S = 0.5  # the camera's picture reaches the Pi about this much behind real time
MOTION_PRE_S, MOTION_S = 5, 55  # a motion clip: before and after the movement
SEGMENTS = 45  # kept in RAM: ~1.5 minutes at the camera's 2 s key frame interval (a motion clip needs a minute)
KEEP_DAYS = 30
MIN_FREE_GB = 2  # the SD card is "full" below this
MARGIN_S = 1.5  # doorbell audio looked at around a clip, for lining it up with the picture
AUDIO = ["-c:a", "aac", "-ar", "16000", "-ac", "1", "-b:a", "48k"]  # the camera's G.711: AAC, playable everywhere


class Buffer:
    """The last minute of the camera as MPEG-TS segments in RAM, kept by one ffmpeg."""

    def __init__(self, url_fn, audio_fn=lambda: True):
        self.url_fn = url_fn; self.audio_fn = audio_fn; self.proc = None; self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            url = self.url_fn()
            if not url or not shutil.which("ffmpeg"):
                time.sleep(10); continue
            shutil.rmtree(BUF, ignore_errors=True); BUF.mkdir(parents=True, exist_ok=True)
            cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url,
                   "-map", "0:v:0", *(["-map", "0:a:0?", *AUDIO] if self.audio_fn() else []), "-c:v", "copy",
                   "-f", "segment", "-segment_time", "1", "-segment_wrap", str(SEGMENTS),
                   "-segment_list", str(BUF / "list.csv"), "-segment_list_type", "csv",
                   "-segment_list_size", str(SEGMENTS - 2), "-segment_format", "mpegts", str(BUF / "seg%02d.ts")]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            err = self.proc.communicate()[1]
            if self.running:
                print("Camera buffer stopped:", (err or "")[-200:].strip(), flush=True); time.sleep(5)

    def restart(self):
        """The camera settings changed: start again with the new address."""
        if self.proc and self.proc.poll() is None: self.proc.send_signal(signal.SIGINT)

    def stop(self):
        self.running = False; self.restart(); shutil.rmtree(BUF, ignore_errors=True)

    def segments(self):
        """[(path, start, end)] of the finished segments, oldest first, in stream seconds
        (from ffmpeg's segment list, which is written as each one finishes)."""
        try: lines = (BUF / "list.csv").read_text().split()
        except OSError: return []
        out = []
        for line in lines:
            name, start, end = line.split(",")[:3]
            out.append((BUF / name, float(start), float(end)))
        return out

    def to_stream(self, wall, segs):
        """Stream time of what the camera saw at wall-clock `wall`. The newest finished
        segment was completed when its file was last written, LAG_S after it was seen."""
        p, _, end = segs[-1]
        return end - (p.stat().st_mtime - LAG_S - wall)

    def healthy(self):
        s = self.segments()
        try: return bool(s) and time.time() - s[-1][0].stat().st_mtime < 6
        except OSError: return False

    def cut(self, t0, t1, out):
        """Joins the segments covering wall-clock t0..t1 into the MP4 `out`; waits until t1 is buffered.
        The clip starts on the key frame at or before t0 (without re-encoding it cannot start
        in between). Returns how many seconds before t0 it starts, or None on failure."""
        deadline = time.time() + (t1 - time.time()) + 10
        while time.time() < deadline:  # the moment t1 must be in a finished segment
            segs = self.segments()
            if segs and segs[-1][2] >= self.to_stream(t1, segs): break
            time.sleep(0.3)
        else:
            return None
        s0, s1 = self.to_stream(t0, segs), self.to_stream(t1, segs)
        parts = [s for s in segs if s[2] > s0 and s[1] < s1]
        if not parts: return None
        joined = BUF / f"clip_{os.getpid()}_{int(t0)}.ts"
        with open(joined, "wb") as f:  # MPEG-TS joins by plain concatenation
            for p, _, _ in parts: f.write(p.read_bytes())
        start = parts[0][1]  # a segment begins on a key frame
        try:
            r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(joined),
                                "-t", f"{s1 - start:.2f}", "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(out)],
                               capture_output=True, text=True, timeout=30)
            ok = r.returncode == 0 and out.exists() and out.stat().st_size > 10_000
            return max(0.0, s0 - start) if ok else None
        finally:
            joined.unlink(missing_ok=True)


class Recorder(QObject):
    # object, not dict: a dict signal hands receivers a copy, and they add to the entry itself (describe.py, daily.py)
    saved = Signal(object)  # a new entry: {"time", "kind", "video", "thumb", "note", "seconds", "pre", "detected"}
    # describe.py adds "about", "carrying", "role" and "who" (a close-up of the visitor) later; daily.py "milk"

    def __init__(self, url_fn, audio_fn=lambda: True, door=None):
        super().__init__(); self.lock = threading.Lock(); self.url_fn = url_fn; self.audio_fn = audio_fn; self.door = door
        DIR.mkdir(exist_ok=True); self.index = DIR / "index.json"
        try: self.entries = json.loads(self.index.read_text(encoding="utf-8"))
        except (OSError, ValueError): self.entries = []
        self.buffer = Buffer(url_fn, audio_fn)
        threading.Thread(target=self.prune, daemon=True).start()

    def record(self, kind="ring", seconds=CLIP_S, pre=PRE_S, detected=None):
        """Saves a clip around now in the background (also logs the event when there is no camera).
        `detected`: a list of what was seen, which may still grow while the clip records."""
        threading.Thread(target=self._record, args=(kind, time.time(), int(seconds), pre, detected), daemon=True).start()

    def _record(self, kind, t, seconds, pre, detected):
        lt = time.localtime(t); day = DIR / time.strftime("%Y-%m-%d", lt); day.mkdir(parents=True, exist_ok=True)
        stem = time.strftime("%H%M%S", lt) + "_" + kind
        video, thumb = day / f"{stem}.mp4", day / f"{stem}.jpg"
        entry = {"time": t, "kind": kind, "video": "", "thumb": "", "note": "", "seconds": seconds, "pre": 0}
        url = self.url_fn()
        if not url:
            entry["note"] = "No camera set up"
        elif not shutil.which("ffmpeg"):
            entry["note"] = "ffmpeg missing"
        elif self.buffer.healthy() and (extra := self.buffer.cut(t - pre, t + seconds, video)) is not None:
            entry["pre"] = round(pre + extra, 1); entry["seconds"] = round(entry["pre"] + seconds)
            if self.audio_fn() and self.door:  # the clip shows Pi times t - pre - extra onwards
                try: entry["audio"] = self._door_audio(video, t - pre - extra, pre + extra + seconds)
                except Exception as e: print("Doorbell audio not added:", e, flush=True)
        else:
            self._direct(url, seconds, video, entry)
        if video.exists() and video.stat().st_size > 10_000:
            entry["video"] = video.relative_to(DIR).as_posix()
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", str(entry["pre"] + 0.5), "-i", str(video),
                            "-frames:v", "1", "-vf", "scale=480:-2", str(thumb)], capture_output=True, timeout=20)  # the press
            if thumb.exists(): entry["thumb"] = thumb.relative_to(DIR).as_posix()
        if detected is not None: entry["detected"] = list(detected)
        with self.lock:
            self.entries.insert(0, entry); self._write()
        self.saved.emit(entry)
        self.prune()

    def _door_audio(self, video, start, length):
        """Puts the doorbell's microphone into `video` (which shows Pi times start .. start + length),
        lined up with the camera's own sound. Returns what the clip's sound is."""
        wait = start + length + MARGIN_S + 0.5 - time.time()  # the live packets up to the end are in
        if wait > 0: time.sleep(wait)
        from door_audio import PORT, RATE, find_lag
        door, covered = self.door.pcm(start - MARGIN_S, start + length + MARGIN_S)
        if covered < 0.2:
            print(f"Doorbell audio not added: only {covered:.0%} arrived (firmware, or UDP {PORT} blocked on the Pi?)", flush=True)
            return "camera"
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(video), "-vn", "-f", "s16le", "-ar", "8000", "-ac", "1", "-"],
                           capture_output=True, timeout=30)
        cam = np.frombuffer(r.stdout, np.int16) if r.returncode == 0 else np.zeros(0, np.int16)
        lag, _ = find_lag(door, RATE, cam, 8000, MARGIN_S); measured = lag is not None
        if measured: self.door.remember(lag)
        else: lag = self.door.offset()  # too little sound to measure: as usual
        lag = max(-MARGIN_S, min(MARGIN_S, lag))
        i0 = int(round((MARGIN_S - lag) * RATE)); pcm = door[i0:i0 + int(length * RATE)]
        tmp = video.with_suffix(".tmp.mp4")
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(video), "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "-",
                            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "64k", "-shortest",
                            "-movflags", "+faststart", str(tmp)], input=pcm.tobytes(), capture_output=True, timeout=60)
        if r.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True); print("Doorbell audio mux failed:", r.stderr[-200:], flush=True); return "camera"
        tmp.replace(video)
        print(f"Doorbell audio added: {covered:.0%} covered, shift {lag * 1000:+.0f} ms ({'measured' if measured else 'usual'})", flush=True)
        return "doorbell"

    def _direct(self, url, seconds, video, entry):
        """No buffer: record from the camera's next key frame on."""
        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-rtsp_transport", "tcp", "-i", url,
               "-t", str(seconds), "-map", "0:v:0", *(["-map", "0:a:0?", *AUDIO] if self.audio_fn() else []), "-c:v", "copy",
               "-movflags", "+faststart", str(video)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 20)
            if r.returncode == 0 and video.exists(): return
            err = r.stderr or ""
        except subprocess.TimeoutExpired:
            err = "timeout"
        video.unlink(missing_ok=True)
        entry["note"] = "Camera refused the login" if "401" in err else "Camera did not answer"
        print("Recording failed:", err[-300:], flush=True)

    def stop(self):
        self.buffer.stop()

    def snapshot(self, width=1280):
        """The camera's picture of a moment ago as a JPEG (from the buffer, full quality), or None."""
        segs = self.buffer.segments() if self.buffer.healthy() else []
        if not segs: return None
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-sseof", "-0.3", "-i", str(segs[-1][0]), "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "4", "-"], capture_output=True, timeout=15)
        return r.stdout if r.returncode == 0 and r.stdout else None

    def update(self, entry):
        """`entry` (one of self.entries) was given more fields: saved with the rest."""
        with self.lock:
            if any(e is entry for e in self.entries): self._write()

    def delete(self, entry):
        for key in ("video", "thumb", "who"):
            if entry.get(key): (DIR / entry[key]).unlink(missing_ok=True)
        with self.lock:
            self.entries = [e for e in self.entries if e is not entry and e != entry]; self._write()

    def delete_many(self, entries):
        for e in list(entries): self.delete(e)
        for d in DIR.iterdir():
            if d.is_dir() and not any(d.iterdir()): d.rmdir()

    def _write(self):
        tmp = self.index.with_suffix(".tmp"); tmp.write_text(json.dumps(self.entries, indent=1), encoding="utf-8")
        tmp.replace(self.index)

    def prune(self):
        """Drops clips older than KEEP_DAYS; then, while the SD card has under MIN_FREE_GB free,
        the oldest motion clip, and only when none is left the oldest ring."""
        cutoff = time.time() - KEEP_DAYS * 86400
        with self.lock: entries = sorted(self.entries, key=lambda e: e["time"])
        for e in [e for e in entries if e["time"] < cutoff]: self.delete(e)
        with self.lock: entries = sorted(self.entries, key=lambda e: (e.get("kind") != "motion", e["time"]))
        for e in entries:
            if shutil.disk_usage(DIR).free >= MIN_FREE_GB * 1e9: break
            if not e.get("video"): continue  # nothing on the card to free
            print(f"SD card nearly full: deleting the {e.get('kind', 'ring')} recording of {time.ctime(e['time'])}", flush=True)
            self.delete(e)
        for d in DIR.iterdir():
            if d.is_dir() and not any(d.iterdir()): d.rmdir()
