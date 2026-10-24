#!/bin/sh
# Makes the dashboard start with the desktop after boot (current user, auto-login).
# Run once on the Pi:  sh ~/Indoor/autostart/install.sh
# Undo:                rm ~/.config/autostart/indoor-dashboard.desktop
set -e
dir=$(cd "$(dirname "$0")/.." && pwd)
chmod +x "$dir/autostart/start.sh"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/indoor-dashboard.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Indoor doorbell dashboard
Comment=Starts ~/Indoor/app.py full screen after login
Exec=$dir/autostart/start.sh
X-GNOME-Autostart-enabled=true
EOF
echo "Installed: $HOME/.config/autostart/indoor-dashboard.desktop -> $dir/autostart/start.sh"
