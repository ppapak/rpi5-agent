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

cat << 'FIRMWARE' >> "$CONFIG_FILE"
enable_uart=1
dtparam=audio=off
dtoverlay=googlevoicehat-soundcard
gpu_mem=256
dtoverlay=vc4-kms-v3d
dtoverlay=ov5647
dtoverlay=dwc2,dr_mode=peripheral
FIRMWARE

cat << 'SOUND' > /etc/asound.conf 
pcm.!default {
    type asym
    playback.pcm "plug:softvol"
    capture.pcm "plug:micboost"
}

pcm.softvol {
    type softvol
    slave.pcm "speaker_mixer"
    control {
        name "Master"
        card "sndrpigooglevoi"
        count 2
    }
    min_dB -51.0
    max_dB 0.0
    resolution 256
}

pcm.micboost {
    type softvol
    slave.pcm "input_dsnoop"
    control {
        name "MicMaster"
        card "sndrpigooglevoi"
        count 1
    }
    min_dB -3.0
    max_dB 30.0
    resolution 100
}

pcm.speaker_mixer {
    type plug
    slave.pcm {
        type dmix
        ipc_key 1024
        slave {
            pcm "hw:sndrpigooglevoi,0"
            rate 48000
            channels 2
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
        pcm "hw:sndrpigooglevoi,0"
        rate 48000
        channels 1
    }
}

ctl.!default {
    type hw
    card "sndrpigooglevoi"
}
SOUND

#reduce sound volume 
amixer -c sndrpigooglevoi sset Master 70%

#fix swap file size to 4GB
sudo mkdir -p /etc/rpi/swap.conf.d
sudo tee /etc/rpi/swap.conf.d/80-fixedswap.conf << EOF
[Main]
Mechanism=swapfile
[File]
FixedSizeMiB=4096
EOF

#turn on usb gadget mode
rpi-usb-gadget on

echo "----------------------------------------------------"
echo "CONSOLIDATED SETUP COMPLETE."
echo "1. Run: sudo reboot"
echo "2. After reboot, test audio: aplay /usr/share/sounds/alsa/Front_Center.wav"
echo "----------------------------------------------------"