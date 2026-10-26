"""Ring alerts on phones and laptops through Web Push: the browser's own push
service (Google's for Chrome/Android, Apple's for Safari/iPhone, Mozilla's for
Firefox) wakes the doorbell page's service worker, which shows a notification
with a STOP button, even when the page is closed.

Browsers only allow this on a secure (HTTPS) page, so phones subscribe on the
Tailscale HTTPS address (`tailscale serve`), not on http://<pi>:8080. The
payload is end-to-end encrypted to each device; the push services see only
its size and time. Our signing key (VAPID) is made on first use and kept in
web_push_key.pem, the devices in web_push.json (both readable by nobody else).
Needs the pywebpush package (in ~/Indoor/.venv, see setup_pi.sh)."""
import base64, json, os, secrets, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY = ROOT / "web_push_key.pem"
DEVICES = ROOT / "web_push.json"
lock = threading.Lock()
pool = ThreadPoolExecutor(4)


def available():
    try:
        import pywebpush  # noqa: F401
        return True
    except ImportError:
        return False


def _private_write(path, text):
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(text)
    tmp.replace(path)


def _vapid():
    from py_vapid import Vapid01
    with lock:
        if not KEY.exists():
            v = Vapid01(); v.generate_keys()
            from cryptography.hazmat.primitives import serialization
            pem = v.private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()).decode()
            _private_write(KEY, pem)
        return Vapid01.from_file(str(KEY))


def public_key():
    """The applicationServerKey a browser subscribes with (base64url, uncompressed point)."""
    from cryptography.hazmat.primitives import serialization
    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# ---------- devices ----------
def devices():
    try: return json.loads(DEVICES.read_text(encoding="utf-8")).get("devices", [])
    except (OSError, ValueError): return []


def _save(devs):
    _private_write(DEVICES, json.dumps({"devices": devs}, indent=1))


def add(subscription, name):
    """Registers a browser (its push subscription); the same endpoint again just renames it."""
    ep = str(subscription.get("endpoint", ""))
    keys = subscription.get("keys") or {}
    if not ep.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"): raise ValueError("bad subscription")
    with lock:
        devs = [d for d in devices() if d["endpoint"] != ep]
        devs.append({"id": secrets.token_hex(6), "endpoint": ep, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
                     "name": str(name)[:60] or "Browser", "added": time.time()})
        _save(devs)


def remove(device_id=None, endpoint=None):
    with lock: _save([d for d in devices() if d["id"] != device_id and d["endpoint"] != endpoint])


def listing():
    """What Settings shows: no keys or endpoints, only names and dates."""
    return [{"id": d["id"], "name": d["name"], "added": d["added"], "endpoint_host": d["endpoint"].split("/")[2]}
            for d in devices()]


# ---------- sending ----------
def send(payload, sub_claim, ttl=120, urgency="high", only=None):
    """Sends `payload` (a dict) to every registered device in the background.
    Devices the push service says are gone (404/410) are forgotten."""
    if not available(): return
    devs = [d for d in devices() if only is None or d["id"] == only]
    if not devs: return
    data = json.dumps(payload)

    def one(d):
        from pywebpush import webpush, WebPushException
        try:
            webpush({"endpoint": d["endpoint"], "keys": d["keys"]}, data, vapid_private_key=str(KEY),
                    vapid_claims={"sub": sub_claim}, ttl=ttl, headers={"Urgency": urgency, "Topic": "doorbell"}, timeout=10)
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410): remove(device_id=d["id"])
            print(f"Push to {d['name']} failed: {code or e}", flush=True)
        except Exception as e:
            print(f"Push to {d['name']} failed: {e}", flush=True)

    _vapid()  # makes the key on first use, before the threads read it
    for d in devs: pool.submit(one, d)
