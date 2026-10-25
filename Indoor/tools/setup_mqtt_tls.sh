#!/bin/bash
# Encrypted MQTT between the doorbell and this Pi's Mosquitto broker.
#
#   sudo bash ~/Indoor/tools/setup_mqtt_tls.sh          # step 1: add the encrypted listener
#   sudo bash ~/Indoor/tools/setup_mqtt_tls.sh --lock   # step 2, once the doorbell connects encrypted
#
# The doorbell talks TLS 1.2 with a pre-shared key (PSK) on port 8883: no
# certificates, so it works before the doorbell's clock is set and whatever
# address the Pi has, and only a doorbell holding the key gets in. The key
# comes from ~/Indoor/mqtt_psk.txt ("identity:hex key"), written on the PC
# together with Outdoor/src/doorbell_secret.h, which the firmware is built with.
#
# Step 1 keeps plain MQTT on 1883 open as before, so the doorbell keeps working
# until it runs the encrypted firmware. Step 2 (--lock) limits 1883 to this Pi
# itself: the dashboard connects to 127.0.0.1, so its traffic never leaves the
# Pi, and nothing on the network can use plain MQTT any more.
#
# The doorbell's key may only use home/doorbell/... topics (an ACL), so a key
# read out of a stolen doorbell cannot reach anything else on the broker.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo bash $0 ${1:-}"; exit 1; }
LOCK=false
[ "${1:-}" = "--lock" ] && LOCK=true
OWNER="${SUDO_USER:-somesh}"
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
PSK_SRC="$HOME_DIR/Indoor/mqtt_psk.txt"
CONF=/etc/mosquitto/conf.d/doorbell.conf
LAN_IP="$(ip -4 route get 8.8.8.8 2>/dev/null | grep -o 'src [0-9.]*' | cut -d' ' -f2 || true)"
LAN="${LAN_IP%.*}.0/24"

[ -f "$PSK_SRC" ] || { echo "$PSK_SRC is missing: it is written on the PC with the firmware's key."; exit 1; }
LINE="$(head -1 "$PSK_SRC" | tr -d '\r\n ')"
ID="${LINE%%:*}"
KEY="${LINE#*:}"
[[ "$ID" =~ ^[A-Za-z0-9_-]+$ && "$KEY" =~ ^[0-9a-f]{32,64}$ ]] || { echo "$PSK_SRC is not 'identity:hexkey'"; exit 1; }

echo "== Key and access rules"
printf '%s:%s\n' "$ID" "$KEY" > /etc/mosquitto/doorbell_psk
cat > /etc/mosquitto/doorbell_acl <<EOF
# Written by Indoor/tools/setup_mqtt_tls.sh
# Clients without a key: the dashboard on this Pi (only it, after --lock).
topic readwrite #

# The doorbell, identified by its TLS key: its own topics only.
user $ID
topic readwrite home/doorbell/#
EOF
chown root:mosquitto /etc/mosquitto/doorbell_psk /etc/mosquitto/doorbell_acl
chmod 640 /etc/mosquitto/doorbell_psk /etc/mosquitto/doorbell_acl

echo "== Broker listeners ($($LOCK && echo "1883 on this Pi only" || echo "1883 still open"), 8883 encrypted)"
[ -f "$CONF" ] && cp -n "$CONF" "$CONF.orig"
cp "$CONF" "$CONF.before" 2>/dev/null || true
if $LOCK; then PLAIN="listener 1883 127.0.0.1"; NOTE="the dashboard on this Pi only"; else
    PLAIN="listener 1883"; NOTE="the dashboard, and the doorbell until it runs the encrypted firmware (then: --lock)"; fi
cat > "$CONF" <<EOF
# Written by Indoor/tools/setup_mqtt_tls.sh
per_listener_settings false
allow_anonymous true
acl_file /etc/mosquitto/doorbell_acl

# Plain MQTT: $NOTE
$PLAIN

# Encrypted MQTT for the doorbell: TLS 1.2 with a pre-shared key
listener 8883
psk_hint doorbell
psk_file /etc/mosquitto/doorbell_psk
use_identity_as_username true
tls_version tlsv1.2
ciphers ECDHE-PSK-AES128-CBC-SHA256
EOF

systemctl restart mosquitto
sleep 2
if ! systemctl is-active --quiet mosquitto; then
    echo "!! Mosquitto did not start with the new settings; putting the previous ones back:"
    tail -n 8 /var/log/mosquitto/mosquitto.log 2>/dev/null || journalctl -u mosquitto -n 8 --no-pager
    [ -f "$CONF.before" ] && cp "$CONF.before" "$CONF" && systemctl restart mosquitto
    exit 1
fi

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    echo "== Firewall"
    ufw allow from "$LAN" to any port 8883 proto tcp >/dev/null
    $LOCK && ufw delete allow from "$LAN" to any port 1883 proto tcp >/dev/null 2>&1 || true
fi

echo "== Check: an encrypted connection with the doorbell's key"
if timeout 6 openssl s_client -connect 127.0.0.1:8883 -tls1_2 -cipher ECDHE-PSK-AES128-CBC-SHA256 \
        -psk_identity "$ID" -psk "$KEY" -brief </dev/null 2>&1 | grep -q "CONNECTION ESTABLISHED"; then
    echo "   OK: TLS-PSK on 8883 works"
else
    echo "!! The TLS check failed; see /var/log/mosquitto/mosquitto.log"; exit 1
fi
if $LOCK; then
    echo "== Done: plain MQTT is limited to this Pi; the doorbell must use 8883."
else
    echo "== Done. Flash the doorbell with the encrypted firmware; when its Indoor Unit page shows"
    echo "   'Connected', run: sudo bash $0 --lock"
fi
