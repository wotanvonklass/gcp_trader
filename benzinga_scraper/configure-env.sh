#!/bin/bash

# Interactive .env configuration script
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}🔧 Benzinga Scraper - Environment Configuration${NC}"
echo ""

# Check if .env already exists
if [ -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file already exists!${NC}"
    read -p "Do you want to overwrite it? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Configuration cancelled. Edit .env manually."
        exit 0
    fi
fi

# Create .env file
cat > .env << 'EOF'
# GCP Configuration
GCP_PROJECT_ID=
SERVICE_NAME=benzinga-scraper
REGION=us-central1

# Benzinga Credentials
BENZINGA_EMAIL=
BENZINGA_PASSWORD=

# Scraping Configuration
RUN_MODE=continuous
SCRAPE_INTERVAL=60000

# Optional: Webhook for sending news data
WEBHOOK_URL=

# Optional: Cloud Storage bucket for data export
GCS_BUCKET=

# Optional: Pub/Sub topic for news events
PUBSUB_TOPIC=
EOF

echo -e "${GREEN}Created .env file. Now let's configure it...${NC}"
echo ""

# === GCP Project ID ===
echo -e "${BLUE}1. GCP Project Configuration${NC}"
echo ""

# Try to get current project
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")

if [ -n "$CURRENT_PROJECT" ]; then
    echo -e "${GREEN}Current GCP project: ${CURRENT_PROJECT}${NC}"
    read -p "Use this project? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        GCP_PROJECT_ID=$CURRENT_PROJECT
    else
        echo "Enter your GCP Project ID:"
        read GCP_PROJECT_ID
    fi
else
    echo "Enter your GCP Project ID (or leave empty to create a new one):"
    read GCP_PROJECT_ID

    if [ -z "$GCP_PROJECT_ID" ]; then
        GCP_PROJECT_ID="benzinga-scraper-$(date +%s)"
        echo -e "${GREEN}Creating new project: ${GCP_PROJECT_ID}${NC}"
        gcloud projects create $GCP_PROJECT_ID 2>/dev/null || true
    fi
fi

# Update .env
sed -i '' "s|GCP_PROJECT_ID=.*|GCP_PROJECT_ID=$GCP_PROJECT_ID|" .env

echo ""
echo -e "${GREEN}✓ GCP Project ID: ${GCP_PROJECT_ID}${NC}"
echo ""

# === Benzinga Credentials ===
echo -e "${BLUE}2. Benzinga Pro Credentials${NC}"
echo ""
echo "Enter your Benzinga Pro email:"
read BENZINGA_EMAIL

echo "Enter your Benzinga Pro password:"
read -s BENZINGA_PASSWORD
echo ""

# Update .env
sed -i '' "s|BENZINGA_EMAIL=.*|BENZINGA_EMAIL=$BENZINGA_EMAIL|" .env
sed -i '' "s|BENZINGA_PASSWORD=.*|BENZINGA_PASSWORD=$BENZINGA_PASSWORD|" .env

echo -e "${GREEN}✓ Benzinga credentials saved${NC}"
echo ""

# === Optional: Webhook URL ===
echo -e "${BLUE}3. Optional: Webhook URL${NC}"
echo "Enter webhook URL (or press Enter to skip):"
read WEBHOOK_URL

if [ -n "$WEBHOOK_URL" ]; then
    sed -i '' "s|WEBHOOK_URL=.*|WEBHOOK_URL=$WEBHOOK_URL|" .env
    echo -e "${GREEN}✓ Webhook URL saved${NC}"
else
    echo -e "${YELLOW}⊘ Skipped webhook configuration${NC}"
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Configuration complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Your .env file has been created with:"
echo ""
cat .env
echo ""
echo -e "${GREEN}Next steps:${NC}"
echo "1. Run: ${BLUE}./setup-secrets.sh${NC} (to store credentials in GCP)"
echo "2. Run: ${BLUE}./deploy.sh${NC} (to deploy to Cloud Run)"
echo ""
