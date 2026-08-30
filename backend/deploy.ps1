# REACH backend -> Cloud Run (Phase 2, Steps 2.19-2.21).
# Run this ONLY after the local flow works end to end.
# Requires: gcloud CLI, authenticated, billing enabled.

$ErrorActionPreference = "Stop"

$PROJECT  = "reach-agent-507107"
$REGION   = "asia-south1"
$SERVICE  = "reach-backend"

gcloud config set project $PROJECT

# Enable the APIs we need (safe to re-run).
gcloud services enable `
    run.googleapis.com `
    cloudbuild.googleapis.com `
    artifactregistry.googleapis.com `
    aiplatform.googleapis.com

# Build + deploy straight from source (Cloud Build makes the image).
gcloud run deploy $SERVICE `
    --source . `
    --region $REGION `
    --allow-unauthenticated `
    --min-instances 0 `
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT"

Write-Host ""
Write-Host "Service URL:" -ForegroundColor Green
gcloud run services describe $SERVICE --region $REGION --format "value(status.url)"
Write-Host ""
Write-Host "Test it:  curl <URL>/health"
Write-Host "Logs:     gcloud run services logs read $SERVICE --region $REGION"
