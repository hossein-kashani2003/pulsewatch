# PulseWatch

A self-hosted uptime monitoring service. Register URLs, and PulseWatch checks them on a schedule, stores the history, and shows live status on a dashboard.

## Architecture




Docker networks:

| Network | Internet access | Members |
|---|---|---|
| frontend | yes | nginx, api1, api2 |
| backend (`internal: true`) | no | api1, api2, worker, db, redis |
| egress | yes | worker only |

## Tech stack

Python 3.12 / FastAPI, PostgreSQL 16, Redis 7, nginx, Docker Compose, GitHub Actions, GHCR.

## Design notes

- **Separate worker.** Checks run outside the API, so scaling the API to several replicas never duplicates a check.
- **Redis scheduling.** A key `due:<id>` is created with `SET NX EX <interval>`. Whichever worker creates the key runs that check, so workers can be scaled safely.
- **SSRF protection.** The worker can reach both the internet and the database, so monitor URLs must resolve to public addresses (private, loopback and link-local ranges are rejected) and redirects are not followed.
- **Authentication.** Write endpoints (`POST`, `DELETE`) require an `X-API-Key` header. If `API_KEY` is unset, all writes are rejected (fail closed).
- **Network isolation.** The database and Redis live on an internal network with no route to the internet.

## Getting started

Requirements: Docker with the Compose plugin, and `openssl`.

```bash
git clone git@github.com:hossein-kashani2003/pulsewatch.git
cd pulsewatch
cp .env.example .env        # set the passwords and API_KEY (openssl rand -hex 24)
bash scripts/gen-cert.sh    # self-signed certificate for local use
docker compose up -d --build
```

Open `https://<host>/` (the browser will warn about the self-signed certificate).

## API

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | no | Dashboard |
| GET | `/health` | no | Health check (Postgres, Redis, worker heartbeat) |
| GET | `/api/monitors` | no | List monitors with latest status |
| POST | `/api/monitors` | `X-API-Key` | Create a monitor |
| DELETE | `/api/monitors/{id}` | `X-API-Key` | Delete a monitor |
| GET | `/api/monitors/{id}/history` | no | Recent check results |
| GET | `/api/monitors/{id}/stats` | no | 24h uptime and average latency |

Interactive docs are served at `/docs`.

```bash
curl -sk -X POST https://<host>/api/monitors \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"Example","url":"https://example.com","interval_s":30}'
```

## CI/CD

GitHub Actions (`.github/workflows/ci-cd.yml`):

1. **test**: ruff, pytest and `docker compose config` validation (on every push and pull request).
2. **build**: build the image and push it to GHCR (on pushes to `main`).
3. **deploy**: pull the new image and restart the stack on a self-hosted runner.

## Tests

```bash
cd app && pip install -r requirements-dev.txt && pytest
```
