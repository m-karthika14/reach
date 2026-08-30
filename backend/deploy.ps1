# REACH backend -> Google Cloud Run.
# Reads secrets from backend/.env (which is gitignored + dockerignored, so they
# are passed as Cloud Run env vars, never baked into the image).
#
# Requires: gcloud CLI authenticated, billing enabled.
#   $env:Path += ";K:\g-cli\google-cloud-sdk\bin"

$ErrorActionPreference = "Stop"

$PROJECT = "reach-agent-507107"
$REGION  = "asia-south1"
$SERVICE = "reach-backend"

gcloud config set project $PROJECT | Out-Null

# ---- APIs -------------------------------------------------------------------
gcloud services enable `
    run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
    aiplatform.googleapis.com firestore.googleapis.com

# ---- IAM for the Cloud Run runtime service account -------------------------
$NUM = (gcloud projects describe $PROJECT --format "value(projectNumber)")
$SA  = "$NUM-compute@developer.gserviceaccount.com"
Write-Host "Granting Vertex AI + Firestore to $SA" -ForegroundColor Cyan
gcloud projects add-iam-policy-binding $PROJECT --member "serviceAccount:$SA" --role "roles/aiplatform.user" | Out-Null
gcloud projects add-iam-policy-binding $PROJECT --member "serviceAccount:$SA" --role "roles/datastore.user"   | Out-Null

# ---- Build env-vars string from .env --------------------------------------
$envPairs = @("GOOGLE_CLOUD_PROJECT=$PROJECT", "GOOGLE_CLOUD_LOCATION=$REGION")
if (Test-Path ".env") {
    foreach ($line in Get-Content ".env") {
        if ($line -match '^\s*(RAZORPAY_[A-Z_]+)\s*=\s*(.+?)\s*$') {
            if ($Matches[2]) { $envPairs += "$($Matches[1])=$($Matches[2])" }
        }
    }
}
$envArg = ($envPairs -join ",")
if ($envArg -match "RAZORPAY_KEY_ID") { Write-Host "Razorpay keys: found in .env -> real mode" -ForegroundColor Green }
else { Write-Host "Razorpay keys: not in .env -> payments will run in MOCK mode" -ForegroundColor Yellow }

# ---- Deploy from source (Cloud Build makes the image) --------------------
gcloud run deploy $SERVICE `
    --source . `
    --region $REGION `
    --allow-unauthenticated `
    --min-instances 0 `
    --memory 1Gi `
    --timeout 300 `
    --set-env-vars "$envArg"

$URL = (gcloud run services describe $SERVICE --region $REGION --format "value(status.url)")
Write-Host ""
Write-Host "Service URL: $URL" -ForegroundColor Green
Write-Host "Verify:      curl $URL/         (expect payments_mode + session_backend)"
Write-Host "Logs:        gcloud run services logs read $SERVICE --region $REGION"
