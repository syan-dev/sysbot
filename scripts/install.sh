#!/usr/bin/env bash
# SysBot install script — Linux & macOS
# Usage: bash scripts/install.sh
set -euo pipefail

# ── colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()      { printf "${GREEN}  ✓  ${NC}%s\n"    "$*"; }
warn()    { printf "${YELLOW}  !  ${NC}%s\n"   "$*"; }
die()     { printf "${RED}  ✗  ${NC}%s\n"      "$*" >&2; exit 1; }
section() { printf "\n${BOLD}${CYAN}  %s${NC}\n  %s\n" "$1" "$(printf '%.0s─' {1..50})"; }
hr()      { printf "\n  %s\n" "$(printf '%.0s─' {1..50})"; }

# Read input with a default value.
# Prompts go to stderr so they're visible even inside $() command substitution.
ask() {
    local prompt="$1" default="$2" answer
    printf "  ${CYAN}?${NC}  %s" "$prompt" >&2
    [[ -n "$default" ]] && printf " ${BOLD}[%s]${NC}" "$default" >&2
    printf ": " >&2
    read -r answer
    echo "${answer:-$default}"
}

# Ask a yes/no question; returns 0 for yes, 1 for no
ask_yn() {
    local prompt="$1" default="${2:-y}" answer
    local hint; hint="$( [[ "${default,,}" == y ]] && echo "Y/n" || echo "y/N" )"
    printf "  ${CYAN}?${NC}  %s ${BOLD}[%s]${NC}: " "$prompt" "$hint"
    read -r answer
    answer="${answer:-$default}"
    [[ "${answer,,}" =~ ^y ]]
}

# Redraw the option list for menu(), highlighting the current selection.
# Reads $_menu_options[]/$_menu_sel from the calling menu() (bash dynamic scope).
_menu_draw() {
    local i=0
    for opt in "${_menu_options[@]}"; do
        if (( i == _menu_sel )); then
            printf "  ${CYAN}❯${NC} ${BOLD}%s${NC}\033[K\n" "$opt" >/dev/tty
        else
            printf "    %s\033[K\n" "$opt" >/dev/tty
        fi
        i=$(( i + 1 ))
    done
}

# Single-choice menu; prints the chosen 1-based number on stdout.
# Interactive: ↑/↓ to move, Enter to confirm, number keys jump to an option.
# Drawing goes to /dev/tty so it works inside $() substitution; when no terminal
# is available it falls back to a typed numbered prompt on stderr.
menu() {
    local default="$1"; shift
    local -a _menu_options=("$@")
    local n=${#_menu_options[@]}

    # Non-interactive fallback (e.g. piped input, CI) ─ keep the old behaviour.
    # stdout is captured by $(), so probe stderr (fd 2) to detect a real terminal.
    if [[ ! -t 2 || ! -r /dev/tty ]]; then
        local i=1
        for opt in "${_menu_options[@]}"; do printf "    %s) %s\n" "$i" "$opt" >&2; ((i++)); done
        printf "\n" >&2
        local choice; choice=$(ask "Choice" "$default")
        if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > n )); then choice="$default"; fi
        echo "$choice"
        return
    fi

    local _menu_sel=$(( default - 1 ))
    (( _menu_sel < 0 || _menu_sel >= n )) && _menu_sel=0

    printf "  ${CYAN}?${NC}  Use ${BOLD}↑/↓${NC} then ${BOLD}Enter${NC}, or press a number:\n" >/dev/tty
    printf '\033[?25l' >/dev/tty            # hide cursor
    # Always restore the cursor, even on Ctrl-C.
    trap 'printf "\033[?25h" >/dev/tty' RETURN
    _menu_draw

    local key rest
    while IFS= read -rsn1 key </dev/tty; do
        case "$key" in
            $'\x1b')                          # escape sequence (arrow keys)
                read -rsn2 -t 0.05 rest </dev/tty || rest=""
                case "$rest" in
                    '[A'|'OA') _menu_sel=$(( (_menu_sel - 1 + n) % n ));;
                    '[B'|'OB') _menu_sel=$(( (_menu_sel + 1) % n ));;
                esac
                ;;
            '') break ;;                      # Enter confirms
            [1-9])
                (( key >= 1 && key <= n )) && _menu_sel=$(( key - 1 ))
                ;;
        esac
        printf '\033[%dA' "$n" >/dev/tty      # move back to the top of the list
        _menu_draw
    done

    printf '\033[?25h' >/dev/tty             # restore cursor
    trap - RETURN
    echo $(( _menu_sel + 1 ))
}

# ── Ollama helpers ────────────────────────────────────────────────────────────
# List installed Ollama models (names only), one per line. Empty if none / no server.
ollama_models() {
    ollama list 2>/dev/null | awk 'NR>1 && $1 != "" {print $1}'
}

# Pull a model, streaming progress to stderr so it isn't captured by $().
# Returns 0 on success.
ollama_pull() {
    local model="$1"
    printf "\n  Pulling ${BOLD}%s${NC} … this can take a few minutes.\n\n" "$model" >&2
    if ollama pull "$model" >&2; then
        ok "Pulled $model" >&2
        return 0
    fi
    warn "Could not pull $model — you can do it later with: ollama pull $model" >&2
    return 1
}

# Interactive Ollama model picker. Prints the chosen model name on stdout;
# all UI goes to stderr so it works inside $(...).
select_ollama_model() {
    local default_model="llama3.2"

    if ! command -v ollama &>/dev/null; then
        warn "Ollama CLI not found on PATH." >&2
        printf "  Install it from ${BOLD}https://ollama.com${NC}, then re-run.\n" >&2
        printf "  For now you can name a model to use once Ollama is available.\n" >&2
        ask "Model name" "$default_model"
        return
    fi

    local -a models=()
    local line
    while IFS= read -r line; do [[ -n "$line" ]] && models+=("$line"); done < <(ollama_models)

    if (( ${#models[@]} == 0 )); then
        warn "No Ollama models are installed yet." >&2
        local m; m=$(ask "Model to download now" "$default_model")
        ollama_pull "$m" || true
        echo "$m"
        return
    fi

    printf "\n  ${BOLD}Choose an Ollama model${NC} (pick one or pull a new one):\n" >&2
    local choice; choice=$(menu 1 "${models[@]}" "Pull a different model (enter a name)")
    local pull_opt=$(( ${#models[@]} + 1 ))
    if (( choice == pull_opt )); then
        local m; m=$(ask "Model name to pull (e.g. llama3.2, qwen3.5, gemma3:4b)" "$default_model")
        ollama_pull "$m" || true
        echo "$m"
        return
    fi
    echo "${models[$((choice-1))]}"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
OS="$(uname -s)"

clear
printf "\n"
hr
printf "\n  ${BOLD}SysBot Setup${NC}\n"
hr

# ═══════════════════════════════════════════════════════════════════════════════
# 1. PYTHON
# ═══════════════════════════════════════════════════════════════════════════════
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    die "Python 3.11+ is required but was not found.
       Install it from https://python.org or via your package manager:
         Ubuntu/Debian : sudo apt install python3
         macOS         : brew install python"
fi
ok "Python $($PYTHON --version | cut -d' ' -f2)"

# ═══════════════════════════════════════════════════════════════════════════════
# 2. INSTALL PACKAGE
# ═══════════════════════════════════════════════════════════════════════════════
printf "\n  Installing sysbot package …\n"
cd "$REPO_DIR"
$PYTHON -m pip install --quiet .
ok "Package installed"

SYSBOT_BIN=""
if command -v sysbot &>/dev/null; then
    SYSBOT_BIN="$(command -v sysbot)"
else
    SCRIPTS="$($PYTHON -c 'import sys, os; print(os.path.join(sys.prefix, "bin"))')"
    [[ -f "$SCRIPTS/sysbot" ]] && SYSBOT_BIN="$SCRIPTS/sysbot"
fi
[[ -n "$SYSBOT_BIN" ]] || die "Cannot locate the sysbot binary after install.
       Make sure pip's bin directory is in your PATH, then re-run."
ok "Binary: $SYSBOT_BIN"

# ═══════════════════════════════════════════════════════════════════════════════
# 3. SETUP WIZARD
# ═══════════════════════════════════════════════════════════════════════════════
if [[ -f "$REPO_DIR/config.yaml" ]]; then
    printf "\n"
    if ! ask_yn "config.yaml already exists — overwrite with new settings?" "n"; then
        printf "\n  Keeping existing config.yaml.\n"
        SKIP_CONFIG=true
    else
        SKIP_CONFIG=false
    fi
else
    SKIP_CONFIG=false
fi

if [[ "$SKIP_CONFIG" == false ]]; then

    # ── LLM backend ───────────────────────────────────────────────────────────
    section "LLM Backend"
    LLM_CHOICE=$(menu 1 \
        "Ollama    — local, recommended (no API key needed)" \
        "OpenAI    — cloud API" \
        "vLLM      — self-hosted OpenAI-compatible server" \
        "Custom    — any OpenAI-compatible endpoint")

    case "$LLM_CHOICE" in
        2)
            LLM_BASE_URL="https://api.openai.com/v1"
            LLM_MODEL=$(ask "Model" "gpt-4o")
            LLM_API_KEY=$(ask "API key (sk-...)" "")
            ;;
        3)
            LLM_BASE_URL=$(ask "vLLM base URL" "http://localhost:8000/v1")
            LLM_MODEL=$(ask "Model" "meta-llama/Llama-3.2-8B-Instruct")
            LLM_API_KEY="vllm"
            ;;
        4)
            LLM_BASE_URL=$(ask "Base URL" "http://localhost:8000/v1")
            LLM_MODEL=$(ask "Model" "llama3.2")
            LLM_API_KEY=$(ask "API key" "none")
            ;;
        *)  # 1 — Ollama
            LLM_BASE_URL="http://localhost:11434/v1"
            LLM_MODEL=$(select_ollama_model)
            LLM_API_KEY="ollama"
            ;;
    esac

    # ── How to reach SysBot ───────────────────────────────────────────────────
    section "How to reach SysBot"
    printf "  You can always chat in this terminal with ${BOLD}sysbot --provider cli${NC}.\n"
    printf "  Add Telegram or Slack to also message SysBot remotely.\n\n"
    MSG_CHOICE=$(menu 1 \
        "Terminal only (default)" \
        "Telegram — also message it remotely" \
        "Slack — also message it remotely")

    TG_TOKEN=""; TG_ALLOWED_IDS="[]"; SLACK_BOT=""; SLACK_APP=""
    case "$MSG_CHOICE" in
        2)
            MSG_PROVIDER="telegram"
            printf "\n"
            TG_TOKEN=$(ask "Bot token (from @BotFather)" "")
            _raw_ids=$(ask "Allowed Telegram user IDs, comma-separated (blank = allow everyone)" "")
            if [[ -n "$_raw_ids" ]]; then
                TG_ALLOWED_IDS="[$(echo "$_raw_ids" | sed 's/[[:space:]]//g; s/,/, /g')]"
            fi
            ;;
        3)
            MSG_PROVIDER="slack"
            printf "\n"
            SLACK_BOT=$(ask "Bot token (xoxb-...)" "")
            SLACK_APP=$(ask "App token (xapp-...)" "")
            ;;
        *)
            MSG_PROVIDER="cli"
            ;;
    esac

    # ── Write config.yaml ─────────────────────────────────────────────────────
    cat > "$REPO_DIR/config.yaml" <<EOF
messaging:
  provider: $MSG_PROVIDER

  telegram:
    token: "$TG_TOKEN"
    allowed_user_ids: $TG_ALLOWED_IDS

  slack:
    bot_token: "$SLACK_BOT"
    app_token: "$SLACK_APP"

llm:
  base_url: "$LLM_BASE_URL"
  model: "$LLM_MODEL"
  api_key: "$LLM_API_KEY"
  temperature: 0.7
  max_tokens: 4096
  timeout: 120.0

mcp:
  tools_dir: "./tools"
  hot_reload: true

agent:
  system_prompt: >
    You are a helpful assistant with access to tools.
    Use tools when they help answer the user's question.
    Be concise and clear.
  max_history: 50
  max_tool_calls: 10

logging:
  level: INFO
  file: logs/sysbot.log
  trace_file: logs/traces.jsonl
EOF
    ok "config.yaml written"

fi  # end SKIP_CONFIG

# ── Resolve provider ──────────────────────────────────────────────────────────
# $MSG_PROVIDER is set above only when a fresh config was written; if the user
# kept an existing config.yaml, read the provider back from it. Only Telegram and
# Slack need an always-on background service to poll for messages — CLI is an
# interactive terminal session the user starts on demand.
PROVIDER="${MSG_PROVIDER:-}"
if [[ -z "$PROVIDER" && -f "$REPO_DIR/config.yaml" ]]; then
    PROVIDER=$(grep -E '^[[:space:]]*provider:' "$REPO_DIR/config.yaml" \
        | head -1 | sed -E 's/.*provider:[[:space:]]*//; s/["'\'' ]//g')
fi
PROVIDER="${PROVIDER:-cli}"
NEEDS_SERVICE=false
[[ "$PROVIDER" == telegram || "$PROVIDER" == slack ]] && NEEDS_SERVICE=true

# ── Auto-start ────────────────────────────────────────────────────────────────
AUTO_START=false
if $NEEDS_SERVICE; then
    section "Service"
    printf "  A %s bot runs in the background, so it installs as a service.\n\n" "$PROVIDER"
    if ask_yn "Start SysBot automatically after reboot?" "y"; then
        AUTO_START=true
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 4. SUMMARY + CONFIRM
# ═══════════════════════════════════════════════════════════════════════════════
printf "\n"
hr
printf "\n  ${BOLD}Summary${NC}\n\n"
if [[ "$SKIP_CONFIG" == false ]]; then
    printf "  LLM        %s  (%s)\n" "$LLM_MODEL" "$LLM_BASE_URL"
fi
printf "  Provider   %s\n" "$PROVIDER"
if $NEEDS_SERVICE; then
    printf "  Startup    %s\n" "$( $AUTO_START && echo "enabled — starts at reboot" || echo "started now, not at reboot" )"
else
    printf "  Startup    runs in your terminal (no background service)\n"
fi
printf "  Config     %s/config.yaml\n" "$REPO_DIR"
printf "  Working    %s\n" "$REPO_DIR"
printf "\n"

if ! ask_yn "Apply these settings?" "y"; then
    printf "\n  ${YELLOW}Aborted.${NC}\n\n"
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 5. PLATFORM-SPECIFIC SERVICE SETUP
# ═══════════════════════════════════════════════════════════════════════════════
setup_linux() {
    UNIT_DIR="$HOME/.config/systemd/user"
    UNIT_FILE="$UNIT_DIR/sysbot.service"
    mkdir -p "$UNIT_DIR"

    cat > "$UNIT_FILE" <<EOF
[Unit]
Description=SysBot — local AI assistant with tools
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=$SYSBOT_BIN
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload

    if $AUTO_START; then
        systemctl --user enable --now sysbot
        if command -v loginctl &>/dev/null; then
            loginctl enable-linger "$USER" 2>/dev/null \
                && ok  "Linger enabled — starts at boot without login" \
                || warn "Could not enable linger — service will start on first login"
        fi
        ok "systemd service installed and enabled"
    else
        systemctl --user start sysbot
        ok "systemd service started (not enabled at boot)"
    fi

    printf "\n  Manage:\n"
    printf "    systemctl --user status sysbot\n"
    printf "    systemctl --user stop   sysbot\n"
    printf "    journalctl --user -u sysbot -f\n"
}

setup_macos() {
    PLIST_DIR="$HOME/Library/LaunchAgents"
    PLIST_FILE="$PLIST_DIR/com.sysbot.sysbot.plist"
    LOG_DIR="$HOME/Library/Logs/sysbot"
    mkdir -p "$PLIST_DIR" "$LOG_DIR"

    launchctl unload -w "$PLIST_FILE" 2>/dev/null || true

    cat > "$PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sysbot.sysbot</string>

    <key>ProgramArguments</key>
    <array>
        <string>$SYSBOT_BIN</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$REPO_DIR</string>

    <key>RunAtLoad</key>
    $( $AUTO_START && echo "<true/>" || echo "<false/>" )

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$LOG_DIR/stderr.log</string>
</dict>
</plist>
EOF

    launchctl load -w "$PLIST_FILE"
    ok "LaunchAgent installed and started"
    $AUTO_START && ok "Auto-starts at login" || true

    printf "\n  Manage:\n"
    printf "    launchctl stop  com.sysbot.sysbot\n"
    printf "    launchctl start com.sysbot.sysbot\n"
    printf "    tail -f %s/stdout.log\n" "$LOG_DIR"
}

if $NEEDS_SERVICE; then
    printf "\n"
    case "$OS" in
        Linux*)  setup_linux  ;;
        Darwin*) setup_macos  ;;
        *) warn "Unsupported OS: $OS — see SERVICE.md for manual setup." ;;
    esac
fi

# ── How to use ────────────────────────────────────────────────────────────────
section "How to use"
case "$PROVIDER" in
    telegram)
        printf "  SysBot is running as a ${BOLD}Telegram${NC} bot.\n\n"
        printf "    1. Open Telegram and find the bot you created with @BotFather\n"
        printf "    2. Send it a message, e.g.  ${BOLD}what's my disk usage on / ?${NC}\n"
        printf "    3. Built-in commands:  ${BOLD}/help${NC} (list tools)  ${BOLD}/clear${NC}  ${BOLD}/history${NC}\n\n"
        printf "  Prefer the terminal? Start a local chat anytime:\n"
        printf "    ${BOLD}sysbot --provider cli${NC}\n"
        ;;
    slack)
        printf "  SysBot is running as a ${BOLD}Slack${NC} bot.\n\n"
        printf "    1. Invite the bot to a channel, or open a direct message with it\n"
        printf "    2. Send it a message, e.g.  ${BOLD}what's my disk usage on / ?${NC}\n"
        printf "    3. Built-in commands:  ${BOLD}/help${NC} (list tools)  ${BOLD}/clear${NC}  ${BOLD}/history${NC}\n\n"
        printf "  Prefer the terminal? Start a local chat anytime:\n"
        printf "    ${BOLD}sysbot --provider cli${NC}\n"
        ;;
    *)  # cli
        printf "  Start chatting in your terminal:\n"
        printf "    ${BOLD}sysbot --provider cli${NC}\n\n"
        printf "  Then try:\n"
        printf "    • Ask in plain language    ${BOLD}what's my disk usage on / ?${NC}\n"
        printf "    • Run a tool directly      ${BOLD}/disk_usage path=/${NC}\n"
        printf "    • List available tools     ${BOLD}/help${NC}\n"
        printf "    • Clear the conversation   ${BOLD}/clear${NC}\n"
        printf "    • Leave                    type ${BOLD}exit${NC}\n"
        ;;
esac

printf "\n  Full usage guide:  ${BOLD}docs/usage.md${NC}\n"
printf "  Activity logs:     ${BOLD}logs/sysbot.log${NC}  and  ${BOLD}logs/traces.jsonl${NC}\n"

hr
if $NEEDS_SERVICE; then
    printf "\n  ${GREEN}${BOLD}SysBot is running.${NC}\n"
else
    printf "\n  ${GREEN}${BOLD}SysBot is ready.${NC}\n"
fi
printf "  Edit ${BOLD}%s/config.yaml${NC} to adjust any settings.\n\n" "$REPO_DIR"
