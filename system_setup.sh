#!/bin/bash
set -e

# If not root, re-run with sudo automatically
if [[ $EUID -ne 0 ]]; then
   exec sudo "$0" "$@"
fi

echo "--- PHASE 1: SYSTEM UPDATES ---"
swapoff -a
apt update && apt upgrade -y
apt install -y locales-all git alsa-utils

echo "--- PHASE 2: LOCALE & SSH ---"
# Use a single sed command to handle multiple changes
sed -i -e 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen en_US.UTF-8

# Consolidate file writes
cat << 'LOCALE' > /etc/default/locale
LANG=en_US.UTF-8
LC_ALL=en_US.UTF-8
LOCALE

sed -i 's/^AcceptEnv LANG LC_*/# AcceptEnv LANG LC_*/' /etc/ssh/sshd_config

echo "--- PHASE 3: FIRMWARE & HARDWARE ---"
CONFIG_FILE="/boot/firmware/config.txt"

# Optimization: Use a temporary file to rebuild the config cleanly
# This prevents duplicate entries if the script is run multiple times.
sed -i '/dtoverlay=vc4-kms-v3d/s/$/,noaudio/' "$CONFIG_FILE"
sed -i '/dtparam=audio/d' "$CONFIG_FILE"
sed -i '/dtoverlay=rpi-codeczero/d' "$CONFIG_FILE"
sed -i '/dtparam=pciex1/d' "$CONFIG_FILE"

cat << 'FIRMWARE' >> "$CONFIG_FILE"
dtparam=audio=off
dtoverlay=rpi-codeczero
dtparam=pciex1_gen=3
FIRMWARE

cat << 'SOUND' > /etc/asound.conf 
pcm.!default {
    type asym
    playback.pcm "speaker_mixer"
    capture.pcm "input_dsnoop"
}

pcm.speaker_mixer {
    type plug
    slave.pcm {
        type dmix
        ipc_key 1024
        slave {
            pcm "hw:Zero,0"
            rate 48000
            period_time 0
            period_size 1024
            buffer_size 4096
        }
    }
}

pcm.input_dsnoop {
    type dsnoop
    ipc_key 2048
    slave {
        pcm "hw:Zero,0"
        rate 48000
        channels 1
    }
}

ctl.!default {
    type hw
    card Zero
}
SOUND

echo "--- PHASE 4: DRIVERS ---"
[[ -d "Pi-Audio-Drive" ]] || git clone https://github.com/RASPIAUDIO/Pi-Audio-Drive
# Use -f to restore without needing to cd if possible, or use subshell
(
    cd Pi-Audio-Drive
    alsactl restore -f MIC_HP_SPK 2 > /dev/null || echo "Hardware state restore pending reboot."
)

rpi-usb-gadget on

echo "----------------------------------------------------"
echo "CONSOLIDATED SETUP COMPLETE."
echo "1. Run: sudo reboot"
echo "2. After reboot, test audio: aplay /usr/share/sounds/alsa/Front_Center.wav"
echo "----------------------------------------------------"
