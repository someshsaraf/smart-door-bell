"""Bluetooth speaker handling through bluetoothctl (BlueZ) and wpctl (PipeWire).

All commands run on one worker thread, one job at a time, so the UI never
blocks on a slow pair/connect. Results come back as Qt signals.
"""
import queue, re, subprocess, time
from PySide6.QtCore import QThread, Signal

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02")
MAC = re.compile(r"([0-9A-F]{2}(?::[0-9A-F]{2}){5})")

def run(*cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return ANSI.sub("", r.stdout + r.stderr)
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)

def sinks():
    """[(id, name, is_default)] from `wpctl status`."""
    out, found, inside = run("wpctl", "status", timeout=5), [], False
    for line in out.splitlines():
        if "Sinks:" in line: inside = True; continue
        if inside and ("Sources:" in line or "├─" in line or "└─" in line): break
        m = re.search(r"(\*)?\s*(\d+)\.\s+(.+?)\s+\[vol", line) if inside else None
        if m: found.append((m.group(2), m.group(3).strip(), bool(m.group(1))))
    return found

class Bluetooth(QThread):
    devices = Signal(list)   # [{"mac", "name", "paired", "connected"}]
    status = Signal(str)     # progress / result text for the user
    output = Signal(str, int)  # current audio output name, volume 0-100

    def __init__(self):
        super().__init__(); self.jobs = queue.Queue(); self.start()

    def request(self, job, mac=None, value=None):
        self.jobs.put((job, mac, value))

    def run(self):
        while True:
            job, mac, value = self.jobs.get()
            if job == "quit": return
            try: getattr(self, "_" + job)(mac, value)
            except Exception as e: self.status.emit(f"Bluetooth error: {e}")
            if job not in ("volume", "output", "list"): self._list()
            self._output()

    # ---- jobs ----
    def _scan(self, mac, value):
        self.status.emit("Searching for 12 s… put the speaker in pairing mode")
        run("bluetoothctl", "power", "on", timeout=5)
        run("bluetoothctl", "--timeout", "12", "scan", "on", timeout=20)
        self.status.emit("Search finished")

    def _connect(self, mac, value):
        info = run("bluetoothctl", "info", mac, timeout=5)
        name = self._name(info, mac)
        if "Paired: yes" not in info:
            self.status.emit(f"Pairing with {name}…")
            out = run("bluetoothctl", "--agent", "NoInputNoOutput", "--timeout", "25", "pair", mac, timeout=35)
            if "Paired: yes" not in run("bluetoothctl", "info", mac, timeout=5):
                self.status.emit(f"Pairing failed: {self._reason(out)}. Is the speaker in pairing mode?"); return
        run("bluetoothctl", "trust", mac, timeout=5)  # lets it reconnect by itself later
        self.status.emit(f"Connecting to {name}…")
        out = run("bluetoothctl", "--timeout", "20", "connect", mac, timeout=30)
        if "Connected: yes" not in run("bluetoothctl", "info", mac, timeout=5):
            self.status.emit(f"Connection failed: {self._reason(out)}"); return
        self.status.emit(f"Connected to {name}" + ("" if self._use_sink(name) else " (sound output not switched; see wpctl status)"))

    def _reconnect(self, mac, value):
        """Saved speaker at start-up: connect quietly if it is on."""
        if mac and "Connected: yes" not in run("bluetoothctl", "info", mac, timeout=5):
            run("bluetoothctl", "--timeout", "10", "connect", mac, timeout=15)
            if "Connected: yes" in run("bluetoothctl", "info", mac, timeout=5):
                self._use_sink(self._name(run("bluetoothctl", "info", mac, timeout=5), mac))

    def _disconnect(self, mac, value):
        run("bluetoothctl", "disconnect", mac, timeout=10); self.status.emit("Disconnected")

    def _forget(self, mac, value):
        run("bluetoothctl", "remove", mac, timeout=10); self.status.emit("Speaker removed")

    def _volume(self, mac, value):
        run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value / 100:.2f}", timeout=5)

    def _output(self, mac=None, value=None):
        current = next((n for _, n, d in sinks() if d), "none")
        vol = re.search(r"Volume:\s*([\d.]+)", run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@", timeout=5))
        self.output.emit(current, int(float(vol.group(1)) * 100) if vol else 0)

    # ---- helpers ----
    def _list(self, mac=None, value=None):
        found = []
        for mac in MAC.findall(run("bluetoothctl", "devices", timeout=5)):
            info = run("bluetoothctl", "info", mac, timeout=5)
            name, paired = self._name(info, mac), "Paired: yes" in info
            audio = re.search(r"Icon: audio|Audio Sink|Headset|Handsfree", info) is not None
            if (audio or paired) and name.replace("-", ":") != mac:  # skip unnamed and non-audio gadgets
                found.append({"mac": mac, "name": name, "paired": paired, "connected": "Connected: yes" in info})
        found.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
        self.devices.emit(found)

    @staticmethod
    def _name(info, mac):
        m = re.search(r"Alias:\s*(.+)", info) or re.search(r"Name:\s*(.+)", info)
        return m.group(1).strip() if m else mac

    @staticmethod
    def _reason(out):
        m = re.search(r"Failed to \w+:?\s*(.+)", out)
        return m.group(1).strip() if m else "no answer"

    def _use_sink(self, name):
        """Makes the speaker the default output; its sink appears a moment after connecting."""
        for _ in range(16):
            for sid, sname, _ in sinks():
                if name.lower() in sname.lower() or "bluez" in sname.lower():
                    run("wpctl", "set-default", sid, timeout=5); return True
            time.sleep(0.5)
        return False
