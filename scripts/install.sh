#!/bin/bash
# ============================================================
# Native-AI deployment.
#
#   ./scripts/install.sh                 # auto-detect the board
#   ./scripts/install.sh --board pi4     # force a profile
#   ./scripts/install.sh --dry-run       # print every action, change nothing
#
# Everything board-specific comes from profiles/<board>.conf.
# ============================================================
set -euo pipefail

source "$(dirname "$(realpath "$0")")/lib/common.sh"

VOSK_MODEL="vosk-model-small-en-us-0.15"
PIPER_VERSION="v1.2.0"
PIPER_VOICE="en_US-lessac-medium"

usage() {
    cat <<USAGE
Usage: $(basename "$0") [--board <$(available_boards | paste -sd'|' -)>] [--dry-run]

  --board   Skip auto-detection and use this profile.
  --dry-run Print what would happen without touching the system.
USAGE
}

BOARD_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --board) BOARD_ARG="${2:-}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "Unknown argument: $1" ;;
    esac
done

# ============================================================
# 1. IDENTITY & PROFILE
# ============================================================
REAL_USER=${SUDO_USER:-$(whoami)}
# getent is the reliable answer under sudo; fall back for systems without it.
USER_HOME=$(getent passwd "$REAL_USER" 2>/dev/null | cut -d: -f6 || true)
[[ -n "$USER_HOME" ]] || USER_HOME=$(eval echo "~$REAL_USER")
BASE_DIR="$USER_HOME/native-ai"
MODEL_DIR="$BASE_DIR/models"

load_profile "$BOARD_ARG"
MODEL_FILE="$MODEL_DIR/$LLM_MODEL_FILE"

log "Deploying $BOARD_NAME for user $REAL_USER in $BASE_DIR"
if [[ $DRY_RUN -eq 1 ]]; then
    log "DRY RUN — nothing will be changed."
fi

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && $DRY_RUN -eq 0 ]]; then
    die "This installer builds against arm64 assets but the system reports '$ARCH'.
    Use a 64-bit Raspberry Pi OS image."
fi

# ============================================================
# 2. SYSTEM DEPENDENCIES
# ============================================================
log "[1/7] Verifying system dependencies..."
run sudo apt-get update -qq
# shellcheck disable=SC2086
run sudo apt-get install -y -qq git build-essential cmake portaudio19-dev \
    python3-venv python3-dev unzip curl wget alsa-utils $EXTRA_APT

# Without the audio group the service cannot open the sound card.
run sudo usermod -aG audio "$REAL_USER"

run mkdir -p "$MODEL_DIR" "$BASE_DIR/piper" "$BASE_DIR/workspace"

if [[ -n "$TMP_REMOUNT" ]]; then
    # The llama.cpp build and the model download both spill into /tmp.
    log "Enlarging /tmp to $TMP_REMOUNT for the build..."
    run sudo mount -o remount,size="$TMP_REMOUNT" /tmp
fi

# ============================================================
# 3. UNINSTALLER
# ============================================================
run cp "$REPO_ROOT/scripts/uninstall.sh" "$BASE_DIR/uninstall.sh"
run chmod +x "$BASE_DIR/uninstall.sh"

# ============================================================
# 4. INFERENCE ENGINE
# ============================================================
log "[2/7] Checking inference engine..."
build_llama "$BASE_DIR" "$LLM_THREADS"

# ============================================================
# 5. ASSET DOWNLOADS
# ============================================================
log "[3/7] Syncing models and voice assets..."

fetch "$LLM_MODEL_URL" "$MODEL_FILE"

if [[ ! -f "$BASE_DIR/piper/piper/piper" ]]; then
    log "Installing Piper $PIPER_VERSION..."
    fetch "https://github.com/rhasspy/piper/releases/download/$PIPER_VERSION/piper_arm64.tar.gz" \
          "$BASE_DIR/piper/piper_arm64.tar.gz"
    run tar -xf "$BASE_DIR/piper/piper_arm64.tar.gz" -C "$BASE_DIR/piper"
fi

fetch "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/$PIPER_VOICE.onnx" \
      "$BASE_DIR/piper/$PIPER_VOICE.onnx"
fetch "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/$PIPER_VOICE.onnx.json" \
      "$BASE_DIR/piper/$PIPER_VOICE.onnx.json"

if [[ ! -d "$BASE_DIR/$VOSK_MODEL" ]]; then
    log "Installing Vosk STT model..."
    fetch "https://alphacephei.com/vosk/models/$VOSK_MODEL.zip" "$BASE_DIR/$VOSK_MODEL.zip"
    run unzip -q "$BASE_DIR/$VOSK_MODEL.zip" -d "$BASE_DIR"
    run rm -f "$BASE_DIR/$VOSK_MODEL.zip"
fi

# ============================================================
# 6. PYTHON ENVIRONMENT
# ============================================================
log "[4/7] Configuring virtual environment..."
# picamera2 is an apt package, so the Pi 4 venv has to see system site-packages.
VENV_ARGS=""
if [[ "$VENV_SYSTEM_SITE_PACKAGES" -eq 1 ]]; then
    VENV_ARGS="--system-site-packages"
fi

if [[ ! -d "$BASE_DIR/venv" ]]; then
    # shellcheck disable=SC2086  # VENV_ARGS is a single known flag or empty
    run python3 -m venv $VENV_ARGS "$BASE_DIR/venv"
fi
run "$BASE_DIR/venv/bin/pip" install --upgrade -q pip
run "$BASE_DIR/venv/bin/pip" install -q -r "$REPO_ROOT/$REQUIREMENTS_FILE"

# ============================================================
# 7. APPLICATION & CONFIGURATION
# ============================================================
log "[5/7] Installing the assistant..."
run rm -rf "$BASE_DIR/native_ai"
run cp -R "$REPO_ROOT/src/native_ai" "$BASE_DIR/native_ai"

ENV_FILE="$BASE_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    log "Writing $ENV_FILE from .env.example..."
    run cp "$REPO_ROOT/.env.example" "$ENV_FILE"
    set_env_var "$ENV_FILE" "SAMPLE_RATE" "$SAMPLE_RATE"
    set_env_var "$ENV_FILE" "PROMPT_FORMAT" "$PROMPT_FORMAT"
    set_env_var "$ENV_FILE" "FEATURE_RAG" "$FEATURE_RAG"
    set_env_var "$ENV_FILE" "FEATURE_VISION" "$FEATURE_VISION"
    set_env_var "$ENV_FILE" "FEATURE_BATTERY" "$FEATURE_BATTERY"
    set_env_var "$ENV_FILE" "FEATURE_TOOLS" "$FEATURE_TOOLS"
else
    log "Keeping existing $ENV_FILE (delete it to regenerate from the profile)."
fi
# Always correct: a wrong BASE_DIR breaks every path the assistant resolves.
set_env_var "$ENV_FILE" "BASE_DIR" "$BASE_DIR"

# ============================================================
# 8. SYSTEMD SERVICES
# ============================================================
log "[6/7] Installing systemd services..."
render_template "$REPO_ROOT/systemd/llama-server.service.tmpl" \
    /etc/systemd/system/llama-server.service \
    "USER=$REAL_USER" "BASE_DIR=$BASE_DIR" "MODEL_FILE=$MODEL_FILE" \
    "LLM_CTX=$LLM_CTX" "LLM_THREADS=$LLM_THREADS"

render_template "$REPO_ROOT/systemd/voice-assistant.service.tmpl" \
    /etc/systemd/system/voice-assistant.service \
    "USER=$REAL_USER" "BASE_DIR=$BASE_DIR" "UID=$(id -u "$REAL_USER")"

# ============================================================
# 9. START
# ============================================================
log "[7/7] Launching services..."
run sudo chown -R "$REAL_USER:$REAL_USER" "$BASE_DIR"
run sudo systemctl daemon-reload
run sudo systemctl enable llama-server voice-assistant
run sudo systemctl restart llama-server voice-assistant

log "--- DEPLOYMENT COMPLETE ($BOARD_NAME) ---"
log "Logs:      journalctl -u voice-assistant -f"
log "Settings:  $ENV_FILE"
log "Uninstall: $BASE_DIR/uninstall.sh"
