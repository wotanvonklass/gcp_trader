#!/bin/bash

# Simple Pub/Sub Setup - No complex IAM
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}📬 Simple Pub/Sub Setup${NC}"
echo ""

# Load .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

PROJECT_ID="${GCP_PROJECT_ID}"

if [ -z "$PROJECT_ID" ]; then
    echo "❌ Set GCP_PROJECT_ID in .env"
    exit 1
fi

echo "Project: $PROJECT_ID"
echo ""

# Enable API
echo "Enabling Pub/Sub API..."
gcloud services enable pubsub.googleapis.com --project=$PROJECT_ID

# Create topic
echo "Creating topic: benzinga-news..."
gcloud pubsub topics create benzinga-news --project=$PROJECT_ID 2>/dev/null || echo "Topic exists"

# Create subscription
echo "Creating subscription: benzinga-news-sub..."
gcloud pubsub subscriptions create benzinga-news-sub \
    --topic=benzinga-news \
    --project=$PROJECT_ID \
    2>/dev/null || echo "Subscription exists"

echo ""
echo -e "${GREEN}✅ Done!${NC}"
echo ""
echo -e "${BLUE}Topic:${NC} benzinga-news"
echo -e "${BLUE}Subscription:${NC} benzinga-news-sub"
echo ""
echo "Anyone in your project can now publish/subscribe."
echo ""
echo "Test it:"
echo "  gcloud pubsub topics publish benzinga-news --message='test'"
echo "  gcloud pubsub subscriptions pull benzinga-news-sub --limit=1 --auto-ack"
echo ""
