# Resource Lifecycle — disk, RAM, Docker, logs

Why this exists: the Crimpd parity campaign (Oct 2026) ran up to 27 parallel agents. It left 56
worktrees, 27 forgotten local uvicorn servers (ports 8011–8037), unbounded Docker logs and no
cleanup after deploys. Nothing here is product code; it keeps the machines healthy.

## Thresholds

| Resource | WARN | CRITICAL | Where measured |
|---|---|---|---|
| Mac free disk | < 30 GB | < 15 GB | `resource_janitor.py audit` (first line) |
| VPS disk (`/`) | ≥ 75 % | ≥ 85 % | `deploy/vps-resource-report.sh` |
| VPS RAM | ≥ 85 % in two consecutive reports (sustained) | — | same |

Also tracked in every VPS report: Docker images / containers / volumes / BuildKit cache
(`docker system df`), per-container log size and whether a container has **unbounded** json-file
logs, journald usage, per-container live memory (`docker stats`).

## Mac (local)

```bash
python scripts/resource_janitor.py audit                    # read only
python scripts/resource_janitor.py local-clean              # dry run (default)
python scripts/resource_janitor.py local-clean --apply      # act
```

`local-clean --apply` may: remove worktrees that pass **every** predicate, `git worktree prune`,
`git branch -d` the removed worktree's branch, stop stale test servers (SIGTERM), delete generated
artifacts older than 3 days in surviving worktrees, delete `/tmp/par-e2e-*` style dirs, prune
**dangling** Docker images and BuildKit cache older than 7 days.

It never: uses `--force` / `-D`, touches Docker volumes (hard guard `assert_no_volume_command`,
unit-tested), removes a dirty / unpushed / canonical / current / in-use worktree, removes a worktree
whose `.venv`/`node_modules` other worktrees symlink to, or touches another session's scratchpad.
Anything it cannot determine counts as unsafe.

Watchdog: run `audit` at the start and end of every navigator session; if free disk < 30 GB run
`local-clean` (dry-run first). Below 15 GB stop starting new workers until it is resolved.

**Know where the space actually is.** On the audited Mac the whole pullup tree was ~2.7 GB; the
free-space problem came from outside the project (iCloud/Mobile Documents, Pictures, `~/.ollama`,
Docker Desktop VM, `~/.cache/codex-runtimes`). The janitor deliberately does not touch those.

## VPS (1 vCPU / 1 GB, shared with other projects)

SSH access is intentionally minimal: GitHub Actions' keys are forced-command only
(`./deploy.sh <sha>`, `./deploy-staging.sh <ref>`; see `.claude/skills/deploy-and-verify`). **Do not
widen them for monitoring.** Instead everything runs on the server and reports locally:

1. **Report timer (read-only):** install `deploy/vps-resource-report.sh` to
   `/usr/local/bin/` and `deploy/systemd/vps-resource-report.{service,timer}` to
   `/etc/systemd/system/`; `systemctl enable --now vps-resource-report.timer`. Runs every 6 h,
   writes `/var/lib/resource-report/latest.txt`, exit 1 = WARN / 2 = CRITICAL
   (`systemctl --failed`, `journalctl -t vps-resource-report`). No inbound/outbound access needed.
2. **Post-deploy cleanup:** install `deploy/post-deploy-cleanup.sh` to `/usr/local/bin/`
   (root:root 755). The in-repo copy of `deploy/deploy-run.sh` already calls it as its last step;
   add the same 3 lines to the server's `deploy-staging-run.sh` (it lives only on the VPS):

   ```bash
   if [ -x /usr/local/bin/post-deploy-cleanup.sh ]; then
       /usr/local/bin/post-deploy-cleanup.sh || true
   fi
   ```

   It prunes dangling images and BuildKit cache older than 168 h only; never volumes, never
   containers, never `-a`; failure cannot fail the deploy; prints MB reclaimed.
3. **Deploy-time visibility (optional):** ask the owner to run `vps-resource-report.sh` once after a
   deploy and paste the verdict; no CI change needed.

### Never, on the VPS

`docker volume prune`, `docker system prune --volumes`, `docker system prune -a`, deleting
`pgdata` / `redisdata` / backups / secrets, removing an image a running prod or staging container
uses. Production and staging databases are out of scope for every cleanup.

### Docker log rotation

- `docker-compose.yml` now bounds `app` and `web` logs: `json-file`, `max-size: 10m`,
  `max-file: 3` (≤ 30 MB per container). Applied on the next deploy (containers are recreated).
- `db` and `redis` are **deliberately not** in the compose block: changing `db`'s config makes
  `docker compose up -d app web` recreate Postgres as a dependency. Bound them at daemon level
  during a maintenance window instead:

  ```json
  /etc/docker/daemon.json
  { "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
  ```

  then `systemctl restart docker` (restarts all containers — plan a window; only newly created
  containers pick the default up, so recreate db/redis once afterwards). Until then the report
  flags them as `UNBOUNDED logs`.

### Memory limits — not applied

No `mem_limit` / `deploy.resources` was added: there is no measured VPS RAM data yet (SSH is
forced-command), and on a 1 GB host a wrong limit turns a spike into an OOM-kill restart loop.
Let the report timer collect `docker stats` for a week; set limits only from that evidence, with
headroom, and never on `db`.

## GitHub hygiene

Remote task branches (`parallel/*`, `orch/issue-*`, `integ/*`, `claude/issue-*`) are **not**
mass-deleted. A branch may be deleted only when: its task/issue is closed, the integrated commit
is preserved in `develop/current`/`main`, and no open PR references it (check
`gh pr list --state open --json headRefName`). Failed-Playwright artifact retention stays 14 days.

## Quick reference

| Situation | Action |
|---|---|
| Wave finished | CLEAN stage: `local-clean` dry-run → `--apply`, stop shared test PG |
| Handoff | list retained worktrees + reason in the last status comment |
| Mac < 30 GB | `audit`, then `local-clean`; look at Docker Desktop/caches outside the repo |
| VPS ≥ 75 % | read `latest.txt`; check image/build-cache lines; run post-deploy cleanup |
| VPS ≥ 85 % | stop deploying; owner reviews; never prune volumes |
