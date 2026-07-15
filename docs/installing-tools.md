# Installing tools from GitHub

Any GitHub repo that contains a tool folder package can be installed with one
command — no registry, no catalog, just the link:

```bash
sysbot tools install owner/repo                 # whole repo
sysbot tools install owner/repo/tools/gpu-temp  # one package inside a bigger repo
sysbot tools install owner/repo@v1.2            # pin a branch, tag, or commit
sysbot tools install https://github.com/owner/repo
```

SysBot downloads the repo as a zip (no git needed), shows you what it found —
package names, versions, files — and asks for confirmation before anything is
written. Installed packages land in your tools dir (`~/.sysbot/tools/` for an
installed setup); a running bot with hot-reload picks them up immediately.

## Manage what's installed

```bash
sysbot tools list             # every tool: status, source package, install origin
sysbot tools info gpu_temp    # params, gating, and where it was installed from
sysbot tools enable/disable gpu_temp
sysbot tools remove gpu_temp  # deletes the package (asks y/N)
```

`list`/`info` show provenance for installed packages (`acme/repo@commit`);
tools you wrote yourself just say `local`. See
[Using SysBot §9](usage.md#9-managing-tools-enable--disable--remove) for the
management commands and the [Dashboard](dashboard.md) for the point-and-click
equivalent.

## Source spec grammar

```
owner/repo                       default branch (HEAD)
owner/repo@ref                   branch, tag, or 40-hex commit SHA
owner/repo/sub/dir[@ref]         a package inside a bigger repo
https://github.com/owner/repo[.git]
https://github.com/owner/repo/tree/REF[/sub/dir]
git@github.com:owner/repo
```

Branch names containing `/` are ambiguous in `/tree/` URLs — use the
`owner/repo/subdir@feature/x` short form for those.

## What counts as a tool package in a repo

- **Repo root holds `tool.py`** (any non-`_` `.py`): the repo *is* one package,
  named after the repo.
- **Otherwise**: every immediate subdirectory that holds a non-`_` `.py` file is
  a package (`tests/`, `docs/`, dot- and `_`-prefixed dirs are skipped). Install
  just one of them with `--only NAME` (repeatable), or point the spec at its
  subdir.

## Trust model — read this once

Installed tools are **arbitrary Python code running as your user** the moment
the bot loads them. There is no sandbox. Before confirming an install:

- Install only from repos you trust (read `tool.py` — they're small).
- Prefer pinning: `@tag` or `@commit-sha`. The exact commit you got is recorded
  in the lock file (`tools.lock.json`) either way.
- The plan printed before the y/N prompt lists every file that will land in
  your tools dir. `--yes` skips the prompt — use it only in scripts you trust.

## Python dependencies

If a package ships a `requirements.txt`, SysBot **prints** the
`pip install -r …` command instead of running it. Opt in with
`--install-deps` to run it automatically.

## Private repos

Set `GITHUB_TOKEN` (or `GH_TOKEN`) and it is sent as a Bearer token:

```bash
GITHUB_TOKEN=ghp_… sysbot tools install you/private-tools
```

## Collisions & local tools

The install refuses to overwrite a folder it didn't create (your hand-written
tools are never clobbered) — `--force` overrides. Re-installing a package the
lock already owns replaces it in place; that's also how you update one.

## Config

```yaml
mcp:
  tools_dir: "./tools"          # where packages are installed & loaded from
  lock_file: tools.lock.json    # install provenance (repo, pinned commit)
```

Both anchor next to the active `config.yaml` (so `~/.sysbot/` when installed) —
`sysbot tools install` and the bot always resolve the same locations.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Not found: owner/repo@ref` | Check the spec; for private repos set `GITHUB_TOKEN`. |
| `tools dir already has X` | That folder wasn't installed by SysBot — `--force` to overwrite it. |
| Installed but not in `/help` | Restart the bot if `hot_reload` is off; check the log for import errors. |
| Tool needs a pip package | Re-run with `--install-deps`, or run the printed `pip install -r` line. |
