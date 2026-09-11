# Deployment

The backend runs as a Docker container; the frontend is a static build served by
nginx on the host. One EC2 instance, one external (RDS) PostgreSQL, no domain —
the site answers on the instance's public IP over plain HTTP. This is a
throwaway environment for client evaluation, not hardened production; see
**Accepted risks** below.

## Topology

```
browser ─→ http://<EC2-public-IP>/…
              │
         nginx (host, :80)
         ├─ /assets/    → /var/www/llm-system/assets/     (hashed files, cached 1y)
         ├─ /           → a real file, else index.html    (SPA client-side routing)
         ├─ /events     → proxy → 127.0.0.1:8000          (SSE: proxy_buffering off, no read timeout)
         └─ /auth /conversations /files /documents /settings /health
                        → proxy → 127.0.0.1:8000
                                     │
                              docker container "api"
                              (published ONLY on 127.0.0.1:8000)
                                     │
                              uvicorn app.main --api ─→ RDS PostgreSQL
```

- The API container binds `127.0.0.1:8000` — not publicly reachable. Only nginx,
  on the same host, proxies to it. That is the whole access model for port 8000;
  no firewall sits in front of it.
- Single origin: the browser only ever talks to `http://<IP>`. No CORS in play,
  and the session and CSRF cookies are same-origin.

## Files

### In the repo

| Path | Role |
|---|---|
| `deploy/Dockerfile` | Backend image. `python -m app.main --api`, non-root, `WORKDIR=/app`. Bakes `ENV CONSOLE_LOG=true` so container logs reach `docker logs` (a real env var beats the `.env` file). |
| `deploy/docker-compose.yml` | **Local/dev.** Builds the image; reaches the host's PostgreSQL via `host.docker.internal`. |
| `deploy/docker-compose.prod.yml` | **Production.** Pulls the image from Docker Hub (`API_IMAGE`), no `build:`, no `db:` service — the database is RDS via `DATABASE_URL` in `.env`. |
| `deploy/nginx/llm-system.conf` | The host nginx site. Version-controlled so CI can ship it. |
| `.dockerignore` | Keeps `ui/`, `.git/`, docs out of the image build context. |
| `.github/workflows/deploy.yml` | The CI/CD pipeline (below). |

### On the EC2 box

| Path | Contents | Maintained by |
|---|---|---|
| `/opt/llm-system/docker-compose.prod.yml` | prod compose | CI — `scp`, every deploy |
| `/opt/llm-system/llm-system.conf` | nginx site | CI — `scp`, every deploy |
| `/opt/llm-system/.env` | secrets, RDS URL, all runtime config | **you, by hand** — CI never touches it |
| `/var/www/llm-system/` | the built SPA (`index.html`, `assets/`) | CI — `scp ui/dist/`, every deploy |
| `/etc/nginx/sites-enabled/llm-system` | symlink → `/opt/llm-system/llm-system.conf` | you, once |

`.env` is owned `admin:admin`, mode `600`. The container runs as UID 1000, which
is `admin` on Debian, so `600` is still readable inside the container through the
read-only bind mount.

## Server `.env`

Same keys as the local `.env` (see the root `README.md` table), with these
deltas:

| Key | Value |
|---|---|
| `DATABASE_URL` | `postgresql://<user>:<url-encoded-pass>@<rds-endpoint>:5432/llm_system?sslmode=require` |
| `CSRF_TRUSTED_ORIGINS` | `http://<EC2-public-IP>` — the origin the browser actually sends. A wrong value makes every POST a 403. |
| `CSRF_SECRET` | a fixed random string. If it changes, every already-issued CSRF cookie stops validating until the next page load. |
| `COOKIE_SECURE` | `false` — there is no TLS on a bare IP. |
| `LOG_LEVEL` | `INFO` |
| `CONVERSATION_LOG` | `false` |

No `DB_*` split parts — `DATABASE_URL` wins whenever it is set.

## CI/CD pipeline

`.github/workflows/deploy.yml`. Trigger: a push to the `deploy` branch, or **Run
workflow** on `main` from the Actions tab (`workflow_dispatch`).
`concurrency: deploy-production` keeps two deploys from overlapping.

| Job | What it does |
|---|---|
| `build` | `npm ci`, `eslint`, `npm run build` (`tsc -b && vite build`, so it also typechecks) → uploads `ui/dist/` as an artifact; `python -m compileall app` as a cheap backend gate |
| `image` | `docker build` from `deploy/Dockerfile` → push `kashoummt/llm-system:<git-sha>` **and** `kashoummt/llm-system:deploy` to Docker Hub (private repo) |
| `deploy` | needs both. Downloads `dist/`; over SSH: `rm -rf /var/www/llm-system/assets`, `scp -r ui/dist/.` there, `scp` the nginx conf to `/opt/llm-system/`; then `docker login`, `API_IMAGE=<sha> docker compose -f docker-compose.prod.yml pull && up -d`, `nginx -t && systemctl reload nginx`, poll `/health` for up to 60s |

The image tag deployed is the exact commit SHA, so a rollback names a specific
known-good build. Every remote `ssh`/`scp` call passes
`-o BatchMode=yes -o ConnectTimeout=15`, so an auth or reachability problem fails
in seconds instead of hanging.

### Release

```
git push origin main:deploy
```

Fast-forwards `deploy` to `main` and triggers the run. (Or Actions → Deploy to
production → Run workflow → `main`.) Do not mix the CLI push with a web PR merge
into `deploy` — a merge commit there makes the next `push origin main:deploy`
non-fast-forward.

### Rollback

`git revert <bad-sha>` on `deploy` and push, or **Re-run all jobs** on an older
green run from the Actions tab.

### One-time setup (done once; kept here for a rebuild)

GitHub repo → Settings → Secrets and variables → Actions:

| Kind | Name | Value |
|---|---|---|
| Variable | `DOCKERHUB_USERNAME` | `kashoummt` |
| Variable | `EC2_HOST` | the instance's public IP |
| Variable | `EC2_USER` | `admin` |
| Secret | `DOCKERHUB_TOKEN` | Docker Hub personal access token, Read & Write |
| Secret | `EC2_SSH_KEY` | private key of a **dedicated** CI keypair; its public half appended to the box's `~/.ssh/authorized_keys` |
| Secret | `EC2_KNOWN_HOSTS` | `<IP> ssh-ed25519 <key>` — take it from `/etc/ssh/ssh_host_ed25519_key.pub` on the box (a Windows `ssh-keyscan` may be too old to negotiate Debian 13's post-quantum KEX) |

- **EC2 security group:** inbound `22` from `0.0.0.0/0` (the runner's IP is not
  predictable), inbound `80` from `0.0.0.0/0`.
- **RDS security group:** inbound `5432` from the EC2 security group only.
- **The box needs:** Docker + the compose plugin, nginx, and the
  `sites-enabled` symlink. `admin` needs passwordless sudo (Debian's default) for
  the nginx reload. `rsync` is **not** needed — the pipeline uses `scp`.

## Accepted risks — do not "fix" these as bugs

- **Port 22 open to the world** (key-only auth). Fine for a disposable box.
  Hardening path: AWS SSM Session Manager (no inbound SSH at all) or a
  bastion/VPN.
- **HTTP only, `COOKIE_SECURE=false`.** The session cookie travels in cleartext.
  Before this is real production: a domain + TLS (Let's Encrypt), then
  `COOKIE_SECURE=true` and `CSRF_TRUSTED_ORIGINS=https://…`.
- **The database and the whole environment are disposable** — no migration
  tooling beyond what the app runs itself, no backups, no HA.

## Backlog

- Confirm `?sslmode=require` is on `DATABASE_URL` (RDS traffic is already TLS via
  libpq's default `prefer`; the flag just makes it explicit and fail loudly).
- CI `image` job: add `docker run --rm <image> python -c "import app.main"` so a
  bad import fails before deploy rather than at the health check.
- `.gitattributes` → `*.conf text eol=lf` (the nginx conf picks up CRLF on a
  Windows checkout; nginx tolerates it, but it is untidy).
- Prune old Docker Hub tags — one `:<sha>` accumulates per deploy.

## Local Docker (not the deploy path)

```
# from the repo root, with the host's PostgreSQL running
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f
docker compose -f deploy/docker-compose.yml down
```

The local `.env` must use the split `DB_*` parts (or point `DATABASE_URL` at
`host.docker.internal`), because `localhost` inside the container is the
container, not the host.
