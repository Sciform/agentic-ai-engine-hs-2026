# Deployment

This guide covers deploying the application to **Cloud Run**.

Complete the local setup in the [main README](../README.md) first:

- [1. Prerequisites](../README.md#1-prerequisites)
- [2. Google Cloud Setup](../README.md#2-google-cloud-setup): project, billing limit, login, Cloud Storage bucket and Agent Platform API
- [4. Project Setup](../README.md#4-project-setup)
- [5. Configure `.env`](../README.md#5-configure-env)
- [6. Run the Application locally](../README.md#6-run-the-application-locally)

## 1. Cloud Run Deployment

The application deploys to Cloud Run as a **single-container service**:

| Container | Description | Port |
|---|---|---|
| **Main app** | FastAPI + ADK agents (uvicorn) | 8080 |

### 1.1 Architecture

```
Cloud Run instance
┌──────────────────────────────┐
│  ┌────────────────────────┐  │
│  │  Main App              │  │
│  │  (port 8080)           │  │
│  │  FastAPI + ADK agents  │  │
│  └────────────────────────┘  │
└──────────────┬───────────────┘
               │
               ▼
        Agent Platform APIs
        (Sessions, Memory Bank, RAG Engine, Gemini)
        GCS (Artifacts)
        Cloud Trace (OpenTelemetry)
```

Services the app uses on Cloud Run:

- **VertexAiSessionService**: persistent sessions that survive container restarts and scale-out (backed by Agent Runtime in `europe-west3`)
- **VertexAiMemoryBankService**: long-term agent memory (same Agent Runtime)
- **GcsArtifactService**: artifact storage in Cloud Storage
- **Gemini**: LLM inference via Gemini Enterprise Agent Platform

### 1.2 Key files

| File | Purpose |
|---|---|
| `deploy/Dockerfile` | Main app container image |
| `deploy/service.yaml` | Cloud Run service definition (Knative) |
| `deploy/cloudbuild.yaml` | Cloud Build pipeline: builds and pushes the image, then deploys it |
| `scripts/setup_iam.sh` | One-time setup: enables the APIs and grants the IAM roles |

The image installs exactly the package versions in `uv.lock`, without the `dev` group. The ADK evaluation tools are therefore not in the image: evals run locally only.

### 1.3 One-time setup

Run these steps once per project, from the project root. The commands use bash syntax; on Windows, run them in Git Bash.

**1. Enable the APIs and grant the IAM roles:**

```bash
PROJECT_ID=<PROJECT_ID> ./scripts/setup_iam.sh
```

The script enables Agent Platform, Cloud Storage, Cloud Run, Cloud Build, Artifact Registry and Cloud Logging. It then grants roles to two service accounts:

- **Cloud Run runtime service account** (Compute Engine default): Agent Platform, Cloud Storage and logging
- **Cloud Build service account**: push images, deploy to Cloud Run, act as the runtime service account

> **Note:** Newer projects may run Cloud Build as the Compute Engine default service account instead of `<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`. The build log shows which account a build used. If it's the Compute Engine one, pass it to the script: `CLOUDBUILD_SA=<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`.

**2. Create the Artifact Registry repository for the images:**

```bash
gcloud artifacts repositories create agentic-ai-engineering \
  --repository-format=docker \
  --location=europe-west3
```

**3. Allow Cloud Trace export:**

OpenTelemetry traces (FastAPI HTTP spans + ADK agent/LLM/tool spans) are exported to **Cloud Trace** automatically on Cloud Run, over OTLP to the Telemetry API (`telemetry.googleapis.com`). Enable that API and give the runtime service account the `cloudtrace.agent` role, which includes the `telemetry.traces.write` permission:

```bash
PROJECT_ID=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

gcloud services enable telemetry.googleapis.com

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudtrace.agent"
```

View traces in **Cloud Console → Trace → Trace explorer**.

To enable telemetry locally, set `OTEL_ENABLED=true` (requires `gcloud auth application-default login`). To keep only 10 % of traces, set `OTEL_TRACES_SAMPLER_RATIO=0.1`.

**4. Point `deploy/service.yaml` at your bucket:**

Set `GOOGLE_CLOUD_STORAGE_BUCKET` in `deploy/service.yaml` to the bucket you created in the [main README](../README.md#24-create-a-cloud-storage-bucket).

### 1.4 Deploy with Cloud Build (recommended)

From the project root:

```bash
gcloud builds submit --region=europe-west3 --config deploy/cloudbuild.yaml .
```

Cloud Build runs in Google Cloud, so you don't need Docker locally. The pipeline:

1. Builds the image from `deploy/Dockerfile` and tags it with the build ID and `latest`
2. Pushes both tags to Artifact Registry: `europe-west3-docker.pkg.dev/<PROJECT_ID>/agentic-ai-engineering/agentic-ai-engineering`
3. Fills in the project ID and the build ID tag in `deploy/service.yaml`, then deploys a new Cloud Run revision
4. Allows public access, so the chat UI opens without login (see [1.6](#16-public-access))

`gcloud builds submit` uploads your local files, including uncommitted changes. Files listed in `.gitignore`, such as `.env` and `.venv`, are not uploaded.

### 1.5 Deploy manually (step by step)

This requires Docker running locally.

**1. Let Docker push to Artifact Registry** (once):

```bash
gcloud auth configure-docker europe-west3-docker.pkg.dev
```

**2. Build and push the image:**

```bash
docker build -t europe-west3-docker.pkg.dev/<PROJECT_ID>/agentic-ai-engineering/agentic-ai-engineering:latest \
  -f deploy/Dockerfile .
docker push europe-west3-docker.pkg.dev/<PROJECT_ID>/agentic-ai-engineering/agentic-ai-engineering:latest
```

**3. Deploy the service:**

`deploy/service.yaml` contains the placeholder `PROJECT_ID`. Write a copy with your project ID filled in, so the file in the repository stays unchanged:

```bash
sed "s|PROJECT_ID|<PROJECT_ID>|g" deploy/service.yaml > /tmp/service.yaml
gcloud run services replace /tmp/service.yaml --region europe-west3
```

> **Note:** If you redeploy with an unchanged `service.yaml`, Cloud Run may see no change and not create a new revision, so the newly pushed `:latest` image isn't picked up. To avoid this, tag each build with a unique tag, as Cloud Build does with the build ID: use e.g. `TAG=$(date +%Y%m%d-%H%M%S)` in place of `latest` in step 2, and add `-e "s|:latest|:$TAG|g"` to the `sed` command above.

### 1.6 Public access

By default, Cloud Run requires IAM authentication, and the URL answers **403 Forbidden** to everyone else. To open the chat UI without login, the service grants `allUsers` the Cloud Run Invoker role:

```bash
gcloud run services add-iam-policy-binding agentic-ai-engineering \
  --region europe-west3 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

- **Cloud Build** (section 1.4) runs this command in its last step on every deploy. Running it again changes nothing.
- **Manual deploy** (section 1.5): run it once after the first deploy.

> **Note:** Anyone with the URL can then use the agents, and the Gemini calls are billed to your project. `deploy/service.yaml` caps the service at 3 instances, and the budget alert from the [main README](../README.md#22-set-a-gcp-billing-limit) notifies you as spending grows.

To make the service private again, remove the binding and delete step 4 from `deploy/cloudbuild.yaml`, otherwise the next deploy grants it again:

```bash
gcloud run services remove-iam-policy-binding agentic-ai-engineering \
  --region europe-west3 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

### 1.7 Verify the deployment and open the UI

Get the service URL:

```bash
gcloud run services describe agentic-ai-engineering \
  --region europe-west3 \
  --format="value(status.url)"
```

The chat UI is served by the same FastAPI container at the root path (`/`). No separate frontend deployment is needed. When the page is served over `https://`, the WebSocket switches to `wss://` and connects back to the same Cloud Run host.

**With public access** (section 1.6, the default with Cloud Build), open the URL directly:

```
https://<SERVICE_URL>/
```

**If you made the service private**, use the Cloud Run local proxy to access it:

```bash
gcloud run services proxy agentic-ai-engineering \
  --region europe-west3 \
  --port 8080
```

Then open **http://localhost:8080** in your browser. The proxy adds your IAM token to every request.

### 1.8 Environment variables

**Set in `deploy/service.yaml`:**

| Variable | Value | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `PROJECT_ID` | GCP project ID; the placeholder is replaced at deploy time |
| `GOOGLE_CLOUD_LOCATION` | `europe-west3` | Region for Gemini, RAG Engine, Sessions and Memory Bank |
| `GOOGLE_CLOUD_STORAGE_BUCKET` | `agentic-ai-eng-bucket-ew3` | GCS bucket for artifacts; change it to your bucket |
| `GOOGLE_GENAI_USE_ENTERPRISE` | `TRUE` | Call Gemini through Agent Platform (not the AI Studio API) |
| `MEMORY_BANK_LOCATION` | `europe-west3` | Region for Agent Runtime (sessions + memory) |
| `LOG_LEVEL` | `INFO` | Minimum log level |
| `DEFAULT_AGENT_ID` | `greeting_agent` | Agent used when a new connection starts |
| `DEFAULT_LLM_MODEL` | `gemini-3.5-flash` | Gemini model for agent LLM calls |
| `SESSION_BACKEND` | `VERTEX` | Persistent sessions in Agent Runtime |
| `RAG_CORPUS` | *(empty)* | RAG corpus resource name; empty means the app reuses the corpus with its display name, or creates one on first use |
| `AGENT_ENGINE_ID` | *(empty)* | Agent Runtime resource ID; empty means the app reuses the runtime named `agentic-ai-engineering-memory`, or creates it if none exists |
| `OTEL_ENABLED` | `true` | Export traces to Cloud Trace |
| `OTEL_TRACES_SAMPLER_RATIO` | `1.0` | Share of requests that are traced |

**Not set in `deploy/service.yaml`**, so the app's defaults from `app/config.py` apply. To change one, add it to the `env:` list in `deploy/service.yaml`:

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_MODEL` | `gemini-embedding-2` | Embedding model for Memory Bank |
| `EMBEDDING_LOCATION` | `eu` | Endpoint for the Memory Bank embedding model (EU multi-region) |
| `RAG_EMBEDDING_MODEL` | `text-embedding-005` | Embedding model used when the RAG corpus is created |
