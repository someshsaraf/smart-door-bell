"""The dashboard in a browser: phones, tablets and laptops open http://<pi>:8080
(at home, or from anywhere over Tailscale) for the whole dashboard: the doorbell's
status, news, photos, a live camera view, ring alerts with STOP, the recordings
and the settings. Over HTTPS (Tailscale) a phone can also get ring alerts as
notifications while the page is closed (push.py).

A small threaded HTTP server inside the dashboard. It only reads the parts the
window keeps up to date (webapp.py publishes them), and hands every action to
the window's thread through a Qt signal, exactly like a tap on the screen.
Everything but the login page needs a session: the password is set under
Settings > Web access and stored only as a salted scrypt hash in secrets.json;
sessions (one per device, kept 90 days) in web_sessions.json.

The live view is MJPEG made by one shared ffmpeg from the camera's small
substream, started when the first viewer arrives and stopped after the last;
its sound, the doorbell's microphone, is MP3 from one shared encoder too."""
import hashlib, hmac, json, mimetypes, os, re, secrets, shutil, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from PySide6.QtCore import QObject, Signal
import push

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "web"
SECRETS = ROOT / "secrets.json"
SESSIONS = ROOT / "web_sessions.json"
PORT = 8080
SESSION_DAYS = 90
# files the pages use, by URL prefix (all need a session)
FILES = {"/photos/": ROOT / "assets" / "scenic", "/bells/": ROOT / "assets" / "bells",
         "/tones/": ROOT / "assets" / "tones", "/news_img/": ROOT / "news_images", "/looks/": ROOT / "assets" / "looks"}


# ---------- password and sessions ----------
def _secrets():
    try: return json.loads(SECRETS.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def set_password(password):
    data = _secrets(); salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    data["web"] = {"salt": salt.hex(), "hash": h.hex()}
    tmp = SECRETS.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(data, f, indent=1)
    tmp.replace(SECRETS)
    SESSIONS.unlink(missing_ok=True)  # a new password logs every device out


def has_password():
    return bool(_secrets().get("web", {}).get("hash"))


def check_password(password):
    w = _secrets().get("web") or {}
    if not w.get("hash"): return False
    h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(w["salt"]), n=2 ** 14, r=8, p=1)
    return hmac.compare_digest(h.hex(), w["hash"])


class Sessions:
    def __init__(self):
        self.lock = threading.Lock()
        try: self.tokens = json.loads(SESSIONS.read_text(encoding="utf-8"))
        except (OSError, ValueError): self.tokens = {}

    def new(self, device):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.tokens = {t: v for t, v in self.tokens.items() if v["expires"] > time.time()}
            self.tokens[token] = {"expires": time.time() + SESSION_DAYS * 86400, "device": device[:80]}
            self._save()
        return token

    def valid(self, token):
        with self.lock:
            if not SESSIONS.exists() and self.tokens: self.tokens = {}  # password changed: everyone logs in again
            v = self.tokens.get(token or "")
            return bool(v) and v["expires"] > time.time()

    def drop(self, token):
        with self.lock:
            self.tokens.pop(token, None); self._save()

    def _save(self):
        if not SESSIONS.exists() and not self.tokens: return
        tmp = SESSIONS.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(self.tokens, f)
        tmp.replace(SESSIONS)


# ---------- addresses ----------
_secure = {"t": 0, "url": ""}


def secure_url():
    """https://<pi>.<tailnet>.ts.net (Tailscale's name for this Pi) or "": where push alerts work.
    The page is served there by `tailscale serve`; checked at most every 10 minutes."""
    if time.time() - _secure["t"] > 600:
        _secure["t"] = time.time()
        try:
            out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=4).stdout
            name = (json.loads(out).get("Self") or {}).get("DNSName", "").rstrip(".")
            _secure["url"] = f"https://{name}" if name.endswith(".ts.net") else ""
        except (OSError, ValueError, subprocess.TimeoutExpired):
            _secure["url"] = ""
    return _secure["url"]


# ---------- live camera as MJPEG, shared by all viewers ----------
class LiveView:
    def __init__(self, url_fn):
        self.url_fn = url_fn; self.lock = threading.Lock(); self.cond = threading.Condition(self.lock)
        self.frame = None; self.seq = 0; self.viewers = 0; self.proc = None

    def _reader(self, proc):
        buf = b""
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk: break
            buf += chunk
            while True:  # JPEG frames: from FFD8 to FFD9
                a = buf.find(b"\xff\xd8"); b = buf.find(b"\xff\xd9", a + 2)
                if a < 0 or b < 0: break
                with self.cond: self.frame = buf[a:b + 2]; self.seq += 1; self.cond.notify_all()
                buf = buf[b + 2:]
            if len(buf) > 4_000_000: buf = b""
        with self.cond: self.proc = None; self.cond.notify_all()

    def join(self):
        with self.lock:
            self.viewers += 1
            if self.proc is None and shutil.which("ffmpeg"):
                url = self.url_fn()
                if url:
                    self.proc = subprocess.Popen(
                        ["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url, "-an",
                         "-vf", "scale=960:-2", "-r", "10", "-q:v", "6", "-f", "mjpeg", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def leave(self):
        with self.lock:
            self.viewers -= 1
            if self.viewers <= 0 and self.proc:
                self.proc.kill(); self.viewers = 0

    def next_frame(self, after, timeout=8):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != after or self.proc is None, timeout)
            return self.seq, self.frame


class LiveAudio:
    """The doorbell's microphone (door_audio.py) as one MP3 stream shared by all listeners. It is fed
    in real time, silence included, so a browser's player never stalls between words. It runs as far
    behind real time as the live picture does, less what the browser's player buffers itself."""
    PLAYER_BUFFER = 0.3

    def delay(self):
        return max(0.15, self.door.live_delay() - self.PLAYER_BUFFER)

    def __init__(self, door):
        self.door = door; self.lock = threading.Lock(); self.cond = threading.Condition(self.lock)
        self.listeners = 0; self.proc = None; self.chunks = []; self.seq = 0

    def join(self):
        with self.lock:
            self.listeners += 1
            if self.proc is None and self.door and shutil.which("ffmpeg"):
                self.proc = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "-",
                                              "-c:a", "libmp3lame", "-b:a", "48k", "-f", "mp3", "-flush_packets", "1", "-"],
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                threading.Thread(target=self._feed, args=(self.proc,), daemon=True).start()
                threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def leave(self):
        with self.lock:
            self.listeners -= 1
            if self.listeners <= 0 and self.proc:
                self.proc.kill(); self.proc = None; self.listeners = 0

    def _feed(self, proc):
        step = 0.02; t = time.time() - self.delay()
        while proc.poll() is None:
            target = time.time() - self.delay()
            if target - t > 0.5: t = target - step
            while t + step <= target:
                pcm, _ = self.door.pcm(t, t + step); t += step
                try: proc.stdin.write(pcm.tobytes())
                except (BrokenPipeError, OSError): return
            try: proc.stdin.flush()
            except (BrokenPipeError, OSError): return
            time.sleep(step / 2)

    def _read(self, proc):
        while True:
            data = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1024)
            if not data: break
            with self.cond:
                self.chunks = (self.chunks + [data])[-64:]; self.seq += 1; self.cond.notify_all()
        with self.cond: self.cond.notify_all()

    def next(self, after, timeout=8):
        """MP3 bytes produced after chunk number `after`: (new number, bytes or None when it ended)."""
        with self.cond:
            self.cond.wait_for(lambda: self.seq != after or self.proc is None, timeout)
            if self.proc is None: return after, None
            new = self.chunks[-min(len(self.chunks), self.seq - after):] if after else self.chunks[-1:]
            return self.seq, b"".join(new)


class Reply:
    """The answer to one action, filled in on the window's thread and awaited by the request's thread."""
    def __init__(self): self.done = threading.Event(); self.value = None

    def __call__(self, value=None):
        self.value = value if value is not None else {"ok": True}; self.done.set()


# ---------- the server ----------
class Web(QObject):
    # (what, {"data": request JSON, "reply": Reply}); handled by webapp.WebApp on the window's thread
    action = Signal(str, object)

    def __init__(self, recorder_dir, url_fn, door=None):
        super().__init__(); self.recorder_dir = Path(recorder_dir)
        self.sessions = Sessions(); self.live = LiveView(url_fn); self.live_audio = LiveAudio(door)
        self.parts = {}; self.version = 0; self.cond = threading.Condition()
        self.ring_token = None  # lets a notification's STOP work without a session, for this ring only
        self.snaps = {}  # token: (jpeg bytes, expiry), the visitor's picture shown in notifications
        self.server = None

    def publish(self, name, value):
        """Called on the window's thread whenever a part changes; browsers waiting get it at once."""
        with self.cond:
            if name in self.parts and self.parts[name][1] == value: return
            self.version += 1; self.parts[name] = (self.version, value); self.cond.notify_all()

    def changes(self, since):
        """{version, parts changed after `since`} (all of them for a new page, or after a restart)."""
        full = since <= 0 or since > self.version
        return {"version": self.version, "parts": {k: v for k, (ver, v) in self.parts.items() if full or ver > since}}

    def add_snap(self, jpeg):
        token = secrets.token_urlsafe(16); now = time.time()
        self.snaps = {t: s for t, s in self.snaps.items() if s[1] > now}
        self.snaps[token] = (jpeg, now + 900); return token

    def call(self, what, data, timeout=30):
        reply = Reply(); self.action.emit(what, {"data": data, "reply": reply})
        return reply.value if reply.done.wait(timeout) else {"ok": False, "error": "The dashboard did not answer"}

    def start(self):
        if self.server: return
        web = self
        class Handler(_Handler): pass
        Handler.web = web
        try:
            self.server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler); self.server.daemon_threads = True
        except OSError as e:
            print("Web access: port", PORT, "unavailable:", e, flush=True); self.server = None; return
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        print(f"Web access on port {PORT}", flush=True)

    def stop(self):
        if self.server:
            self.server.shutdown(); self.server.server_close(); self.server = None


class _Handler(BaseHTTPRequestHandler):
    web = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *a): pass  # quiet

    def handle(self):
        try: super().handle()
        except (BrokenPipeError, ConnectionResetError): pass  # a browser that went away mid-answer

    # -- helpers --
    def _token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "dbsession": return v
        return ""

    def _authed(self): return self.web.sessions.valid(self._token())

    def _send(self, code, body=b"", ctype="application/json", headers=None):
        if isinstance(body, (dict, list)): body = json.dumps(body).encode()
        elif isinstance(body, str): body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: return json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError: return {}

    # -- GET --
    def do_GET(self):
        url = urlparse(self.path); path = url.path
        if path in ("/", "/index.html"): return self._static("index.html")
        if re.fullmatch(r"/[a-z0-9_-]+\.(js|css|json|svg|png)", path): return self._static(path[1:])
        if path == "/api/me": return self._send(200, {"authed": self._authed(), "has_password": has_password()})
        m = re.fullmatch(r"/api/snap/([\w-]+)\.jpg", path)
        if m:  # no session: notifications fetch it; the token is unguessable and expires
            snap = self.web.snaps.get(m.group(1))
            return self._send(200, snap[0], "image/jpeg") if snap and snap[1] > time.time() else self._send(404, "")
        if not self._authed(): return self._send(401, {"error": "login"})
        if path == "/api/wait":  # long poll: returns when something changes (or after 25 s)
            since = int(parse_qs(url.query).get("v", ["0"])[0] or 0)
            with self.web.cond:
                if 0 < since <= self.web.version: self.web.cond.wait_for(lambda: self.web.version != since, 25)
                return self._send(200, self.web.changes(since))
        if path == "/api/live.mjpg": return self._live()
        if path == "/api/live_audio.mp3": return self._live_audio()
        if path == "/api/push/key":
            ok = push.available()
            return self._send(200, {"available": ok, "key": push.public_key() if ok else ""})
        if path.startswith("/media/"): return self._file(self.web.recorder_dir, path[len("/media/"):], "private, max-age=3600")
        for prefix, folder in FILES.items():
            if path.startswith(prefix): return self._file(folder, path[len(prefix):], "private, max-age=86400")
        return self._send(404, {"error": "not found"})

    do_HEAD = do_GET

    def _static(self, name):
        f = STATIC / name
        if not f.is_file(): return self._send(404, "missing")
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name.endswith(".js"): ctype = "text/javascript"
        if name.endswith(".json"): ctype = "application/manifest+json" if name == "manifest.json" else "application/json"
        self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))

    def _file(self, base, rel, cache):
        """A file under `base` (never outside it), with byte ranges (phones' video players need them)."""
        f = (base / unquote(rel)).resolve()
        if base.resolve() not in f.parents or not f.is_file(): return self._send(404, "")
        size = f.stat().st_size; ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        rng = self.headers.get("Range", "")
        start, end = 0, size - 1
        if rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            start = int(a) if a else max(0, size - int(b)); end = int(b) if a and b else size - 1
            end = min(end, size - 1)
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length)); self.send_header("Cache-Control", cache)
        if rng: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD": return
        with open(f, "rb") as fh:
            fh.seek(start); left = length
            while left > 0:
                chunk = fh.read(min(65536, left))
                if not chunk: break
                self.wfile.write(chunk); left -= len(chunk)

    def _live(self):
        live = self.web.live; live.join(); seq = 0
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "close"); self.end_headers()
            while True:
                seq, frame = live.next_frame(seq)
                if frame is None: break
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            live.leave(); self.close_connection = True

    def _live_audio(self):
        la = self.web.live_audio; la.join(); seq = 0
        try:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg"); self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close"); self.end_headers()
            while True:
                seq, data = la.next(seq)
                if data is None: break
                if data: self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            la.leave(); self.close_connection = True

    # -- POST --
    def do_POST(self):
        path = urlparse(self.path).path; data = self._body()
        if path == "/api/login":
            time.sleep(0.5)  # slows down password guessing
            if not check_password(str(data.get("password", ""))): return self._send(403, {"error": "wrong password"})
            token = self.web.sessions.new(self.headers.get("User-Agent", "browser"))
            return self._send(200, {"ok": True}, headers={"Set-Cookie": f"dbsession={token}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Strict"})
        if path == "/api/push/stop":  # STOP on a notification: the ring's own token instead of a session
            t = self.web.ring_token
            if not (t and hmac.compare_digest(str(data.get("token", "")), t)): return self._send(403, {"error": "this ring is over"})
            return self._send(200, self.web.call("stop", {"via": "notification"}))
        if not self._authed(): return self._send(401, {"error": "login"})
        if path == "/api/logout":
            self.web.sessions.drop(self._token()); return self._send(200, {"ok": True}, headers={"Set-Cookie": "dbsession=; Path=/; Max-Age=0"})
        if path == "/api/password":  # a new password, from Settings in the browser (logs every device out)
            if not check_password(str(data.get("current", ""))): return self._send(403, {"error": "The current password is wrong"})
            new = str(data.get("new", ""))
            if len(new) < 6: return self._send(400, {"error": "At least 6 characters, please"})
            set_password(new); return self._send(200, {"ok": True})
        if path == "/api/push/subscribe":
            try: push.add(data.get("subscription") or {}, data.get("name", ""))
            except ValueError as e: return self._send(400, {"error": str(e)})
            self.web.call("push_changed", {}); return self._send(200, {"ok": True})
        if path == "/api/push/remove":
            push.remove(device_id=data.get("id"), endpoint=data.get("endpoint"))
            self.web.call("push_changed", {}); return self._send(200, {"ok": True})
        if path == "/api/push/test":
            ids = [d["id"] for d in push.devices() if d["endpoint"] == data.get("endpoint")]
            if not ids: return self._send(404, {"error": "This browser is not registered"})
            return self._send(200, self.web.call("push_test", {"id": ids[0]}))
        m = re.fullmatch(r"/api/do/([a-z_]+)", path)
        if m: return self._send(200, self.web.call(m.group(1), data))
        return self._send(404, {"error": "not found"})
