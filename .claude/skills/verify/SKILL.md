---
name: verify
description: How to run and drive SysBot end-to-end in an isolated scratch environment — CLI, subcommands, and the web dashboard — without touching the user's real ~/.sysbot or the installed Telegram service.
---

# Verifying SysBot changes

## Gotcha first: stale-install shadowing

The install wizard (`scripts/install.sh`) does a **non-editable** `pip install`,
which shadows this repo for any run outside the repo directory (`sysbot` then
uses the old site-packages copy — new subcommands/flags "don't exist").
Always check and fix before verifying:

```bash
python3 -c "import sysbot; print(sysbot.__file__)"   # run from OUTSIDE the repo
pip install -e .                                      # must point at this repo after
```

## Isolated environment

Never drive `~/.sysbot` — a real Telegram service may be running from it.
All paths anchor to the cwd when no config file is found, and `SYSBOT_HOME`
redirects the `~/.sysbot` fallback:

```bash
S=$(mktemp -d)                      # scratch root
mkdir -p "$S/tools/mypkg" "$S/home"
# write tool packages under $S/tools/…, optionally a lock: $S/tools.lock.json
cd "$S" && export SYSBOT_HOME="$S/home"
```

State then lands in `$S/tool_state.json`, `$S/tools.lock.json`, `$S/logs/`.

## Driving the surfaces

**Subcommand CLI** (`sysbot tools …`) — just run it from `$S`.
The y/N confirmation reads stdin, so `echo n | sysbot tools remove X` exercises
the abort path and `-y` skips it.

**Interactive bot + dashboard** — the CLI adapter exits on stdin EOF, so hold
stdin open with `tail -f /dev/null |`. Override the port via env
(`SYSBOT_<SECTION>__<FIELD>` pattern) to avoid the user's real dashboard on 8765:

```bash
export SYSBOT_DASHBOARD__PORT=8799
(tail -f /dev/null | sysbot --provider cli --dashboard > "$S/bot.log" 2>&1 &)
sleep 3
curl -s http://127.0.0.1:8799/api/status | python3 -m json.tool
```

No LLM is needed for the dashboard, slash commands, or tool management; the
health banner just shows unreachable if Ollama is down.

Hot-reload evidence (tool loads/removals/reloads) is in `$S/logs/sysbot.log`
(INFO level) — the interactive console clamps to WARNING, so don't look there.

**Cleanup:** kill by PID, not `pkill -f` with the launch string — the pattern
matches your own shell's command line and kills it (exit 144). Find the PID
with a bracket trick: `pgrep -f "sysbot --provider cl[i]"`.
