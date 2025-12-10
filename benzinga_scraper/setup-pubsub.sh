#!/bin/bash

# Setup Secure Pub/Sub for Benzinga News
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🔐 Setting up Secure Pub/Sub Infrastructure${NC}"
echo ""

# Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo -e "${GREEN}✓ Loaded .env file${NC}"
fi

PROJECT_ID="${GCP_PROJECT_ID}"
TOPIC_NAME="benzinga-news"
SUBSCRIPTION_NAME="benzinga-news-sub"
SCRAPER_SA="benzinga-scraper"
SCRAPER_SA_EMAIL="${SCRAPER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}❌ GCP_PROJECT_ID not set${NC}"
    exit 1
fi

echo -e "${BLUE}Configuration:${NC}"
echo "  Project: $PROJECT_ID"
echo "  Topic: $TOPIC_NAME"
echo "  Subscription: $SUBSCRIPTION_NAME"
echo "  Scraper SA: $SCRAPER_SA_EMAIL"
echo ""

# Enable Pub/Sub API
echo -e "${GREEN}📡 Enabling Pub/Sub API...${NC}"
gcloud services enable pubsub.googleapis.com --project=$PROJECT_ID

# Create service account for scraper
echo -e "${GREEN}👤 Creating service account for scraper...${NC}"
if gcloud iam service-accounts describe $SCRAPER_SA_EMAIL --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  Service account already exists${NC}"
else
    gcloud iam service-accounts create $SCRAPER_SA \
        --display-name="Benzinga Scraper VM" \
        --project=$PROJECT_ID
    echo -e "${GREEN}✓ Service account created${NC}"
fi

# Create Pub/Sub topic
echo -e "${GREEN}📬 Creating Pub/Sub topic...${NC}"
if gcloud pubsub topics describe $TOPIC_NAME --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  Topic already exists${NC}"
else
    gcloud pubsub topics create $TOPIC_NAME --project=$PROJECT_ID
    echo -e "${GREEN}✓ Topic created${NC}"
fi

# Create subscription
echo -e "${GREEN}📥 Creating subscription...${NC}"
if gcloud pubsub subscriptions describe $SUBSCRIPTION_NAME --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  Subscription already exists${NC}"
else
    gcloud pubsub subscriptions create $SUBSCRIPTION_NAME \
        --topic=$TOPIC_NAME \
        --ack-deadline=60 \
        --message-retention-duration=7d \
        --project=$PROJECT_ID
    echo -e "${GREEN}✓ Subscription created${NC}"
fi

# Grant publisher role to scraper service account
echo -e "${GREEN}🔑 Granting publisher permissions...${NC}"
gcloud pubsub topics add-iam-policy-binding $TOPIC_NAME \
    --member="serviceAccount:$SCRAPER_SA_EMAIL" \
    --role="roles/pubsub.publisher" \
    --project=$PROJECT_ID

echo -e "${GREEN}✓ Scraper can now publish to topic${NC}"

# Optional: Grant subscriber role (for testing)
echo ""
echo -e "${BLUE}Do you want to grant subscriber permissions to the scraper SA?${NC}"
echo "  (Useful for testing, but not required for production)"
read -p "Grant subscriber role? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    gcloud pubsub subscriptions add-iam-policy-binding $SUBSCRIPTION_NAME \
        --member="serviceAccount:$SCRAPER_SA_EMAIL" \
        --role="roles/pubsub.subscriber" \
        --project=$PROJECT_ID
    echo -e "${GREEN}✓ Scraper can also subscribe (for testing)${NC}"
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Pub/Sub Setup Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}Topic Details:${NC}"
echo "  Name: $TOPIC_NAME"
echo "  Full: projects/$PROJECT_ID/topics/$TOPIC_NAME"
echo "  Publisher: $SCRAPER_SA_EMAIL ✓"
echo ""
echo -e "${BLUE}Subscription Details:${NC}"
echo "  Name: $SUBSCRIPTION_NAME"
echo "  Full: projects/$PROJECT_ID/subscriptions/$SUBSCRIPTION_NAME"
echo "  Retention: 7 days"
echo "  Ack Deadline: 60 seconds"
echo ""
echo -e "${BLUE}Security:${NC}"
echo "  ✓ Only the scraper service account can publish"
echo "  ✓ No public access"
echo "  ✓ IAM-based authentication"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "  1. Update VM to use service account:"
echo "     gcloud compute instances set-service-account benzinga-scraper \\"
echo "       --zone=us-east4-a \\"
echo "       --service-account=$SCRAPER_SA_EMAIL \\"
echo "       --scopes=cloud-platform"
echo ""
echo "  2. Grant subscriber access to your services:"
echo "     gcloud pubsub subscriptions add-iam-policy-binding $SUBSCRIPTION_NAME \\"
echo "       --member=\"serviceAccount:YOUR_SERVICE@$PROJECT_ID.iam.gserviceaccount.com\" \\"
echo "       --role=\"roles/pubsub.subscriber\""
echo ""
echo -e "${BLUE}Testing:${NC}"
echo "  # Publish test message"
echo "  gcloud pubsub topics publish $TOPIC_NAME --message=\"test\""
echo ""
echo "  # Pull messages"
echo "  gcloud pubsub subscriptions pull $SUBSCRIPTION_NAME --limit=5 --auto-ack"
echo ""
echo -e "${BLUE}View IAM Policy:${NC}"
echo "  gcloud pubsub topics get-iam-policy $TOPIC_NAME"
echo "  gcloud pubsub subscriptions get-iam-policy $SUBSCRIPTION_NAME"
echo ""
