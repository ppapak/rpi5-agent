#!/bin/bash
# ============================================================
# Remove the services and the whole install directory.
# Copied to $BASE_DIR/uninstall.sh by scripts/install.sh, and deletes the
# directory it is sitting in.
# ============================================================
set -uo pipefail

BASE_DIR="$(dirname "$(realpath "$0")")"

echo "--- Removing Native-AI from $BASE_DIR ---"
read -r -p "This deletes $BASE_DIR including workspace/ and .env. Continue? [y/N] " reply
[[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

sudo systemctl stop voice-assistant llama-server 2>/dev/null || true
sudo systemctl disable voice-assistant llama-server 2>/dev/null || true
sudo rm -f /etc/systemd/system/voice-assistant.service
sudo rm -f /etc/systemd/system/llama-server.service
sudo systemctl daemon-reload

sudo rm -f /tmp/assistant_beep.wav

if [ -d "$BASE_DIR" ]; then
    echo "Deleting $BASE_DIR..."
    rm -rf "$BASE_DIR"
fi

echo "--- REMOVAL COMPLETE ---"
echo "System-level changes from system-setup.sh (/etc/asound.conf, config.txt) are left in place."
