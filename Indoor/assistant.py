"""Voice commands for the dashboard, all on the Pi (no cloud).

listen() records from the default microphone (PipeWire) until the speaker
pauses, Whisper ("base.en", via faster-whisper on the CPU) turns it into text,
and intents.parse() maps the text to a command. The Whisper model (~140 MB) is
fetched once into models/whisper and loaded in the background at start-up.
Whisper is told the doorbell's vocabulary up front, which makes short
commands much more reliable."""
import subprocess, threading, time
from pathlib import Path
from PySide6.QtCore import QObject, Signal
import intents
try:
    import numpy as np
except ImportError:
    np = None

MODEL_DIR = Path(__file__).resolve().parent / "models" / "whisper"
RATE = 16000
CHUNK = 480            # samples: 30 ms
MAX_S, WAIT_S, PAUSE_S = 7.0, 4.0, 0.8  # longest command, give up without speech, end after this pause
HINT = ("Doorbell commands: stop the bell. Mute the bell for an hour. Show me all events. Show events from "
        "yesterday, last Monday, 20 October, this week. Play the last recording. Show the front door. Go home. Open settings.")


def _run(*cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired): return ""


def microphone():
    """(node name, description) of a real microphone, or None. Bluetooth inputs never
    count: recording from one makes the Pi switch the speaker to its hands-free mode
    (phone-call sound, drop-outs), and WirePlumber offers one even when the speaker
    is in music mode. The default input is preferred when it qualifies."""
    import re
    status = _run("wpctl", "status")
    m = re.search(r"Sources:(.*?)(?:\n │\s*\n|\n └)", status, re.S)
    ids = re.findall(r"(\*?)\s*(\d+)\.\s", m.group(1)) if m else []
    found = []
    for star, node in sorted(ids, key=lambda x: x[0] != "*"):  # the default (*) first
        info = _run("wpctl", "inspect", node)
        name = re.search(r'node\.name = "([^"]+)"', info); desc = re.search(r'node\.description = "([^"]+)"', info)
        if name and not name.group(1).startswith("bluez") and "monitor" not in name.group(1):
            found.append((name.group(1), desc.group(1) if desc else name.group(1)))
    return found[0] if found else None


class Assistant(QObject):
    state = Signal(str)                   # "listening" / "thinking" / "" (idle) / a problem, for the screen
    heard = Signal(str)                   # what Whisper understood
    command = Signal(str, object, str)    # action, its arguments, a short reply
    unknown = Signal(str)                 # understood words but no command

    def __init__(self):
        super().__init__(); self.model = None; self.busy = False; self.ready = threading.Event()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            from faster_whisper import WhisperModel
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            self.model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4,
                                      download_root=str(MODEL_DIR))
            print("Voice: Whisper ready", flush=True)
        except Exception as e:
            print("Voice: Whisper unavailable:", e, flush=True)
        self.ready.set()

    def listen(self):
        """Push-to-talk: records one command and acts on it, in the background."""
        if self.busy: return
        self.busy = True
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        try:
            if np is None: self.state.emit("Voice needs numpy"); return
            mic = microphone()
            if not mic: self.state.emit("No microphone: plug a USB microphone into the Pi"); return
            self.state.emit("listening")
            audio = self._record(mic[0])
            if audio is None: self.state.emit("Didn't hear anything"); return
            self.handle(audio)
        finally:
            self.busy = False

    def _record(self, target):
        """Float32 samples of one utterance from the microphone `target`, or None if nobody spoke."""
        p = subprocess.Popen(["pw-record", "--target", target, "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        chunks, floor, spoke, quiet_since, start = [], None, False, None, time.monotonic()
        try:
            while time.monotonic() - start < MAX_S:
                raw = p.stdout.read(CHUNK * 2)
                if len(raw) < CHUNK * 2: break
                x = np.frombuffer(raw, np.int16).astype(np.float32); chunks.append(x)
                level = float(np.sqrt(np.mean(x * x)))
                if len(chunks) <= 10:  # first 0.3 s: the room's background level
                    floor = level if floor is None else max(floor, level); continue
                loud = level > max(3.0 * floor, 300.0)
                if loud: spoke, quiet_since = True, None
                elif spoke:
                    quiet_since = quiet_since or time.monotonic()
                    if time.monotonic() - quiet_since > PAUSE_S: break
                if not spoke and time.monotonic() - start > WAIT_S: return None
        finally:
            p.kill(); p.wait(2)
        return np.concatenate(chunks) / 32768.0 if spoke else None

    def handle(self, audio):
        """Transcribes and acts (also used by the tests with recorded speech)."""
        self.state.emit("thinking")
        self.ready.wait(120)
        if not self.model: self.state.emit("Speech recognition not available"); return
        segments, _ = self.model.transcribe(audio, language="en", beam_size=1, initial_prompt=HINT,
                                            condition_on_previous_text=False)
        text = " ".join(s.text for s in segments).strip()
        self.heard.emit(text)
        result = intents.parse(text) if text else None
        if result: self.command.emit(*result)
        else: self.unknown.emit(text)
        self.state.emit("")
