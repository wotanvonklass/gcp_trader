#!/bin/bash

# Deploy Benzinga Scraper to Compute Engine VM (Native Node.js - No Docker)
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🚀 Deploying Benzinga Scraper to Compute Engine VM (Native)${NC}"
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

echo -e "${BLUE}Configuration:${NC}"
echo "  Project: $PROJECT_ID"
echo "  VM Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Machine Type: $MACHINE_TYPE (standard)"
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

# Create startup script for initial setup
cat > /tmp/startup-script.sh << 'STARTUP_EOF'
#!/bin/bash
set -e

# Log all output
exec > >(tee -a /var/log/scraper-startup.log)
exec 2>&1

echo "================================"
echo "Benzinga Scraper VM Setup"
echo "================================"

# Update system
apt-get update
apt-get install -y curl git wget gnupg2 ca-certificates

# Install Node.js 20.x
echo "Installing Node.js..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# Install Chrome for Puppeteer
echo "Installing Chrome..."
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
apt-get update
apt-get install -y google-chrome-stable

# Install Chrome dependencies for Puppeteer
apt-get install -y \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils

# Create app directory
mkdir -p /opt/benzinga-scraper

echo "✅ Base system setup complete"
echo "Waiting for application files to be copied..."
STARTUP_EOF

# Create the VM
echo -e "${GREEN}🖥️  Creating Standard VM...${NC}"
gcloud compute instances create $VM_NAME \
    --project=$PROJECT_ID \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --provisioning-model=STANDARD \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-standard \
    --scopes=cloud-platform \
    --tags=http-server,https-server \
    --metadata-from-file=startup-script=/tmp/startup-script.sh

# Wait for VM to start and run startup script
echo -e "${BLUE}⏳ Waiting for VM to initialize (90 seconds)...${NC}"
sleep 90

# Copy application files to VM
echo -e "${GREEN}📦 Copying application files to VM...${NC}"
gcloud compute scp --recurse \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    index.js package.json package-lock.json benzinga-addon \
    $VM_NAME:/tmp/

# Create .env file on VM
echo -e "${GREEN}📝 Creating environment configuration...${NC}"
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --command="cat > /tmp/.env << 'ENV_EOF'
BENZINGA_EMAIL=$BENZINGA_EMAIL
BENZINGA_PASSWORD=$BENZINGA_PASSWORD
RUN_MODE=continuous
SCRAPE_INTERVAL=60000
PORT=8080
PUBSUB_TOPIC=benzinga-news
ENABLE_PUBSUB=true
ENV_EOF
"

# Install and configure the application
echo -e "${GREEN}⚙️  Installing application...${NC}"
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --command='
        set -e

        # Move files to app directory
        sudo mv /tmp/index.js /opt/benzinga-scraper/
        sudo mv /tmp/package.json /opt/benzinga-scraper/
        sudo mv /tmp/package-lock.json /opt/benzinga-scraper/
        sudo mv /tmp/benzinga-addon /opt/benzinga-scraper/
        sudo mv /tmp/.env /opt/benzinga-scraper/

        # Install dependencies
        cd /opt/benzinga-scraper
        sudo npm ci --only=production

        # Create systemd service
        sudo tee /etc/systemd/system/benzinga-scraper.service > /dev/null << "SERVICE_EOF"
[Unit]
Description=Benzinga Scraper Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/benzinga-scraper
EnvironmentFile=/opt/benzinga-scraper/.env
ExecStart=/usr/bin/node index.js
Restart=always
RestartSec=10
StandardOutput=append:/var/log/benzinga-scraper.log
StandardError=append:/var/log/benzinga-scraper-error.log

[Install]
WantedBy=multi-user.target
SERVICE_EOF

        # Start the service
        sudo systemctl daemon-reload
        sudo systemctl enable benzinga-scraper
        sudo systemctl start benzinga-scraper

        echo "✅ Benzinga Scraper installed and started!"
    '

# Wait a bit for service to start
echo -e "${BLUE}⏳ Waiting for service to start (10 seconds)...${NC}"
sleep 10

# Get VM external IP
EXTERNAL_IP=$(gcloud compute instances describe $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

# Check service status
echo -e "${BLUE}📊 Checking service status...${NC}"
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --command='sudo systemctl status benzinga-scraper --no-pager'

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
echo "  OS: Debian 12 (no Docker)"
echo ""
echo -e "${BLUE}Access:${NC}"
echo "  SSH: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo "  Logs: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo journalctl -u benzinga-scraper -f'"
echo ""
echo -e "${BLUE}Service Management:${NC}"
echo "  Status: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl status benzinga-scraper'"
echo "  Restart: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl restart benzinga-scraper'"
echo "  Stop: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl stop benzinga-scraper'"
echo ""
echo -e "${BLUE}Monitoring:${NC}"
echo "  Status: curl http://$EXTERNAL_IP:8080"
echo "  News: curl http://$EXTERNAL_IP:8080/news"
echo "  Manual Scrape: curl http://$EXTERNAL_IP:8080/scrape"
echo ""
echo -e "${BLUE}VM Management:${NC}"
echo "  Stop VM: gcloud compute instances stop $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo "  Start VM: gcloud compute instances start $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo "  Delete VM: gcloud compute instances delete $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo ""
echo -e "${GREEN}💰 Cost: ~$14/month (standard VM)${NC}"
echo -e "${GREEN}🐳 No Docker required - Native Node.js deployment!${NC}"
echo ""

# Clean up
rm /tmp/startup-script.sh

echo -e "${YELLOW}Note: Give it a minute for the scraper to fully initialize...${NC}"
