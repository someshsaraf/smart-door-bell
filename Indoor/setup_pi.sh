#!/bin/bash
# Sets up (or updates) the indoor Raspberry Pi from a clone of this repository:
#
#   git clone https://github.com/someshsaraf/smart-door-bell.git
#   bash smart-door-bell/Indoor/setup_pi.sh
#
# 1. system packages (Qt, OpenCV, pygame, MQTT broker, ffmpeg)       - asks for sudo
# 2. the dashboard into ~/Indoor (your settings, camera login, keys and
#    recordings there are kept; only the program files are replaced)
# 3. ~/Indoor/.venv with the voice, market and web packages (faster-whisper, yfinance, qrcode, pywebpush)
# 4. the MQTT broker: encrypted for the doorbell when ~/Indoor/mqtt_psk.txt exists
#    (made on the PC by Outdoor/tools/make_psk.py), plain otherwise   - asks for sudo
# 5. start at every boot, and (re)start the dashboard now
# Safe to run again after a git pull: that is how the Pi is updated.
set -e
src=$(cd "$(dirname "$0")" && pwd)
dst="$HOME/Indoor"

echo "== 1/5 system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore \
    python3-pygame python3-opencv python3-paho-mqtt python3-numpy python3-venv \
    mosquitto mosquitto-clients ffmpeg

echo "== 2/5 dashboard files -> $dst"
if [ "$src" != "$dst" ]; then
    mkdir -p "$dst"
    # program files only; per-Pi state stays (see .gitignore: settings, secrets, keys, recordings, caches)
    rsync -a --exclude settings.json --exclude secrets.json --exclude mqtt_psk.txt --exclude news_cache.json \
          --exclude 'app.log*' --exclude recordings/ --exclude visitors/ --exclude models/ --exclude .venv/ \
          --exclude news_images/ --exclude markets_tokens.json --exclude web_sessions.json --exclude web_push.json --exclude web_push_key.pem \
          --exclude 'assets/tones/mine/' --exclude __pycache__/ "$src/" "$dst/"
    [ -f "$dst/mqtt_psk.txt" ] || { [ -f "$src/mqtt_psk.txt" ] && cp "$src/mqtt_psk.txt" "$dst/" && chmod 600 "$dst/mqtt_psk.txt"; } || true
fi

echo "== 3/5 voice, market and web packages (~/Indoor/.venv)"
[ -d "$dst/.venv" ] || python3 -m venv --system-site-packages "$dst/.venv"
"$dst/.venv/bin/pip" install -q --upgrade faster-whisper yfinance qrcode pywebpush

echo "== 4/5 MQTT broker"
if [ -f "$dst/mqtt_psk.txt" ]; then
    sudo bash "$dst/tools/setup_mqtt_tls.sh"   # encrypted listener for the doorbell; plain 1883 kept until --lock
else
    echo "   no ~/Indoor/mqtt_psk.txt: plain MQTT on 1883 (copy the key from the PC and run this again for encryption)"
    printf 'listener 1883\nallow_anonymous true\n' | sudo tee /etc/mosquitto/conf.d/doorbell.conf >/dev/null
    sudo systemctl restart mosquitto
fi
# ufw is in /usr/sbin, which a normal user's PATH may lack: ask through sudo
if sudo sh -c 'command -v ufw' >/dev/null && sudo ufw status | grep -q "Status: active"; then
    net="$(ip -4 route get 8.8.8.8 | grep -o 'src [0-9.]*' | cut -d' ' -f2 | cut -d. -f1-3).0/24"
    sudo ufw allow from "$net" to any port 1883 proto tcp >/dev/null
    # web access (Settings > Web access): the home network and Tailscale only
    sudo ufw allow from "$net" to any port 8080 proto tcp >/dev/null
    ip link show tailscale0 >/dev/null 2>&1 && sudo ufw allow in on tailscale0 to any port 8080 proto tcp >/dev/null
fi

echo "== 5/5 start at boot, and start now"
sh "$dst/autostart/install.sh"
pkill -f '^(\.venv/bin/)?python3 app\.py' || true
sleep 2
(cd "$dst" && setsid nohup autostart/start.sh >/dev/null 2>&1 </dev/null &)
echo "Done. The dashboard starts in a few seconds; logs: $dst/app.log"
