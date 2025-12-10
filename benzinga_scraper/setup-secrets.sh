#!/bin/bash

# Setup GCP Secrets for Benzinga Scraper
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔐 Setting up GCP Secrets for Benzinga Scraper${NC}"
echo ""

# Load .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo -e "${GREEN}✓ Loaded .env file${NC}"
else
    echo -e "${YELLOW}⚠️  No .env file found. Using environment variables.${NC}"
fi

# Check if project is set
if [ -z "$GCP_PROJECT_ID" ]; then
    echo -e "${YELLOW}Enter your GCP Project ID:${NC}"
    read GCP_PROJECT_ID
fi

gcloud config set project $GCP_PROJECT_ID

# Enable Secret Manager API
echo -e "${GREEN}Enabling Secret Manager API...${NC}"
gcloud services enable secretmanager.googleapis.com

# Create Benzinga email secret
echo -e "${GREEN}Creating benzinga-email secret...${NC}"
if [ -z "$BENZINGA_EMAIL" ]; then
    echo -e "${YELLOW}Enter your Benzinga Pro email:${NC}"
    read BENZINGA_EMAIL
fi

echo -n "$BENZINGA_EMAIL" | gcloud secrets create benzinga-email \
    --data-file=- \
    --replication-policy="automatic" 2>/dev/null || \
    echo -n "$BENZINGA_EMAIL" | gcloud secrets versions add benzinga-email --data-file=-

# Create Benzinga password secret
echo -e "${GREEN}Creating benzinga-password secret...${NC}"
if [ -z "$BENZINGA_PASSWORD" ]; then
    echo -e "${YELLOW}Enter your Benzinga Pro password:${NC}"
    read -s BENZINGA_PASSWORD
    echo ""
fi

echo -n "$BENZINGA_PASSWORD" | gcloud secrets create benzinga-password \
    --data-file=- \
    --replication-policy="automatic" 2>/dev/null || \
    echo -n "$BENZINGA_PASSWORD" | gcloud secrets versions add benzinga-password --data-file=-

echo ""
echo -e "${GREEN}✅ Secrets created successfully!${NC}"
echo ""
echo -e "${GREEN}Verify secrets:${NC}"
gcloud secrets list

echo ""
echo -e "${GREEN}Next steps:${NC}"
echo "1. Copy benzinga-addon: cp -r ../benzinga-addon ./"
echo "2. Deploy to Cloud Run: ./deploy.sh"
