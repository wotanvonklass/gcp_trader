#!/bin/bash

# Grant Pub/Sub Subscriber Access to Your Services
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔑 Grant Pub/Sub Subscriber Access${NC}"
echo ""

# Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

PROJECT_ID="${GCP_PROJECT_ID}"
SUBSCRIPTION_NAME="benzinga-news-sub"

if [ -z "$PROJECT_ID" ]; then
    echo "❌ GCP_PROJECT_ID not set"
    exit 1
fi

echo -e "${BLUE}This script will grant subscriber access to your services.${NC}"
echo ""
echo "You can grant access to:"
echo "  1. Service Account (e.g., trading-bot@project.iam.gserviceaccount.com)"
echo "  2. User Account (e.g., user@example.com)"
echo "  3. Google Group (e.g., group@example.com)"
echo ""

read -p "Enter the member to grant access (e.g., serviceAccount:trading-bot@${PROJECT_ID}.iam.gserviceaccount.com): " MEMBER

if [ -z "$MEMBER" ]; then
    echo "❌ No member specified"
    exit 1
fi

echo ""
echo -e "${BLUE}Granting subscriber access...${NC}"
echo "  Subscription: $SUBSCRIPTION_NAME"
echo "  Member: $MEMBER"
echo "  Role: roles/pubsub.subscriber"
echo ""

gcloud pubsub subscriptions add-iam-policy-binding $SUBSCRIPTION_NAME \
    --member="$MEMBER" \
    --role="roles/pubsub.subscriber" \
    --project=$PROJECT_ID

echo ""
echo -e "${GREEN}✅ Access granted!${NC}"
echo ""
echo -e "${BLUE}Current IAM Policy:${NC}"
gcloud pubsub subscriptions get-iam-policy $SUBSCRIPTION_NAME --project=$PROJECT_ID
echo ""
echo -e "${GREEN}The specified member can now subscribe to benzinga-news${NC}"
