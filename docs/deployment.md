# Render deployment (deferred)

The owner selected Render Free and will configure the account later. No cloud service has been created.

The Docker image builds the React workspace and runs the Python API as an unprivileged user. `render.yaml` defines a free web service with a health check. Set the owner password and provider credentials in Render's secret environment settings. Never put them in React or `VITE_` variables.

The image intentionally excludes local datasets and account history. Before running research, provide collected datasets under `/app/data` using the ingestion commands or an approved external store. Live market tools do not refresh the other three specialist datasets.

Render Free has ephemeral storage. SQLite research history, session secrets, memories and pending paper approvals will disappear on replacement or restart. Free instances may sleep, interrupt long research and exceed their available RAM with CrewAI/ADK. This package is a demonstration deployment, not a durable paper-order ledger. Before relying on order execution in a cloud deployment, use persistent storage and reconcile provider order history after every interruption. KAIROS never retries an ambiguous paper submission automatically.

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
