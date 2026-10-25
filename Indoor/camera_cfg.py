"""The VIGI camera's address and login, set on the Settings > Camera page.

Stored in secrets.json next to this file (git-ignored, readable only by the
Pi's user), never in config.json:
    {"camera": {"ip": "192.168.1.50", "port": 554, "user": "admin", "password": "...",
                "main": "stream1", "sub": "stream2"}}
VIGI cameras serve the full picture on /stream1 and a small one on /stream2."""
import json, os, socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

SECRETS = Path(__file__).resolve().parent / "secrets.json"
DEFAULTS = {"ip": "", "port": 554, "user": "admin", "password": "", "main": "stream1", "sub": "stream2"}


def load():
    try: cam = json.loads(SECRETS.read_text(encoding="utf-8")).get("camera", {})
    except (OSError, ValueError): cam = {}
    return {**DEFAULTS, **cam}


def save(cam):
    try: data = json.loads(SECRETS.read_text(encoding="utf-8"))
    except (OSError, ValueError): data = {}
    data["camera"] = {k: cam.get(k, v) for k, v in DEFAULTS.items()}
    tmp = SECRETS.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never readable by others, even briefly
    with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(data, f, indent=1)
    tmp.replace(SECRETS)


def url(cam=None, which="main", hide=False):
    """rtsp://user:pass@ip:port/stream1 (the password masked with `hide`), or "" when no IP is set."""
    cam = cam or load()
    if not cam.get("ip"): return ""
    login = ""
    if cam.get("user"):
        login = quote(cam["user"], safe="") + (":" + ("•" * 6 if hide else quote(cam.get("password", ""), safe=""))) + "@"
    return f"rtsp://{login}{cam['ip']}:{int(cam.get('port') or 554)}/{cam.get(which) or DEFAULTS[which]}"


def reachable(ip, port, timeout=2.0):
    try:
        with socket.create_connection((ip, int(port)), timeout): return True
    except OSError: return False


def test(cam, cv2):
    """(True, BGR frame) or (False, reason) for the main stream; takes a few seconds."""
    if not cam.get("ip"): return False, "Enter the camera's IP address"
    if not reachable(cam["ip"], cam.get("port") or 554):
        return False, f"No camera answers at {cam['ip']}:{cam.get('port') or 554} (address, cable or power?)"
    if cv2 is None: return False, "OpenCV missing: sudo apt install python3-opencv"
    cap = cv2.VideoCapture(url(cam), cv2.CAP_FFMPEG,
                           [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000])
    try:
        ok, frame = cap.read() if cap.isOpened() else (False, None)
    finally:
        cap.release()
    if not ok: return False, "The camera answers but refused the stream: check username, password and stream name"
    return True, frame


PROBE = ('<?xml version="1.0" encoding="UTF-8"?>'
         '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
         'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
         'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
         'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
         '<e:Header><w:MessageID>uuid:{id}</w:MessageID>'
         '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
         '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
         '</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>')


def identify(ip, wait=1.5):
    """The camera's own name ("VIGI C330I") from an ONVIF WS-Discovery probe sent
    straight to it, or "" if it does not answer. (A multicast probe would reach
    every camera at once, but the Pi's firewall drops the replies to it.)"""
    import re, uuid
    from urllib.parse import unquote
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(wait); s.sendto(PROBE.format(id=uuid.uuid4()).encode(), (ip, 3702))
        text = s.recvfrom(65535)[0].decode("utf-8", "replace")
    except OSError:
        return ""
    finally:
        s.close()
    names = []
    for key in ("hardware", "name"):  # usually the model; "name" may be a label set in the camera
        m = re.search(rf"onvif://www\.onvif\.org/{key}/([^\s<]+)", text)
        n = unquote(m.group(1)).replace("-", " ").replace("_", " ") if m else ""
        if n and n not in names: names.append(n)
    return " · ".join(names) or "ONVIF camera"


def find_cameras(timeout=0.4):
    """[(ip, description)] of devices on this Pi's /24 network that serve RTSP
    (port 554), each named by asking it over ONVIF. About two seconds."""
    from settings_ui import this_ip
    me = this_ip()
    if not me: return []
    base = me.rsplit(".", 1)[0]
    hosts = [f"{base}.{i}" for i in range(1, 255) if f"{base}.{i}" != me]
    with ThreadPoolExecutor(64) as pool:
        rtsp = [h for h in pool.map(lambda h: h if reachable(h, 554, timeout) else None, hosts) if h]
        names = list(pool.map(identify, rtsp))
    cams = [(ip, name or "RTSP device") for ip, name in zip(rtsp, names)]
    return sorted(cams, key=lambda c: c[1] == "RTSP device")  # named cameras first
