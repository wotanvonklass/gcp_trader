#!/bin/bash

# Deploy Benzinga Scraper to Compute Engine VM
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}🚀 Deploying Benzinga Scraper to Compute Engine VM${NC}"
echo ""

# Load .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo -e "${GREEN}✓ Loaded .env file${NC}"
fi

# Configuration
PROJECT_ID="${GCP_PROJECT_ID}"
VM_NAME="${VM_NAME:-benzinga-scraper}"
ZONE="${ZONE:-us-east4-a}"
MACHINE_TYPE="e2-small"
IMAGE_NAME="gcr.io/${PROJECT_ID}/benzinga-scraper"

echo -e "${BLUE}Configuration:${NC}"
echo "  Project: $PROJECT_ID"
echo "  VM Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Machine Type: $MACHINE_TYPE (standard)"
echo "  Image: $IMAGE_NAME"
echo ""

# Check if VM already exists
if gcloud compute instances describe $VM_NAME --zone=$ZONE --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  VM '$VM_NAME' already exists!${NC}"
    read -p "Delete and recreate? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Deleting existing VM...${NC}"
        gcloud compute instances delete $VM_NAME --zone=$ZONE --project=$PROJECT_ID --quiet
    else
        echo "Cancelled."
        exit 0
    fi
fi

# Build and push Docker image first
echo -e "${GREEN}📦 Building Docker image...${NC}"
gcloud builds submit --tag $IMAGE_NAME --project=$PROJECT_ID

# Create startup script
cat > /tmp/startup-script.sh << 'STARTUP_EOF'
#!/bin/bash

# Wait for Docker to be ready
until docker info &>/dev/null; do
    echo "Waiting for Docker..."
    sleep 2
done

# Configure Docker to use GCR
gcloud auth configure-docker --quiet

# Pull the latest image
docker pull IMAGE_NAME_PLACEHOLDER

# Stop and remove existing container
docker stop benzinga-scraper 2>/dev/null || true
docker rm benzinga-scraper 2>/dev/null || true

# Run the container with auto-restart
docker run -d \
    --name benzinga-scraper \
    --restart=always \
    -p 8080:8080 \
    -e BENZINGA_EMAIL="BENZINGA_EMAIL_PLACEHOLDER" \
    -e BENZINGA_PASSWORD="BENZINGA_PASSWORD_PLACEHOLDER" \
    -e RUN_MODE="continuous" \
    -e SCRAPE_INTERVAL="60000" \
    IMAGE_NAME_PLACEHOLDER

echo "Benzinga scraper started successfully"
docker logs -f benzinga-scraper
STARTUP_EOF

# Replace placeholders in startup script
sed -i '' "s|IMAGE_NAME_PLACEHOLDER|$IMAGE_NAME|g" /tmp/startup-script.sh
sed -i '' "s|BENZINGA_EMAIL_PLACEHOLDER|$BENZINGA_EMAIL|g" /tmp/startup-script.sh
sed -i '' "s|BENZINGA_PASSWORD_PLACEHOLDER|$BENZINGA_PASSWORD|g" /tmp/startup-script.sh

# Create the VM
echo -e "${GREEN}🖥️  Creating Standard VM...${NC}"
gcloud compute instances create $VM_NAME \
    --project=$PROJECT_ID \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --provisioning-model=STANDARD \
    --image-family=cos-stable \
    --image-project=cos-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-standard \
    --scopes=cloud-platform \
    --tags=http-server,https-server \
    --metadata-from-file=startup-script=/tmp/startup-script.sh

# Wait for VM to start
echo -e "${BLUE}⏳ Waiting for VM to start (30 seconds)...${NC}"
sleep 30

# Get VM external IP
EXTERNAL_IP=$(gcloud compute instances describe $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Deployment Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}VM Details:${NC}"
echo "  Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Type: $MACHINE_TYPE (Standard)"
echo "  External IP: $EXTERNAL_IP"
echo ""
echo -e "${BLUE}Access:${NC}"
echo "  SSH: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo "  Logs: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='docker logs -f benzinga-scraper'"
echo ""
echo -e "${BLUE}Monitoring:${NC}"
echo "  Status: curl http://$EXTERNAL_IP:8080"
echo "  News: curl http://$EXTERNAL_IP:8080/news"
echo ""
echo -e "${BLUE}Management:${NC}"
echo "  Stop VM: gcloud compute instances stop $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo "  Start VM: gcloud compute instances start $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo "  Delete VM: gcloud compute instances delete $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo ""
echo -e "${GREEN}💰 Cost: ~$14/month (standard VM)${NC}"
echo ""

# Clean up
rm /tmp/startup-script.sh
