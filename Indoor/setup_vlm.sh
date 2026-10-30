#!/bin/sh
# Visitor descriptions (describe.py): builds llama.cpp's server on this Pi and runs a small
# vision-language model as a user service on 127.0.0.1:8090, which the dashboard asks about
# each recording. Nothing leaves the Pi once the model is downloaded.
#
#   sh setup_vlm.sh                 # Qwen2.5-VL 3B (~3 GB download, ~15 min build)
#   VLM_MODEL=ggml-org/SmolVLM2-2.2B-Instruct-GGUF sh setup_vlm.sh   # another model from Hugging Face
#
# Follow the first start (the model download) with:  journalctl --user -u doorbell-vlm -f
# The dashboard shows it under Settings > Alerts as "Ready".
set -e
MODEL=${VLM_MODEL:-ggml-org/Qwen2.5-VL-3B-Instruct-GGUF}
SRC=$HOME/llama.cpp

sudo apt-get install -y cmake build-essential git libcurl4-openssl-dev
if [ -d "$SRC" ]; then git -C "$SRC" pull --ff-only; else git clone --depth 1 https://github.com/ggml-org/llama.cpp "$SRC"; fi
cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON
nice cmake --build "$SRC/build" -j3 --target llama-server

# 3 of the 4 cores, at low priority: the dashboard and the camera always come first
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/doorbell-vlm.service" <<EOF
[Unit]
Description=Doorbell visitor descriptions (llama.cpp, $MODEL)
After=network-online.target

[Service]
ExecStart=$SRC/build/bin/llama-server -hf $MODEL --host 127.0.0.1 --port 8090 -t 3 -c 4096
Nice=10
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now doorbell-vlm
sudo loginctl enable-linger "$USER"  # runs from boot, before anyone logs in
echo "Started. The first start downloads the model: journalctl --user -u doorbell-vlm -f"
