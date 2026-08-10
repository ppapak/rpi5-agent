# shellcheck shell=bash
# ============================================================
# Shared helpers for the Native-AI scripts.
# Source this, do not execute it:
#   source "$(dirname "$0")/lib/common.sh"
# ============================================================

# Repo root, derived from this file's location so callers can be run from anywhere.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE_DIR="$REPO_ROOT/profiles"

DRY_RUN=0

log()  { echo ">>> $*"; }
warn() { echo "!!! $*" >&2; }
die()  { echo "!!! $*" >&2; exit 1; }

# run <cmd...> — honours --dry-run for anything that changes the system.
run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "    [dry-run] $*"
    else
        "$@"
    fi
}

# self_elevate "$@" — re-exec under sudo when not already root.
self_elevate() {
    if [[ $EUID -ne 0 ]]; then
        exec sudo "$0" "$@"
    fi
}

# ------------------------------------------------------------
# Board detection and profiles
# ------------------------------------------------------------

available_boards() {
    local f
    for f in "$PROFILE_DIR"/*.conf; do
        [[ -e "$f" ]] || continue
        basename "$f" .conf
    done
}

# detect_board — echoes a board id by matching /proc/device-tree/model against
# each profile's DT_MODEL_MATCH. Returns non-zero when nothing matches.
detect_board() {
    local model board match
    [[ -r /proc/device-tree/model ]] || return 1
    model="$(tr -d '\0' < /proc/device-tree/model)"

    for board in $(available_boards); do
        match="$(
            # shellcheck disable=SC1090
            source "$PROFILE_DIR/$board.conf" >/dev/null 2>&1
            echo "${DT_MODEL_MATCH:-}"
        )"
        [[ -n "$match" ]] || continue
        if [[ "$model" == *"$match"* ]]; then
            echo "$board"
            return 0
        fi
    done
    return 1
}

# load_profile [board] — sources the profile for the given board, or for the
# auto-detected one when no argument is given.
load_profile() {
    local board="${1:-}"

    if [[ -n "$board" ]]; then
        log "Using profile: $board (forced)"
    else
        board="$(detect_board)" || die "Could not identify this board from /proc/device-tree/model.
    Pass one explicitly: --board <$(available_boards | paste -sd'|' -)>"
        log "Detected: $(tr -d '\0' < /proc/device-tree/model)"
        log "Using profile: $board"
    fi

    local file="$PROFILE_DIR/$board.conf"
    [[ -f "$file" ]] || die "No such profile: $file (available: $(available_boards | paste -sd', ' -))"
    # shellcheck disable=SC1090
    source "$file"
    BOARD="$board"
}

# ------------------------------------------------------------
# /boot/firmware/config.txt
# ------------------------------------------------------------

# set_config <key> <value> — idempotent edit of $CONFIG_FILE. Sets, replaces or
# uncomments an existing entry, otherwise appends. An empty value writes a bare
# line (for dtoverlay entries that take no argument).
set_config() {
    local key="$1"
    local value="$2"

    if [[ $DRY_RUN -eq 1 ]]; then
        echo "    [dry-run] set_config ${key}${value:+=$value}"
        return 0
    fi

    if [[ -z "$value" ]]; then
        if grep -q -E "^${key}$" "$CONFIG_FILE"; then
            return 0
        elif grep -q -E "^# *${key}$" "$CONFIG_FILE"; then
            sed -i -E "s/^# *(${key})$/\1/" "$CONFIG_FILE"
        else
            echo "$key" >> "$CONFIG_FILE"
        fi
    else
        if grep -q -E "^${key}=${value}$" "$CONFIG_FILE"; then
            return 0
        elif grep -q -E "^${key}=" "$CONFIG_FILE"; then
            sed -i -E "s/^${key}=.*/${key}=${value}/" "$CONFIG_FILE"
        elif grep -q -E "^# *${key}=" "$CONFIG_FILE"; then
            sed -i -E "s/^# *${key}=.*/${key}=${value}/" "$CONFIG_FILE"
        else
            echo "${key}=${value}" >> "$CONFIG_FILE"
        fi
    fi
}

# apply_firmware_settings — feeds the profile's FIRMWARE_SETTINGS array
# ("key|value" entries) through set_config.
apply_firmware_settings() {
    local entry key value
    for entry in "${FIRMWARE_SETTINGS[@]}"; do
        key="${entry%%|*}"
        value="${entry#*|}"
        set_config "$key" "$value"
    done
}

# set_vc4_noaudio — appends ,noaudio to the vc4-kms-v3d overlay exactly once.
set_vc4_noaudio() {
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "    [dry-run] append ,noaudio to dtoverlay=vc4-kms-v3d"
        return 0
    fi
    if grep -q -E '^dtoverlay=vc4-kms-v3d' "$CONFIG_FILE" &&
       ! grep -q -E '^dtoverlay=vc4-kms-v3d.*noaudio' "$CONFIG_FILE"; then
        sed -i -E '/^dtoverlay=vc4-kms-v3d/s/$/,noaudio/' "$CONFIG_FILE"
    fi
}

# ------------------------------------------------------------
# .env files
# ------------------------------------------------------------

# set_env_var <file> <key> <value> — idempotent KEY=VALUE edit, appending when
# the key is absent. Used to stamp profile values onto a copy of .env.example.
set_env_var() {
    local file="$1" key="$2" value="$3"

    if [[ $DRY_RUN -eq 1 ]]; then
        echo "    [dry-run] ${key}=${value} -> $file"
        return 0
    fi

    if grep -q -E "^# *${key}=" "$file" 2>/dev/null; then
        sed -i -E "s|^# *${key}=.*|${key}=${value}|" "$file"
    elif grep -q -E "^${key}=" "$file" 2>/dev/null; then
        sed -i -E "s|^${key}=.*|${key}=${value}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

# ------------------------------------------------------------
# Downloads and builds
# ------------------------------------------------------------

# fetch <url> <dest> — download unless dest already exists.
fetch() {
    local url="$1" dest="$2"
    if [[ -f "$dest" ]]; then
        return 0
    fi
    log "Downloading $(basename "$dest")..."
    run wget -q --show-progress -O "$dest" "$url"
}

# build_llama <base_dir> [jobs] — clone, build, or rebuild-if-stale llama.cpp.
# The single copy of what used to live in both installers and update_llama.sh.
build_llama() {
    local base_dir="$1"
    local jobs="${2:-4}"
    local src="$base_dir/llama.cpp"

    if [[ ! -d "$src" ]]; then
        log "Cloning llama.cpp..."
        run git clone https://github.com/ggerganov/llama.cpp "$src"
        _cmake_build "$src" "$jobs"
    elif [[ ! -f "$src/build/bin/llama-server" ]]; then
        log "Source present but llama-server binary missing. Rebuilding..."
        _cmake_build "$src" "$jobs"
    else
        log "llama-server binary exists."
    fi
}

# update_llama <base_dir> [jobs] — as build_llama, but also pulls upstream.
update_llama() {
    local base_dir="$1"
    local jobs="${2:-4}"
    local src="$base_dir/llama.cpp"

    if [[ ! -f "$src/build/bin/llama-server" ]]; then
        build_llama "$base_dir" "$jobs"
        return
    fi

    log "Checking for upstream updates..."
    run git -C "$src" fetch origin master
    local local_rev remote_rev
    local_rev="$(git -C "$src" rev-parse HEAD)"
    remote_rev="$(git -C "$src" rev-parse origin/master)"

    if [[ "$local_rev" != "$remote_rev" ]]; then
        log "New commits upstream. Updating and rebuilding..."
        run git -C "$src" pull origin master
        _cmake_build "$src" "$jobs"
    else
        log "llama.cpp is up to date."
    fi
}

_cmake_build() {
    local src="$1" jobs="$2"
    log "Building llama.cpp (this takes a while)..."
    run rm -rf "$src/build"
    run mkdir -p "$src/build"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "    [dry-run] cmake .. && cmake --build . --config Release -j $jobs (in $src/build)"
        return 0
    fi
    (
        cd "$src/build"
        cmake ..
        cmake --build . --config Release -j "$jobs"
    )
}

# ------------------------------------------------------------
# Templates
# ------------------------------------------------------------

# render_template <src> <dest> <KEY=VALUE>... — substitutes @KEY@ placeholders.
# Writes via sudo when dest is outside the user's tree (systemd units).
render_template() {
    local src="$1" dest="$2"; shift 2
    local content
    content="$(cat "$src")"

    local pair key value
    for pair in "$@"; do
        key="${pair%%=*}"
        value="${pair#*=}"
        content="${content//@${key}@/${value}}"
    done

    if [[ $DRY_RUN -eq 1 ]]; then
        echo "    [dry-run] would write $dest:"
        echo "$content" | sed 's/^/        | /'
        return 0
    fi

    if [[ -w "$(dirname "$dest")" ]]; then
        printf '%s\n' "$content" > "$dest"
    else
        printf '%s\n' "$content" | sudo tee "$dest" > /dev/null
    fi
}
