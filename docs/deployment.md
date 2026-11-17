# Render deployment (deferred)

The owner selected Render Free and will configure the account later. No cloud service has been created.

The Docker image builds the React workspace and runs the Python API as an unprivileged user. `render.yaml` defines a free web service with a health check. Set the owner password and provider credentials in Render's secret environment settings. Never put them in React or `VITE_` variables.

The image intentionally excludes local datasets and account history. Before running research, provide collected datasets under `/app/data` using the ingestion commands or an approved external store. Live market tools do not refresh the other three specialist datasets.

Render Free has ephemeral disk and may sleep, interrupt long research and exceed its RAM with CrewAI/ADK. KAIROS keeps its data in Postgres (Supabase) when `DATABASE_URL` is set, so history survives restarts and redeploys (see Storage). KAIROS never retries an ambiguous paper submission automatically.

## Storage

- `DATABASE_URL` set: everything below lives in Postgres. Use the Supabase pooler URL; the server uses a small pool (max 4 connections), requires TLS and a 30 s statement timeout. If the database is unreachable at startup the app **refuses to start** with a clear error (paper-order approvals must never silently fall back to a disk a restart wipes). `GET /api/health` reports `"storage": "postgres"` or `"sqlite"`.
- `DATABASE_URL` unset: local SQLite files under the runtime directory, exactly as before (development and offline tests).
- Tables: `research_runs`, `research_events` (indexed on `run_id, id` for the live event stream), `paper_approvals`, `kairos_run_evidence` (every per-run evidence table and `provenance.json` as JSONB, used to rebuild reports after a restart), `kairos_memory` (research memory; pgvector extension is enabled when available, embeddings are stored as JSON), `kairos_settings` (session-signing secret fallback). Tables are created automatically on startup.
- Row Level Security is enabled on every table with no policies, so Supabase's public REST/anon roles cannot read KAIROS data; the server connects with the database role from `DATABASE_URL`, which bypasses RLS. Never expose that URL.
- Set `KAIROS_SESSION_SECRET` so logins survive restarts; without it the secret is stored in `kairos_settings` (Postgres) or a file (SQLite mode).
- One database should serve one running KAIROS instance: on startup a server marks any QUEUED/RUNNING run as INTERRUPTED, and only one run may be active at a time. Do not point a local server at the production database while a run is in progress.
- Optional tests against a real database: `KAIROS_TEST_DATABASE_URL=... pytest tests/test_storage.py` (each test uses a throwaway schema that is dropped afterwards).

Local verification:

```bash
npm --prefix web ci
npm --prefix web run build
python -m kairos.web.app
```

Optional container verification when Docker is installed:

```bash
docker build -t kairos .
docker run --rm -p 8000:8000 --env-file .env -e KAIROS_WEB_PASSWORD=your-local-password -v "$PWD/data:/app/data" kairos
```

The web API refuses public binding without `KAIROS_WEB_PASSWORD`. Serve HTTPS publicly; the session cookie becomes secure on HTTPS. One owner password is a personal workspace boundary, not a multi-user identity system.
