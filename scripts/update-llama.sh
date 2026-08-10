#!/bin/bash
# ============================================================
# Pull and rebuild llama.cpp in an existing install, then restart the server.
#
#   ./scripts/update-llama.sh [--dry-run]
#
# BASE_DIR defaults to ~/native-ai; override it in the environment.
# ============================================================
set -euo pipefail

source "$(dirname "$(realpath "$0")")/lib/common.sh"

BASE_DIR="${BASE_DIR:-$HOME/native-ai}"
JOBS="${JOBS:-4}"

if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

[[ -d "$BASE_DIR" ]] || die "No install found at $BASE_DIR. Set BASE_DIR or run scripts/install.sh first."

update_llama "$BASE_DIR" "$JOBS"

if systemctl list-unit-files llama-server.service >/dev/null 2>&1; then
    log "Restarting llama-server..."
    run sudo systemctl restart llama-server
fi

log "Done."
