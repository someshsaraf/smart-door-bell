"""The doorbell's microphone on the Pi: recorded with the camera's video and
played live while the camera view is open.

The doorbell streams 20 ms UDP packets (Outdoor/src/doorbell_listen.h): a
session id, the number of the packet's first sample, and 16 kHz mono 16-bit
PCM. On a press it starts by itself, beginning 3 s before the press; for the
camera view the window asks for it over MQTT.

Keeping sound and picture in sync:
1. Every sample gets a time on the Pi's clock. Live packets arrive a few ms
   after they are recorded, so for each session the smallest
   (arrival - sample / 16000) is the moment of its sample 0 (the pre-press
   history, sent in a burst, arrives later and never lowers it). Lost, late
   or repeated packets land exactly where they belong.
2. The camera's picture reaches the Pi late (recorder.LAG_S), and the
   doorbell's microphone path adds its own small delay. The camera's own
   microphone is in step with its picture, so on each recording the doorbell
   audio is matched against it (loudness over time, cross-correlated): the
   lag found moves the doorbell audio onto the picture. Confident lags are
   remembered (door_audio_sync.json) and used when a clip has too little
   sound to measure, and for the live delay."""
import json, os, socket, statistics, struct, subprocess, threading, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
SYNC = ROOT / "door_audio_sync.json"
PORT = 5006
RATE = 16000
HEADER = 12
PACKET = 640  # bytes of PCM: 20 ms
KEEP_S = 300  # sessions kept this long after their last packet
LIVE_DELAY = 0.65  # the wall's live picture is about this much behind real time (camera + decoding)


class Session:
    def __init__(self, sample):
        self.anchor = None  # Pi time of sample 0
        self.chunks = {}    # first sample: PCM bytes; a session's packets are PACKET // 2 samples apart
        self.base = sample % (PACKET // 2)
        self.lo = self.hi = sample  # first samples of the oldest and newest packet kept
        self.last = 0.0     # Pi time of the newest packet


class DoorAudio:
    def __init__(self):
        self.lock = threading.Lock(); self.sessions = {}; self.listeners = []
        self.offsets = self._load()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind(("", PORT)); threading.Thread(target=self._rx, daemon=True).start()
        except OSError as e:
            print("Door audio: port", PORT, "unavailable:", e, flush=True)

    # ---------- receiving ----------
    def _rx(self):
        while True:
            try: data, _ = self.sock.recvfrom(2048)
            except OSError: return
            now = time.time()
            if len(data) != HEADER + PACKET or data[:4] != b"DBA1": continue
            sid, sample = struct.unpack_from("<II", data, 4); pcm = data[HEADER:]
            with self.lock:
                s = self.sessions.get(sid)
                if s is None:
                    s = self.sessions[sid] = Session(sample)
                    self.sessions = {k: v for k, v in self.sessions.items() if now - v.last < KEEP_S or k == sid}
                a = now - (sample + PACKET // 2) / RATE
                if s.anchor is None or a < s.anchor: s.anchor = a
                s.chunks[sample] = pcm; s.last = now; s.lo = min(s.lo, sample); s.hi = max(s.hi, sample)
                if len(s.chunks) > KEEP_S * 50: s.chunks.pop(s.lo, None); s.lo += PACKET // 2
                start = s.anchor + sample / RATE
                listeners = list(self.listeners)
            for fn in listeners:
                try: fn(start, pcm)
                except Exception: pass

    def receiving(self, within=3.0):
        """True while packets come in."""
        with self.lock: return any(time.time() - s.last < within for s in self.sessions.values())

    def subscribe(self, fn):
        """fn(Pi time of the packet's first sample, PCM) for every packet as it arrives."""
        with self.lock: self.listeners.append(fn)

    def unsubscribe(self, fn):
        with self.lock:
            if fn in self.listeners: self.listeners.remove(fn)

    def pcm(self, t0, t1):
        """16 kHz mono int16 samples for Pi times t0..t1 (silence where nothing arrived), and the
        share of that time that is covered by real audio."""
        n = max(0, int(round((t1 - t0) * RATE))); out = np.zeros(n, np.int16); have = 0; step = PACKET // 2
        with self.lock:
            for s in self.sessions.values():
                if s.anchor is None: continue
                k0 = int(((t0 - s.anchor) * RATE - s.base) // step) - 1; k1 = int(((t1 - s.anchor) * RATE - s.base) // step) + 1
                k0 = max(k0, (s.lo - s.base) // step); k1 = min(k1, (s.hi - s.base) // step)
                for k in range(k0, k1 + 1):
                    first = s.base + k * step; pcm = s.chunks.get(first)
                    if pcm is None: continue
                    i = int(round((s.anchor + first / RATE - t0) * RATE))
                    if i >= n or i + PACKET // 2 <= 0: continue
                    a = np.frombuffer(pcm, np.int16)
                    lo, hi = max(0, i), min(n, i + len(a))
                    out[lo:hi] = a[lo - i:hi - i]; have += hi - lo
        return out, (min(1.0, have / n) if n else 0.0)

    # ---------- sync ----------
    def _load(self):
        try: return json.loads(SYNC.read_text())["offsets"][-9:]
        except (OSError, ValueError, KeyError): return []

    def offset(self):
        """Seconds to move the doorbell audio later to match the camera's picture (remembered)."""
        return statistics.median(self.offsets) if self.offsets else 0.0

    def remember(self, lag):
        self.offsets = (self.offsets + [round(lag, 3)])[-9:]
        try:
            tmp = SYNC.with_suffix(".tmp"); tmp.write_text(json.dumps({"offsets": self.offsets})); tmp.replace(SYNC)
        except OSError: pass

    def live_delay(self):
        return max(0.2, min(2.0, LIVE_DELAY + self.offset()))


def envelope(x, rate, step=0.01):
    """Loudness over time, every `step` s: log energy, without its average."""
    n = int(rate * step); m = len(x) // n
    if m == 0: return np.zeros(0)
    e = np.log10((x[:m * n].astype(np.float64).reshape(m, n) ** 2).mean(axis=1) + 1.0)
    return e - e.mean()


def find_lag(door, door_rate, cam, cam_rate, margin):
    """How many seconds later the doorbell audio must go to line up with the camera's: `door`
    starts `margin` s earlier and ends `margin` s later than `cam`. (lag, confidence) or (None, z):
    the doorbell audio for camera time 0..L is then door audio at Pi time cs - lag .. cs - lag + L."""
    d, c = envelope(door, door_rate), envelope(cam, cam_rate)
    k = int(round(margin / 0.01))
    if len(c) < 100 or len(d) < len(c) + k or c.std() < 0.05 or d.std() < 0.05: return None, 0.0
    scores = []
    for shift in range(0, 2 * k + 1):  # door[shift : shift + len(c)] against cam
        w = d[shift:shift + len(c)]
        if len(w) < len(c): break
        scores.append(float(np.dot(w - w.mean(), c) / (np.linalg.norm(w - w.mean()) * np.linalg.norm(c) + 1e-9)))
    if not scores: return None, 0.0
    best = int(np.argmax(scores)); s = np.array(scores)
    # confidence: how far the best match stands above the best one at least 0.15 s away from it
    far = np.concatenate([s[:max(0, best - 15)], s[best + 16:]])
    z = float(s[best] - (far.max() if len(far) else 0.0))
    # door[best] lines up with cam[0]. Without any offset it would be door[margin]; matching earlier
    # means the doorbell's timestamps run ahead of the picture by the difference.
    lag = margin - best * 0.01
    return (lag, z) if s[best] > 0.3 and z > 0.08 else (None, z)


# ---------- live playback on the Pi's speaker ----------
class LivePlayer:
    """Plays the doorbell's microphone on the speaker, `delay` s behind real time so it matches the
    camera picture on the screen. Missing packets become silence; nothing piles up. The player's own
    buffer (generous, for Bluetooth speakers, which also play the chime alongside) is part of that delay."""
    BUFFER = 0.2

    def __init__(self, source):
        self.source = source; self.proc = None; self.stop_evt = threading.Event()

    @property
    def active(self): return self.proc is not None

    def start(self):
        if self.proc: return
        self.stop_evt.clear()
        self.proc = subprocess.Popen(["pw-play", "--raw", "--rate", str(RATE), "--channels", "1", "--format", "s16", "--latency", f"{int(self.BUFFER * 1000)}ms", "-"],
                                     stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._run, args=(self.proc,), daemon=True).start()

    def _run(self, proc):
        step = 0.02; ahead = lambda: max(0.1, self.source.live_delay() - self.BUFFER)
        t = time.time() - ahead()
        while not self.stop_evt.is_set():
            target = time.time() - ahead()
            if target - t > 0.5: t = target - step  # fell behind (busy Pi): skip, never lag further
            while t + step <= target:
                chunk, _ = self.source.pcm(t, t + step); t += step
                try: proc.stdin.write(chunk.tobytes())
                except (BrokenPipeError, OSError): return
            try: proc.stdin.flush()
            except (BrokenPipeError, OSError): return
            time.sleep(step / 2)

    def stop(self):
        self.stop_evt.set()
        if self.proc:
            try: self.proc.kill(); self.proc.wait(2)
            except Exception: pass
            try: self.proc.stdin.close()  # now, not when collected: unwritten bytes would fail noisily then
            except OSError: pass
            self.proc = None


def play_file_audio(path):
    """The sound of a recording on the speaker (the wall's player shows its picture)."""
    dec = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn", "-f", "s16le", "-ar", "48000", "-ac", "2", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    play = subprocess.Popen(["pw-play", "--raw", "--rate", "48000", "--channels", "2", "--format", "s16", "--latency", "80ms", "-"],
                            stdin=dec.stdout, stderr=subprocess.DEVNULL)
    dec.stdout.close()
    return dec, play
