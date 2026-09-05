# Deployment TODO

Everything needed to run this project as containers. Nothing here is
started yet — the folder currently holds only this file.

Target: Debian host, Docker. Development stays native on Windows
(PowerShell + venv), so nothing below should make local development
require Docker.

---

## Decisions to make first

These change the shape of every file below, so settle them before writing
a Dockerfile.

- [ ] **Postgres: container or host?**
      In a container it is reproducible and `DB_HOST` becomes the compose
      service name. On the host it survives `docker compose down` and is
      easier to back up with existing tooling, but needs Postgres
      listening beyond loopback and `DB_HOST=host.docker.internal`.
- [ ] **Frontend: separate nginx image, or same origin behind one proxy?**
      Strongly prefer one origin (nginx serving the built SPA and
      reverse-proxying `/api` to FastAPI). Two origins forces
      `SameSite=none` + `Secure` on the session cookie and a real CORS
      allowlist, which is more surface for no benefit here.
- [ ] **Where do images live?** Built on the host, or pushed to a registry
      by CI. Decides whether CI/CD config belongs in this folder.

---

## Backend image

- [ ] `deploy/Dockerfile` — python slim base, non-root user, dependencies
      installed in their own layer so `requirements.txt` caches separately
      from source. `WORKDIR` must be the repository root: `logger.py`
      writes to the relative path `app/logs`, and `load_dotenv()` reads
      `./.env`.
- [ ] **Logging to stdout.** `CONSOLE_LOG=true` in the container. Today
      the default is `false` and logs go to a rotating file inside the
      image, where `docker logs` cannot see them and a container replace
      destroys them. Decide whether the `RotatingFileHandler` should be
      skipped entirely when running containerized, or keep writing to a
      mounted volume.
      (Related: `CONSOLE_LOG` is parsed with `get_valid_string` and
      compared with `== "true"`, unlike `COOKIE_SECURE` which uses
      `get_bool`. Worth making consistent while touching this.)
- [ ] **`.env` handling.** Prefer bind-mounting `.env` and letting
      `load_dotenv()` parse it, over compose's `env_file:`. Compose's
      parser is not dotenv's — quoting and `#` differ, so a password
      containing `#` would be silently truncated and look like a wrong
      password rather than a config bug. (The same trap applies to
      systemd's `EnvironmentFile`.)
- [ ] **`DB_HOST`** follows from the Postgres decision above.
- [ ] **Health check.** There is no health endpoint today. Compose and any
      future orchestrator both want one. A `GET /health` that checks the
      connection pool is enough — it must not require authentication.
- [ ] **Restart policy.** `restart: unless-stopped` gives crash-restart and
      start-on-boot together, provided `docker.service` is enabled. Note
      there is no clean equivalent to systemd's `StartLimitBurst`, so a
      crash-on-startup fault retries forever with backoff instead of
      failing loudly. `on-failure:10` caps retries but will not come back
      after a host reboot.
- [ ] **`host` and `port` are hardcoded** in `app/main.py`
      (`0.0.0.0:8000`). Correct inside a container, but make them
      configurable rather than leaving it as luck.
- [ ] **Verify the event loop policy** in `app/main.py`. It forces a
      selector loop for Windows; confirm the platform guard means Linux
      containers get the default policy.

## Frontend image

- [ ] `npm run build` → static assets served by nginx. Multi-stage build so
      Node does not ship in the runtime image.
- [ ] **`VITE_API_BASE_URL` is baked in at build time, not read at
      runtime.** `ui/src/api/client.ts` reads `import.meta.env`, which Vite
      substitutes during the build. One image therefore cannot serve two
      environments. Either build per environment, or serve the SPA from the
      same origin as the API so the default relative path just works — a
      further reason to prefer the single-origin option above.
- [ ] **nginx needs an SPA fallback** (`try_files $uri /index.html`), or a
      hard refresh on any route other than `/` returns 404 under
      `BrowserRouter`.
- [ ] **CORS is hardcoded.** `app/runtime/server.py` sets
      `allow_origins=["http://localhost:5173"]`. Must become configurable,
      or become unnecessary by serving both from one origin.
- [ ] **SSE through nginx.** `X-Accel-Buffering: no` is already sent by the
      app, but confirm `proxy_buffering off` and a long
      `proxy_read_timeout` on the `/events` location, or streams will stall
      or be cut.

## Before the first real deployment

- [ ] **`COOKIE_SECURE=true`** once TLS is in front. It is `false` now for
      plain-HTTP localhost.
- [ ] **CSRF.** Deliberately deferred during development. `SameSite=lax`
      covers most of it, but revisit before anyone outside the team logs
      in — especially if the single-origin decision is reversed.
- [ ] **Rotate every credential.** `DB_PASSWORD` and
      `AUTH_BOOTSTRAP_PASSWORD` are development values. Longer term these
      belong in Docker secrets or the host's secret store, not `.env`.
- [ ] **Migrations.** `init_db.create_tables()` runs at startup and uses
      `CREATE TABLE IF NOT EXISTS`, which silently does nothing when a
      table already exists but has changed. This is fine today only
      because the database is disposable. **The first real deployment ends
      that**, and schema changes after it need Alembic or an equivalent.
      This is the single item here that is cheap now and expensive later.
- [ ] **Postgres volume and backups**, if Postgres ends up containerized.
      A named volume is not a backup.

## CI/CD (future — likely lives in this folder)

- [ ] Lint and typecheck on push: `ruff` for `app/`, `tsc -b` and `eslint`
      for `ui/`. Both already run clean locally.
- [ ] Build and push both images, tagged by commit.
- [ ] Deploy step against the Debian host.
- [ ] Note: `ruff` is referenced by `# noqa` comments throughout `app/` but
      is not currently installed in `.venv`. Add it to a dev requirements
      file before wiring it into CI.
