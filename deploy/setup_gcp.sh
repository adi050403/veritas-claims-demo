#!/usr/bin/env bash
# Provision GCS + BigQuery + Cloud Run for Veritas Claims.
# Usage: PROJECT_ID=my-project REGION=us-central1 bash deploy/setup_gcp.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
RAW_BUCKET="${RAW_BUCKET:-veritas-medical-raw-${PROJECT_ID}}"
DATASET="${DATASET:-veritas_claims_demo}"
IMAGE_REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/veritas"

echo ">>> Enabling APIs on ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com \
  aiplatform.googleapis.com \
  pubsub.googleapis.com

echo ">>> Creating Artifact Registry"
gcloud artifacts repositories create veritas \
  --repository-format=docker \
  --location="${REGION}" \
  --quiet || true

echo ">>> Creating GCS bucket gs://${RAW_BUCKET}"
gcloud storage buckets create "gs://${RAW_BUCKET}" --location="${REGION}" --quiet || true

echo ">>> Creating BigQuery dataset"
bq --location=US mk -d --description "Veritas Claims canonical" "${PROJECT_ID}:${DATASET}" || true

echo ">>> Building images"
gcloud builds submit --tag "${IMAGE_REPO}/pipeline:latest" -f docker/Dockerfile.pipeline .
gcloud builds submit --tag "${IMAGE_REPO}/ui:latest" -f docker/Dockerfile.ui .
gcloud builds submit --tag "${IMAGE_REPO}/ai-worker:latest" -f docker/Dockerfile.ai_worker .

echo ">>> Deploy Cloud Run pipeline (min instances = 0)"
gcloud run deploy veritas-pipeline \
  --image "${IMAGE_REPO}/pipeline:latest" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=10 \
  --memory=1Gi \
  --set-env-vars "STORAGE_BACKEND=gcp,GCP_PROJECT_ID=${PROJECT_ID},GCS_RAW_BUCKET=${RAW_BUCKET},GCS_STATE_BUCKET=${RAW_BUCKET},BQ_DATASET=${DATASET},GEMINI_ENABLED=false"

echo ">>> Deploy Ops UI"
gcloud run deploy veritas-ops-ui \
  --image "${IMAGE_REPO}/ui:latest" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --min-instances=0 \
  --memory=1Gi \
  --set-env-vars "STORAGE_BACKEND=gcp,GCP_PROJECT_ID=${PROJECT_ID},GCS_RAW_BUCKET=${RAW_BUCKET},GCS_STATE_BUCKET=${RAW_BUCKET},BQ_DATASET=${DATASET}"

echo ">>> Create AI worker Job"
gcloud run jobs create veritas-ai-worker \
  --image "${IMAGE_REPO}/ai-worker:latest" \
  --region "${REGION}" \
  --memory=1Gi \
  --set-env-vars "STORAGE_BACKEND=gcp,GCP_PROJECT_ID=${PROJECT_ID},GCS_RAW_BUCKET=${RAW_BUCKET},BQ_DATASET=${DATASET},GEMINI_ENABLED=true,VERTEX_LOCATION=${REGION}" \
  --quiet || gcloud run jobs update veritas-ai-worker \
  --image "${IMAGE_REPO}/ai-worker:latest" \
  --region "${REGION}"

echo ">>> Upload sample data"
gcloud storage cp -r sample-data/* "gs://${RAW_BUCKET}/"

echo "Done. Trigger pipeline:"
echo "  curl -X POST \$(gcloud run services describe veritas-pipeline --region ${REGION} --format='value(status.url)')/run -H 'Content-Type: application/json' -d '{}'"
