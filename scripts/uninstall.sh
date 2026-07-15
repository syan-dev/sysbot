#!/usr/bin/env bash
# SysBot uninstall script — Linux & macOS
# Usage: bash scripts/uninstall.sh
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { printf "${CYAN}  →  ${NC}%s\n"   "$*"; }
ok()   { printf "${GREEN}  ✓  ${NC}%s\n"  "$*"; }
warn() { printf "${YELLOW}  !  ${NC}%s\n" "$*"; }
hr()   { printf '%0.s─' {1..60}; printf '\n'; }

OS="$(uname -s)"

hr
printf "  SysBot Uninstaller\n"
hr

# ── 1. Remove platform service ────────────────────────────────────────────────
remove_linux() {
    local stopped=false disabled=false removed=false

    if systemctl --user is-active --quiet sysbot 2>/dev/null; then
        systemctl --user stop sysbot
        stopped=true
    fi
    if systemctl --user is-enabled --quiet sysbot 2>/dev/null; then
        systemctl --user disable sysbot
        disabled=true
    fi

    UNIT_FILE="$HOME/.config/systemd/user/sysbot.service"
    if [[ -f "$UNIT_FILE" ]]; then
        rm "$UNIT_FILE"
        systemctl --user daemon-reload
        removed=true
    fi

    if $removed; then
        ok "systemd service removed"
    else
        warn "No systemd service file found — skipping"
    fi

    # Optionally disable linger (only if user wants it)
    if command -v loginctl &>/dev/null && loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
        read -r -p "  Disable auto-start at boot (loginctl disable-linger)? [y/N] " ans
        if [[ "${ans,,}" == "y" ]]; then
            loginctl disable-linger "$USER" && ok "Linger disabled"
        fi
    fi
}

remove_macos() {
    PLIST_FILE="$HOME/Library/LaunchAgents/com.sysbot.sysbot.plist"
    if [[ -f "$PLIST_FILE" ]]; then
        launchctl unload -w "$PLIST_FILE" 2>/dev/null || true
        rm "$PLIST_FILE"
        ok "LaunchAgent removed"
    else
        warn "No LaunchAgent plist found — skipping"
    fi
}

case "$OS" in
    Linux*)  remove_linux  ;;
    Darwin*) remove_macos  ;;
    *)       warn "Unknown OS — skipping service removal" ;;
esac

# ── 2. Uninstall Python package ───────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    command -v "$cmd" &>/dev/null && PYTHON="$cmd" && break
done

if [[ -n "$PYTHON" ]]; then
    info "Removing sysbot package …"
    if $PYTHON -m pip show sysbot &>/dev/null; then
        $PYTHON -m pip uninstall sysbot -y --quiet
        ok "Package uninstalled"
    else
        warn "Package not found in pip — skipping"
    fi
else
    warn "Python not found — package not removed"
fi

# ── 3. Per-user data home (config, tools, logs) ───────────────────────────────
DATA_DIR="${SYSBOT_HOME:-$HOME/.sysbot}"
if [[ -d "$DATA_DIR" ]]; then
    read -r -p "  Remove your config, tools and logs in $DATA_DIR? [y/N] " ans
    if [[ "${ans,,}" == "y" ]]; then
        rm -rf "$DATA_DIR" && ok "Removed $DATA_DIR"
    else
        info "Kept $DATA_DIR (edit or delete it manually later)"
    fi
fi

hr
ok "SysBot has been uninstalled."
printf "\n  Optional cleanup:\n"
printf "    rm -rf %s          # config, tools and logs\n" "$DATA_DIR"
printf "    rm -rf ~/Library/Logs/sysbot   # macOS stdout/stderr logs\n\n"
