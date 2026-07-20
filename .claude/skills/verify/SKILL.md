---
name: verify
description: How to run and drive LeSysBot end-to-end in an isolated scratch environment — CLI, subcommands, and the web dashboard — without touching the user's real ~/.lesysbot or the installed Telegram service.
---

# Verifying LeSysBot changes

## Gotcha first: stale-install shadowing

The install wizard (`scripts/install.sh`) does a **non-editable** `pip install`,
which shadows this repo for any run outside the repo directory (`lesysbot` then
uses the old site-packages copy — new subcommands/flags "don't exist").
Always check and fix before verifying:

```bash
python3 -c "import lesysbot; print(lesysbot.__file__)"   # run from OUTSIDE the repo
pip install -e .                                      # must point at this repo after
```

## Isolated environment

Never drive `~/.lesysbot` — a real Telegram service may be running from it.
All paths anchor to the cwd when no config file is found, and `LESYSBOT_HOME`
redirects the `~/.lesysbot` fallback:

```bash
S=$(mktemp -d)                      # scratch root
mkdir -p "$S/tools/mypkg" "$S/home"
# write tool packages under $S/tools/…, optionally a lock: $S/tools.lock.json
cd "$S" && export LESYSBOT_HOME="$S/home"
```

State then lands in `$S/tool_state.json`, `$S/tools.lock.json`, `$S/logs/`.

## Driving the surfaces

**Subcommand CLI** (`lesysbot tools …`) — just run it from `$S`.
The y/N confirmation reads stdin, so `echo n | lesysbot tools remove X` exercises
the abort path and `-y` skips it.

**Interactive bot + dashboard** — the CLI adapter exits on stdin EOF, so hold
stdin open with `tail -f /dev/null |`. Override the port via env
(`LESYSBOT_<SECTION>__<FIELD>` pattern) to avoid the user's real dashboard on 8765:

```bash
export LESYSBOT_DASHBOARD__PORT=8799
(tail -f /dev/null | lesysbot --provider cli --dashboard > "$S/bot.log" 2>&1 &)
sleep 3
curl -s http://127.0.0.1:8799/api/status | python3 -m json.tool
```

No LLM is needed for the dashboard, slash commands, or tool management; the
health banner just shows unreachable if Ollama is down.

Hot-reload evidence (tool loads/removals/reloads) is in `$S/logs/lesysbot.log`
(INFO level) — the interactive console clamps to WARNING, so don't look there.

**Cleanup:** kill by PID, not `pkill -f` with the launch string — the pattern
matches your own shell's command line and kills it (exit 144). Find the PID
with a bracket trick: `pgrep -f "lesysbot --provider cl[i]"`.
