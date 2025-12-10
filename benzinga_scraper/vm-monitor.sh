#!/bin/bash

# Monitor Benzinga Scraper VM
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Load .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

PROJECT_ID="${GCP_PROJECT_ID}"
VM_NAME="${VM_NAME:-benzinga-scraper}"
ZONE="${ZONE:-us-east4-a}"

echo -e "${BLUE}🔍 Benzinga Scraper VM Monitor${NC}"
echo ""

# Check if VM exists
if ! gcloud compute instances describe $VM_NAME --zone=$ZONE --project=$PROJECT_ID &>/dev/null; then
    echo -e "${RED}❌ VM '$VM_NAME' not found${NC}"
    exit 1
fi

# Get VM status
STATUS=$(gcloud compute instances describe $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --format='get(status)')

echo -e "${BLUE}VM Status:${NC} $STATUS"

if [ "$STATUS" != "RUNNING" ]; then
    echo -e "${YELLOW}⚠️  VM is not running. Start it with:${NC}"
    echo "  gcloud compute instances start $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
    exit 0
fi

# Get external IP
EXTERNAL_IP=$(gcloud compute instances describe $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo -e "${BLUE}External IP:${NC} $EXTERNAL_IP"
echo ""

# Check if port 8080 is responding
echo -e "${BLUE}Testing HTTP endpoint...${NC}"
if curl -s --max-time 5 "http://$EXTERNAL_IP:8080" &>/dev/null; then
    echo -e "${GREEN}✓ Service is responding${NC}"

    # Get service status
    echo ""
    echo -e "${BLUE}Service Status:${NC}"
    curl -s "http://$EXTERNAL_IP:8080" | python3 -m json.tool 2>/dev/null || curl -s "http://$EXTERNAL_IP:8080"
else
    echo -e "${YELLOW}⚠️  Service not responding on port 8080${NC}"
fi

echo ""
echo -e "${BLUE}Recent Docker Logs:${NC}"
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --command='docker logs --tail=20 benzinga-scraper' 2>/dev/null || \
    echo -e "${YELLOW}Could not fetch logs${NC}"

echo ""
echo -e "${BLUE}Commands:${NC}"
echo "  View live logs: gcloud compute ssh $VM_NAME --zone=$ZONE --command='docker logs -f benzinga-scraper'"
echo "  SSH to VM: gcloud compute ssh $VM_NAME --zone=$ZONE"
echo "  Restart container: gcloud compute ssh $VM_NAME --zone=$ZONE --command='docker restart benzinga-scraper'"
echo "  Stop VM: gcloud compute instances stop $VM_NAME --zone=$ZONE"
