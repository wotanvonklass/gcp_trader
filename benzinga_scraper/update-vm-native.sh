#!/bin/bash

# Update scraper on VM (Native Node.js - No Docker)
# Usage: ./update-vm-native.sh

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

PROJECT_ID="${GCP_PROJECT_ID}"
VM_NAME="${VM_NAME:-benzinga-scraper}"
ZONE="${ZONE:-us-east4-a}"

echo -e "${GREEN}🔄 Updating Benzinga Scraper on VM (Native)${NC}"
echo ""

# Copy updated application files to VM
echo -e "${BLUE}📦 Copying application files...${NC}"
gcloud compute scp --recurse \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    index.js package.json package-lock.json benzinga-addon \
    $VM_NAME:/tmp/

# Update the application
echo -e "${BLUE}⚙️  Updating application...${NC}"
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --command='
        set -e

        # Stop the service
        sudo systemctl stop benzinga-scraper

        # Update files
        sudo mv /tmp/index.js /opt/benzinga-scraper/
        sudo mv /tmp/package.json /opt/benzinga-scraper/
        sudo mv /tmp/package-lock.json /opt/benzinga-scraper/
        sudo rm -rf /opt/benzinga-scraper/benzinga-addon
        sudo mv /tmp/benzinga-addon /opt/benzinga-scraper/

        # Update dependencies
        cd /opt/benzinga-scraper
        sudo npm ci --only=production

        # Restart the service
        sudo systemctl start benzinga-scraper

        echo "✅ Application updated and restarted"
    '

echo ""
echo -e "${GREEN}✅ Update complete!${NC}"
echo ""
echo -e "${BLUE}Check status:${NC}"
echo "  gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl status benzinga-scraper'"
echo ""
echo -e "${BLUE}View logs:${NC}"
echo "  gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo journalctl -u benzinga-scraper -f'"
