#!/usr/bin/env bash
# LeSysBot uninstall script — Linux & macOS
# Usage: bash scripts/uninstall.sh
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { printf "${CYAN}  →  ${NC}%s\n"   "$*"; }
ok()   { printf "${GREEN}  ✓  ${NC}%s\n"  "$*"; }
warn() { printf "${YELLOW}  !  ${NC}%s\n" "$*"; }
hr()   { printf '%0.s─' {1..60}; printf '\n'; }

OS="$(uname -s)"

hr
printf "  LeSysBot Uninstaller\n"
hr

# ── 1. Remove platform service ────────────────────────────────────────────────
remove_linux() {
    local stopped=false disabled=false removed=false

    if systemctl --user is-active --quiet lesysbot 2>/dev/null; then
        systemctl --user stop lesysbot
        stopped=true
    fi
    if systemctl --user is-enabled --quiet lesysbot 2>/dev/null; then
        systemctl --user disable lesysbot
        disabled=true
    fi

    UNIT_FILE="$HOME/.config/systemd/user/lesysbot.service"
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
    PLIST_FILE="$HOME/Library/LaunchAgents/com.lesysbot.lesysbot.plist"
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

# ── 1b. Wake-up sudoers rule (Linux only; written by the optional shutdown-wake
# tool's setup-sudoers.sh, or by an older install wizard) ─────────────────────
WAKE_RULE_FILE="/etc/sudoers.d/lesysbot-rtcwake"
if [[ "$OS" == Linux* && -f "$WAKE_RULE_FILE" ]]; then
    read -r -p "  Remove the rtcwake sudoers rule ($WAKE_RULE_FILE)? [y/N] " ans
    if [[ "${ans,,}" == "y" ]]; then
        sudo rm -f "$WAKE_RULE_FILE" && ok "Wake-up sudoers rule removed" \
            || warn "Could not remove it (sudo failed) — delete it manually"
    else
        info "Kept $WAKE_RULE_FILE"
    fi
fi

# ── 2. Uninstall Python package ───────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    command -v "$cmd" &>/dev/null && PYTHON="$cmd" && break
done

if [[ -n "$PYTHON" ]]; then
    info "Removing lesysbot package …"
    if $PYTHON -m pip show lesysbot &>/dev/null; then
        $PYTHON -m pip uninstall lesysbot -y --quiet
        ok "Package uninstalled"
    else
        warn "Package not found in pip — skipping"
    fi
else
    warn "Python not found — package not removed"
fi

# ── 3. Per-user data home (config, tools, logs) ───────────────────────────────
DATA_DIR="${LESYSBOT_HOME:-$HOME/.lesysbot}"
if [[ -d "$DATA_DIR" ]]; then
    read -r -p "  Remove your config, tools and logs in $DATA_DIR? [y/N] " ans
    if [[ "${ans,,}" == "y" ]]; then
        rm -rf "$DATA_DIR" && ok "Removed $DATA_DIR"
    else
        info "Kept $DATA_DIR (edit or delete it manually later)"
    fi
fi

hr
ok "LeSysBot has been uninstalled."
printf "\n  Optional cleanup:\n"
printf "    rm -rf %s          # config, tools and logs\n" "$DATA_DIR"
printf "    rm -rf ~/Library/Logs/lesysbot   # macOS stdout/stderr logs\n\n"
