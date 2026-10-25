#!/bin/bash
# Self-hosted ntfy server on the Pi, ready for the dashboard's phone
# notifications. Run once:   sudo bash ~/Indoor/tools/setup_ntfy.sh
#
# - installs ntfy from its official apt repository
# - serves it on port 2586, reachable over Tailscale and the home LAN
# - nobody can read or post without a login (auth-default-access: deny-all)
# - creates the logins "phone" (read doorbell-* topics) and "dashboard"
#   (post to doorbell-* topics, with an access token)
# - writes the passwords and token to ~/ntfy-credentials.txt (only you can read it)
#
# The dashboard keeps using ntfy.sh until config.json says otherwise:
#   "notify": {"server": "http://<tailscale ip>:2586", "token": "tk_..."}
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo bash $0"; exit 1; }
OWNER="${SUDO_USER:-somesh}"
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
PORT=2586
TS_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
LAN_IP="$(ip -4 route get 8.8.8.8 2>/dev/null | grep -o 'src [0-9.]*' | cut -d' ' -f2 || true)"
BASE="http://${TS_IP:-$LAN_IP}:$PORT"

echo "== Installing ntfy"
mkdir -p /etc/apt/keyrings
curl -fsSL -o /etc/apt/keyrings/archive.heckel.io.gpg https://archive.heckel.io/apt/pubkey.txt
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/archive.heckel.io.gpg] https://archive.heckel.io/apt debian main" \
    > /etc/apt/sources.list.d/archive.heckel.io.list
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ntfy

echo "== Configuring $BASE"
[ -f /etc/ntfy/server.yml ] && cp -n /etc/ntfy/server.yml /etc/ntfy/server.yml.orig
cat > /etc/ntfy/server.yml <<EOF
# Doorbell notifications (written by Indoor/tools/setup_ntfy.sh)
base-url: "$BASE"
listen-http: ":$PORT"
cache-file: "/var/cache/ntfy/cache.db"
auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"
# iPhones only get instant pushes through ntfy.sh: it receives a hashed topic id, never the message
upstream-base-url: "https://ntfy.sh"
EOF
mkdir -p /var/cache/ntfy /var/lib/ntfy
chown -R ntfy:ntfy /var/cache/ntfy /var/lib/ntfy 2>/dev/null || true
systemctl enable ntfy >/dev/null 2>&1
systemctl restart ntfy
sleep 2
systemctl is-active --quiet ntfy || { journalctl -u ntfy -n 20 --no-pager; exit 1; }

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    echo "== Opening port $PORT for Tailscale and the LAN"
    ufw allow in on tailscale0 to any port "$PORT" proto tcp >/dev/null
    [ -n "$LAN_IP" ] && ufw allow from "${LAN_IP%.*}.0/24" to any port "$PORT" proto tcp >/dev/null
fi

echo "== Logins"
CRED="$HOME_DIR/ntfy-credentials.txt"
if ntfy user list 2>&1 | grep -q "user phone"; then
    echo "Logins already exist; passwords unchanged (see $CRED)"
else
    PHONE_PW="$(openssl rand -base64 12 | tr -d '/+=')"
    DASH_PW="$(openssl rand -base64 18 | tr -d '/+=')"
    NTFY_PASSWORD="$PHONE_PW" ntfy user add phone >/dev/null
    NTFY_PASSWORD="$DASH_PW" ntfy user add dashboard >/dev/null
    ntfy access phone 'doorbell-*' read-only >/dev/null
    ntfy access dashboard 'doorbell-*' write-only >/dev/null
    TOKEN="$(ntfy token add dashboard 2>&1 | grep -o 'tk_[A-Za-z0-9]*' | head -1)"
    umask 077
    cat > "$CRED" <<EOF
ntfy server:  $BASE
Phone login:  phone / $PHONE_PW      (ntfy app: Settings > Manage users)
Dashboard:    dashboard / $DASH_PW
Dashboard token for Indoor/config.json:
  "notify": {"server": "$BASE", "token": "$TOKEN"}
EOF
    chown "$OWNER": "$CRED"; chmod 600 "$CRED"
fi

code="$(curl -s -o /dev/null -w '%{http_code}' -d test "http://127.0.0.1:$PORT/doorbell-check" || true)"
echo "== Done. ntfy runs at $BASE (an anonymous post was answered $code: 403 means logins are enforced)."
echo "   Credentials: $CRED"
echo "   The dashboard still uses ntfy.sh."
