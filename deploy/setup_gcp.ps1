# Provision GCS + BigQuery + Cloud Run for Veritas Claims (Windows).
# Usage: $env:PROJECT_ID="my-project"; .\deploy\setup_gcp.ps1
$ErrorActionPreference = "Stop"

if (-not $env:PROJECT_ID) { throw "Set PROJECT_ID env var first" }
$PROJECT_ID = $env:PROJECT_ID
$REGION = if ($env:REGION) { $env:REGION } else { "us-central1" }
$RAW_BUCKET = if ($env:RAW_BUCKET) { $env:RAW_BUCKET } else { "veritas-medical-raw-$PROJECT_ID" }
$DATASET = if ($env:DATASET) { $env:DATASET } else { "veritas_claims_demo" }
$IMAGE_REPO = "$REGION-docker.pkg.dev/$PROJECT_ID/veritas"

Write-Host ">>> Enabling APIs on $PROJECT_ID"
gcloud config set project $PROJECT_ID
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com storage.googleapis.com bigquery.googleapis.com aiplatform.googleapis.com pubsub.googleapis.com

Write-Host ">>> Artifact Registry"
gcloud artifacts repositories create veritas --repository-format=docker --location=$REGION --quiet 2>$null

Write-Host ">>> GCS bucket gs://$RAW_BUCKET"
gcloud storage buckets create "gs://$RAW_BUCKET" --location=$REGION --quiet 2>$null

Write-Host ">>> BigQuery dataset"
bq --location=US mk -d --description "Veritas Claims canonical" "${PROJECT_ID}:${DATASET}" 2>$null

Write-Host ">>> Build images"
gcloud builds submit --tag "$IMAGE_REPO/pipeline:latest" -f docker/Dockerfile.pipeline .
gcloud builds submit --tag "$IMAGE_REPO/ui:latest" -f docker/Dockerfile.ui .
gcloud builds submit --tag "$IMAGE_REPO/ai-worker:latest" -f docker/Dockerfile.ai_worker .

Write-Host ">>> Deploy pipeline"
gcloud run deploy veritas-pipeline `
  --image "$IMAGE_REPO/pipeline:latest" `
  --region $REGION `
  --allow-unauthenticated `
  --min-instances=0 `
  --max-instances=10 `
  --memory=1Gi `
  --set-env-vars "STORAGE_BACKEND=gcp,GCP_PROJECT_ID=$PROJECT_ID,GCS_RAW_BUCKET=$RAW_BUCKET,GCS_STATE_BUCKET=$RAW_BUCKET,BQ_DATASET=$DATASET,GEMINI_ENABLED=false"

Write-Host ">>> Deploy Ops UI"
gcloud run deploy veritas-ops-ui `
  --image "$IMAGE_REPO/ui:latest" `
  --region $REGION `
  --allow-unauthenticated `
  --min-instances=0 `
  --memory=1Gi `
  --set-env-vars "STORAGE_BACKEND=gcp,GCP_PROJECT_ID=$PROJECT_ID,GCS_RAW_BUCKET=$RAW_BUCKET,GCS_STATE_BUCKET=$RAW_BUCKET,BQ_DATASET=$DATASET"

Write-Host ">>> Upload sample data"
gcloud storage cp -r sample-data/* "gs://$RAW_BUCKET/"

Write-Host "Done."
