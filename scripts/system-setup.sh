#!/bin/bash
# ============================================================
# One-time OS and hardware provisioning for a fresh Raspberry Pi OS image.
# Re-runnable: every edit below is idempotent.
#
#   ./scripts/system-setup.sh                 # auto-detect the board
#   ./scripts/system-setup.sh --board pi4     # force a profile
#   ./scripts/system-setup.sh --dry-run
#
# Reboot afterwards, then run scripts/install.sh.
# ============================================================
set -euo pipefail

source "$(dirname "$(realpath "$0")")/lib/common.sh"

usage() {
    cat <<USAGE
Usage: $(basename "$0") [--board <$(available_boards | paste -sd'|' -)>] [--dry-run]

  --board   Skip auto-detection and use this profile.
  --dry-run Print what would happen without touching the system.
USAGE
}

BOARD_ARG=""
ARGS=("$@")
while [[ $# -gt 0 ]]; do
    case "$1" in
        --board) BOARD_ARG="${2:-}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "Unknown argument: $1" ;;
    esac
done

[[ $DRY_RUN -eq 1 ]] || self_elevate "${ARGS[@]}"

load_profile "$BOARD_ARG"
CONFIG_FILE="/boot/firmware/config.txt"

log "--- PHASE 1: SYSTEM UPDATES ($BOARD_NAME) ---"
run swapoff -a
run apt update
run apt full-upgrade -y
run apt autoremove -y
run apt install -y locales-all git alsa-utils

log "--- PHASE 2: LOCALE & SSH ---"
run sed -i -e 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
run locale-gen en_US.UTF-8

if [[ $DRY_RUN -eq 1 ]]; then
    echo "    [dry-run] write /etc/default/locale"
else
    cat << 'LOCALE' > /etc/default/locale
LANG=en_US.UTF-8
LC_ALL=en_US.UTF-8
LOCALE
fi

# Stop SSH clients from injecting a locale the Pi does not have generated.
run sed -i 's/^AcceptEnv LANG LC_*/# AcceptEnv LANG LC_*/' /etc/ssh/sshd_config

log "--- PHASE 3: FIRMWARE & HARDWARE ---"
[[ -f "$CONFIG_FILE" || $DRY_RUN -eq 1 ]] || die "$CONFIG_FILE not found. Is this Raspberry Pi OS?"

apply_firmware_settings
# Keep HDMI audio from claiming a card index ahead of the HAT.
if [[ "$VC4_NOAUDIO" -eq 1 ]]; then
    set_vc4_noaudio
fi

log "--- PHASE 4: ALSA ROUTING ---"
# dmix/dsnoop let the assistant and any shell command share the card; softvol
# adds the volume controls that HATs without a hardware mixer lack.
build_asound_conf() {
    if [[ "$AUDIO_SOFTVOL" -eq 1 ]]; then
        cat <<SOUND
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
        card "$ALSA_CARD"
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
        card "$ALSA_CARD"
        count 1
    }
    min_dB -3.0
    max_dB 30.0
    resolution 100
}
SOUND
    else
        cat <<SOUND
pcm.!default {
    type asym
    playback.pcm "speaker_mixer"
    capture.pcm "input_dsnoop"
}
SOUND
    fi

    cat <<SOUND

pcm.speaker_mixer {
    type plug
    slave.pcm {
        type dmix
        ipc_key 1024
        slave {
            pcm "$ALSA_HW_DEVICE"
            rate 48000
${ALSA_PLAYBACK_CHANNELS:+            channels $ALSA_PLAYBACK_CHANNELS
}            period_time 0
            period_size 1024
            buffer_size 4096
        }
    }
}

pcm.input_dsnoop {
    type dsnoop
    ipc_key 2048
    slave {
        pcm "$ALSA_HW_DEVICE"
        rate 48000
        channels 1
    }
}

ctl.!default {
    type hw
    card "$ALSA_CARD"
}
SOUND
}

if [[ $DRY_RUN -eq 1 ]]; then
    echo "    [dry-run] would write /etc/asound.conf:"
    build_asound_conf | sed 's/^/        | /'
else
    build_asound_conf > /etc/asound.conf
fi

if [[ -n "$AUDIO_DRIVER_REPO" ]]; then
    log "--- PHASE 5: AUDIO DRIVER ---"
    DRIVER_DIR="/opt/$(basename "$AUDIO_DRIVER_REPO")"
    [[ -d "$DRIVER_DIR" ]] || run git clone "$AUDIO_DRIVER_REPO" "$DRIVER_DIR"
    if [[ -n "$AUDIO_DRIVER_STATE" && $DRY_RUN -eq 0 ]]; then
        (
            cd "$DRIVER_DIR"
            alsactl restore -f "$AUDIO_DRIVER_STATE" 2 > /dev/null ||
                log "Hardware state restore pending reboot."
        )
    fi
fi

if [[ -n "$SWAP_FIXED_MIB" ]]; then
    log "--- PHASE 6: SWAP (${SWAP_FIXED_MIB} MiB) ---"
    run mkdir -p /etc/rpi/swap.conf.d
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "    [dry-run] write /etc/rpi/swap.conf.d/80-fixedswap.conf"
    else
        cat > /etc/rpi/swap.conf.d/80-fixedswap.conf <<EOF
[Main]
Mechanism=swapfile
[File]
FixedSizeMiB=$SWAP_FIXED_MIB
EOF
    fi
fi

# USB gadget mode: reach the Pi over a single USB-C cable, no network needed.
run rpi-usb-gadget on

echo "----------------------------------------------------"
echo "SETUP COMPLETE for $BOARD_NAME."
echo "1. Run: sudo reboot"
echo "2. After reboot, test audio: aplay /usr/share/sounds/alsa/Front_Center.wav"
echo "3. Adjust volume: alsamixer -c $ALSA_CARD"
echo "4. Then deploy: ./scripts/install.sh"
echo "----------------------------------------------------"
