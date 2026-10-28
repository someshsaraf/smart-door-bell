"""Intercom with the doorbell: 16 kHz mono 16-bit PCM over UDP, 20 ms packets
both ways on port 5004 (see topics.md). The call is opened and closed over
MQTT by the window; this module only moves the audio.

The Pi has no microphone of its own, so during a call the Bluetooth speaker
is switched to its hands-free profile (it has a microphone; phone-call
quality) and back to high-quality playback afterwards. Audio goes through
PipeWire's pw-record / pw-play, so no extra Python packages are needed."""
import re, socket, subprocess, threading, time
from PySide6.QtCore import QObject, Signal

PORT = 5004
FRAME = 640  # bytes: 20 ms at 16 kHz, 16-bit mono
PCM = ["--raw", "--rate", "16000", "--channels", "1", "--format", "s16"]  # --raw: plain samples, not a sound file


def run(*cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired): return ""


def section_ids(status, section, name):
    """Ids of the lines naming `name` in one section of `wpctl status`."""
    m = re.search(section + r":(.*?)(?:\n │\s*\n|\n └)", status, re.S)
    return re.findall(r"(\d+)\.\s+" + re.escape(name), m.group(1)) if m else []


def profiles(dev):
    """{profile name: index} of a PipeWire device."""
    out, found, idx = run("pw-cli", "enum-params", str(dev), "EnumProfile"), {}, None
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if "Profile:index" in line and i + 1 < len(lines): idx = lines[i + 1].split()[-1]
        if "Profile:name" in line and i + 1 < len(lines) and idx is not None:
            found[lines[i + 1].split('"')[1] if '"' in lines[i + 1] else lines[i + 1].split()[-1]] = idx
    return found


class Intercom(QObject):
    state = Signal(str)  # what the call is doing, for the ring page
    ended = Signal()

    def __init__(self):
        super().__init__(); self.active = False; self.stop_evt = threading.Event()

    def start(self, door_ip, speaker_name):
        if self.active: return
        self.active = True; self.stop_evt.clear()
        threading.Thread(target=self._run, args=(door_ip, speaker_name), daemon=True).start()

    def stop(self):
        self.stop_evt.set()

    # -- Bluetooth hands-free --
    def _headset(self, name):
        """Switches the speaker to hands-free. Returns (device, profile to restore) or (None, None)."""
        if not name: return None, None
        devs = section_ids(run("wpctl", "status"), "Devices", name)
        if not devs: return None, None
        dev = devs[0]; prof = profiles(dev)
        hs = next((i for n, i in prof.items() if n.startswith("headset-head-unit")), None)
        if hs is None: return None, None
        cur = re.findall(r'String "([^"]+)"', run("pw-cli", "enum-params", dev, "Profile"))
        back = prof.get(cur[0] if cur and cur[0] in prof else "a2dp-sink", prof.get("a2dp-sink"))
        run("wpctl", "set-profile", dev, hs)
        return dev, back

    def _nodes(self, name):
        """(sink id, source id) of the speaker once the profile has switched (waits up to 4 s)."""
        for _ in range(20):
            st = run("wpctl", "status")
            sinks, sources = section_ids(st, "Sinks", name), section_ids(st, "Sources", name)
            if sinks and sources: return sinks[0], sources[0]
            time.sleep(0.2)
        st = run("wpctl", "status")
        return (section_ids(st, "Sinks", name) or [None])[0], None

    def _run(self, door_ip, name):
        dev = back = sock = rec = play = None
        try:
            self.state.emit("Connecting…")
            dev, back = self._headset(name)
            sink, source = self._nodes(name) if dev else (None, None)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); sock.bind(("", PORT)); sock.settimeout(0.3)
            play = subprocess.Popen(["pw-play", *PCM, "--latency", "60ms", *(["--target", sink] if sink else []), "-"],
                                    stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if source:
                rec = subprocess.Popen(["pw-record", *PCM, "--latency", "20ms", "--target", source, "-"],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            threading.Thread(target=self._send, args=(sock, rec, door_ip), daemon=True).start()
            note = "" if source else " · no microphone: listening only"
            self.state.emit("Calling the door…" + note)
            heard = False; last = time.monotonic()
            while not self.stop_evt.is_set():
                try: data, addr = sock.recvfrom(2048)
                except socket.timeout:
                    if heard and time.monotonic() - last > 5: self.state.emit("Door not answering…" + note); heard = False
                    continue
                if addr[0] != door_ip: continue
                if not heard: self.state.emit("Talking" + note); heard = True
                last = time.monotonic()
                try: play.stdin.write(data); play.stdin.flush()
                except (BrokenPipeError, OSError): break
        except Exception as e:
            self.state.emit(f"Call failed: {e}")
        finally:
            self.stop_evt.set()
            for p in (rec, play):
                if p:
                    try: p.kill(); p.wait(2)
                    except Exception: pass
            if sock: sock.close()
            if dev and back: run("wpctl", "set-profile", dev, back)  # back to high-quality playback
            self.active = False; self.ended.emit()

    def _send(self, sock, rec, door_ip):
        """Microphone to the door; without one, a quiet packet every second keeps the call open."""
        while not self.stop_evt.is_set():
            if rec:
                data = rec.stdout.read(FRAME)
                if not data: break
            else:
                data = bytes(FRAME); time.sleep(1)
            try: sock.sendto(data, (door_ip, PORT))
            except OSError: time.sleep(0.2)
