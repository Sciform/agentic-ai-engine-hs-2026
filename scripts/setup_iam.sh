#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup_iam.sh – Grant the required IAM roles for Cloud Run deployment.
#
# Usage:
#   # Uses defaults from the script:
#   ./scripts/setup_iam.sh
#
#   # Override project / region / service account:
#   PROJECT_ID=my-project REGION=europe-west3 ./scripts/setup_iam.sh
#
# What this script does:
#   1. Enables the required GCP APIs.
#   2. Grants IAM roles to the Cloud Run runtime service account.
#   3. Grants IAM roles to the Cloud Build service account.
# ---------------------------------------------------------------------------
set -euo pipefail

# ── Configurable variables ────────────────────────────────────────────────
PROJECT_ID="${PROJECT_ID:-agentic-ai-eng-489113}"
REGION="${REGION:-europe-west3}"

# Cloud Run uses the Compute Engine default SA unless overridden.
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
RUNTIME_SA="${RUNTIME_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
CLOUDBUILD_SA="${CLOUDBUILD_SA:-${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com}"

echo "Project:          ${PROJECT_ID}"
echo "Project number:   ${PROJECT_NUMBER}"
echo "Region:           ${REGION}"
echo "Runtime SA:       ${RUNTIME_SA}"
echo "Cloud Build SA:   ${CLOUDBUILD_SA}"
echo ""

# ── 1. Enable required APIs ──────────────────────────────────────────────
echo "==> Enabling APIs ..."
APIS=(
  aiplatform.googleapis.com          # Agent Platform, formerly Vertex AI (agents, RAG, sessions, memory)
  storage.googleapis.com             # Cloud Storage (artifacts, RAG imports)
  run.googleapis.com                 # Cloud Run
  cloudbuild.googleapis.com          # Cloud Build CI/CD
  artifactregistry.googleapis.com    # Artifact Registry (container images)
  logging.googleapis.com             # Cloud Logging
)
gcloud services enable "${APIS[@]}" --project="${PROJECT_ID}"
echo ""

# ── 2. Cloud Run runtime service account roles ──────────────────────────
echo "==> Granting roles to runtime SA (${RUNTIME_SA}) ..."

RUNTIME_ROLES=(
  # Agent Platform – LLM inference, RAG, Agent Runtime, Memory Bank, Sessions
  roles/aiplatform.user

  # Cloud Storage – read/write artifacts, read RAG import source files
  roles/storage.objectUser

  # Logging – write structured logs (granted by default on Cloud Run,
  # but listed explicitly for completeness)
  roles/logging.logWriter
)

for role in "${RUNTIME_ROLES[@]}"; do
  echo "  ${role}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="${role}" \
    --condition=None \
    --quiet > /dev/null
done
echo ""

# ── 3. Cloud Build service account roles ─────────────────────────────────
echo "==> Granting roles to Cloud Build SA (${CLOUDBUILD_SA}) ..."

CLOUDBUILD_ROLES=(
  # Build & push container images
  roles/storage.admin
  # Push images to Artifact Registry
  roles/artifactregistry.writer

  # Deploy to Cloud Run
  roles/run.admin

  # Act as the runtime service account during deploy
  roles/iam.serviceAccountUser

  # Write build logs
  roles/logging.logWriter
)

for role in "${CLOUDBUILD_ROLES[@]}"; do
  echo "  ${role}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="${role}" \
    --condition=None \
    --quiet > /dev/null
done
echo ""

echo "==> Done. IAM roles configured for project ${PROJECT_ID}."
echo ""
echo "Roles summary:"
echo "  Runtime SA (Cloud Run):"
for role in "${RUNTIME_ROLES[@]}"; do echo "    - ${role}"; done
echo "  Cloud Build SA:"
for role in "${CLOUDBUILD_ROLES[@]}"; do echo "    - ${role}"; done
