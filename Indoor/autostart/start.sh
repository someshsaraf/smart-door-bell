#!/bin/sh
# Starts the indoor dashboard in the desktop session and restarts it if it crashes.
# A clean exit (window closed, or `kill` / SIGTERM) leaves it stopped.
cd "$(dirname "$0")/.." || exit 1

# Only one dashboard at a time: two would keep kicking each other off MQTT.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/indoor-dashboard.lock"
flock -n 9 || exit 0

export QT_QPA_PLATFORM=xcb  # Qt's Wayland plugin is not installed; XWayland works
export DOORBELL_FULLSCREEN=1
sleep 5  # let the desktop, audio (PipeWire) and Bluetooth finish starting

while :; do
    [ -f app.log ] && [ "$(stat -c %s app.log)" -gt 1000000 ] && mv app.log app.log.old
    python3 app.py >> app.log 2>&1
    rc=$?
    [ "$rc" -eq 0 ] && break
    echo "$(date '+%F %T') dashboard exited with code $rc, restarting in 5 s" >> app.log
    sleep 5
done
