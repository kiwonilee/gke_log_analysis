#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# ANSI Color Codes for beautiful output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0;m' # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${BLUE}   🚀 GKE SRE Frontend Cloud Run Deployer  ${NC}"
echo -e "${BLUE}====================================================${NC}"

# Ensure we are in the frontend directory where this script and Dockerfile reside
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Try to dynamically load from parent .env file if it exists
ENV_PATH="../.env"
if [ -f "$ENV_PATH" ]; then
    echo -e "${YELLOW}ℹ .env file found. Auto-loading configuration...${NC}"
    # Read variables from .env ignoring comments and blank lines
    export GOOGLE_CLOUD_PROJECT=$(grep -E '^GOOGLE_CLOUD_PROJECT=' "$ENV_PATH" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    export GOOGLE_CLOUD_LOCATION=$(grep -E '^GOOGLE_CLOUD_LOCATION=' "$ENV_PATH" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    export GCP_RESOURCES_LOCATION=$(grep -E '^GCP_RESOURCES_LOCATION=' "$ENV_PATH" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    export SERVICE_ACCOUNT=$(grep -E '^SERVICE_ACCOUNT=' "$ENV_PATH" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    export BQ_DATASET_ID=$(grep -E '^BQ_DATASET_ID=' "$ENV_PATH" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    export AGENT_RUNTIME_ID=$(grep -E '^AGENT_RUNTIME_ID=' "$ENV_PATH" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    export REASONING_ENGINE_ID=$(grep -E '^REASONING_ENGINE_ID=' "$ENV_PATH" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    export GOOGLE_GENAI_USE_VERTEXAI=$(grep -E '^GOOGLE_GENAI_USE_VERTEXAI=' "$ENV_PATH" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
fi

# Configurable parameters with fallbacks
PROJECT_ID=${GOOGLE_CLOUD_PROJECT:-"gcp-sandbox-kwlee"}
REGION=${GCP_RESOURCES_LOCATION:-"us-central1"}
SERVICE_NAME="gke-log-analysis"
SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT:-"sa-gke-log-analysis@gcp-sandbox-kwlee.iam.gserviceaccount.com"}

echo -e "Deploying with the following target parameters:"
echo -e "  • Project ID:      ${GREEN}${PROJECT_ID}${NC}"
echo -e "  • Region:          ${GREEN}${REGION}${NC}"
echo -e "  • Service Name:    ${GREEN}${SERVICE_NAME}${NC}"
echo -e "  • Service Account: ${GREEN}${SERVICE_ACCOUNT_EMAIL}${NC}"
echo -e "----------------------------------------------------"

echo -e "${YELLOW}▶ Initiating secure Cloud Build & Serverless Container Deployment...${NC}"

# Run the gcloud deploy command
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$SERVICE_ACCOUNT_EMAIL" \
  --allow-unauthenticated \
  --memory 2Gi \
  --set-env-vars GOOGLE_CLOUD_PROJECT="$PROJECT_ID",GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}",GCP_RESOURCES_LOCATION="$REGION",PYTHONUNBUFFERED=1,BQ_DATASET_ID="${BQ_DATASET_ID:-ob_log}",AGENT_RUNTIME_ID="${AGENT_RUNTIME_ID:-$REASONING_ENGINE_ID}",REASONING_ENGINE_ID="${REASONING_ENGINE_ID:-$AGENT_RUNTIME_ID}",GOOGLE_GENAI_USE_VERTEXAI="${GOOGLE_GENAI_USE_VERTEXAI:-true}"

echo -e "\n${GREEN}✔ Serverless Container Deployment Completed Successfully!${NC}"

# Fetch and print the deployed Service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --platform managed --region "$REGION" --project "$PROJECT_ID" --format 'value(status.url)' 2>/dev/null || echo "Unable to fetch automatically")

echo -e "🔗 Your Live Gradio Service URL: ${BLUE}${SERVICE_URL}${NC}\n"