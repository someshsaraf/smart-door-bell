"""Push notifications to phones through ntfy (https://ntfy.sh): the dashboard
posts to a topic and every phone subscribed to it in the free ntfy app gets
the alert. No account is needed; the topic name is the secret, so it is long
and random. A self-hosted ntfy server can be set in config.json, with an access token
when the server requires a login:
    "notify": {"server": "http://100.85.152.79:2586", "token": "tk_..."}"""
import ipaddress, secrets, threading, urllib.request
from urllib.parse import urlparse
from PySide6.QtCore import QObject, Signal

DEFAULT_SERVER = "https://ntfy.sh"


def new_topic():
    return "doorbell-" + secrets.token_hex(6)  # 48 random bits: not guessable


class Notifier(QObject):
    result = Signal(bool, str)  # sent?, what happened (for the settings page)

    def __init__(self, settings, server=None, token=None):
        super().__init__(); self.settings = settings; self.server = (server or DEFAULT_SERVER).rstrip("/"); self.token = token

    def topic_url(self):
        return f"{self.server}/{self.settings.get('notify_topic', '')}"

    def encryption(self):
        """How the alert travels from here to the server, in words for the settings page."""
        host = urlparse(self.server).hostname or ""
        if self.server.startswith("https://"): return "encrypted (HTTPS)"
        if host in ("localhost", "127.0.0.1"): return "stays on this Pi"
        try:
            if ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10"): return "encrypted (Tailscale)"
        except ValueError: pass
        return "NOT encrypted (plain http)"

    def send(self, title, message, tags="bell", priority="high", force=False):
        """Posts in the background; does nothing while notifications are off (unless `force`, for the test)."""
        if not self.settings.get("notify_topic") or not (force or self.settings.get("notify", False)): return
        threading.Thread(target=self._post, args=(title, message, tags, priority), daemon=True).start()

    def _post(self, title, message, tags, priority):
        headers = {"Title": title, "Tags": tags, "Priority": priority}
        if self.token: headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.topic_url(), data=message.encode("utf-8"), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r: ok = 200 <= r.status < 300
            self.result.emit(ok, "Sent" if ok else f"Server answered {r.status}")
        except Exception as e:
            self.result.emit(False, f"Not sent: {e}")
