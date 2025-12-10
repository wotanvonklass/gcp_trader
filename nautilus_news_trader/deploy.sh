#!/bin/bash

# Deploy Nautilus News Trader to GCP Compute Engine
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}🚀 Deploying Nautilus News Trader to GCP${NC}"
echo ""

# Load .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo -e "${GREEN}✓ Loaded .env file${NC}"
fi

# Configuration
PROJECT_ID="${GCP_PROJECT_ID}"
VM_NAME="${VM_NAME:-news-trader}"
ZONE="${ZONE:-us-east4-a}"
MACHINE_TYPE="e2-medium"

echo -e "${BLUE}Configuration:${NC}"
echo "  Project: $PROJECT_ID"
echo "  VM Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Machine Type: $MACHINE_TYPE"
echo ""

# Check if VM exists
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

# Create startup script
cat > /tmp/startup-script.sh << 'STARTUP_EOF'
#!/bin/bash
set -e

# Log output
exec > >(tee -a /var/log/trader-startup.log)
exec 2>&1

echo "================================"
echo "Nautilus News Trader VM Setup"
echo "================================"

# Update system
apt-get update
apt-get install -y python3 python3-pip python3-venv git build-essential

# Create app directory
mkdir -p /opt/news-trader

echo "✅ Base system setup complete"
STARTUP_EOF

# Create the VM
echo -e "${GREEN}🖥️  Creating VM...${NC}"
gcloud compute instances create $VM_NAME \
    --project=$PROJECT_ID \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-standard \
    --scopes=cloud-platform \
    --metadata-from-file=startup-script=/tmp/startup-script.sh

# Wait for VM to start and startup script to complete
echo -e "${BLUE}⏳ Waiting for VM to initialize and startup script to complete (90 seconds)...${NC}"
sleep 90

# Copy application files
echo -e "${GREEN}📦 Copying application files...${NC}"
gcloud compute scp --recurse \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    actors/ strategies/ run_news_trader.py requirements.txt \
    $VM_NAME:/tmp/

# Create .env file on VM
echo -e "${GREEN}📝 Creating environment configuration...${NC}"
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --command="cat > /tmp/.env << 'ENV_EOF'
GCP_PROJECT_ID=$GCP_PROJECT_ID
PUBSUB_SUBSCRIPTION=$PUBSUB_SUBSCRIPTION
ALPACA_API_KEY=$ALPACA_API_KEY
ALPACA_SECRET_KEY=$ALPACA_SECRET_KEY
ALPACA_BASE_URL=$ALPACA_BASE_URL
POLYGON_API_KEY=$POLYGON_API_KEY
MIN_NEWS_AGE_SECONDS=$MIN_NEWS_AGE_SECONDS
MAX_NEWS_AGE_SECONDS=$MAX_NEWS_AGE_SECONDS
VOLUME_PERCENTAGE=$VOLUME_PERCENTAGE
MIN_POSITION_SIZE=$MIN_POSITION_SIZE
MAX_POSITION_SIZE=$MAX_POSITION_SIZE
LIMIT_ORDER_OFFSET_PCT=$LIMIT_ORDER_OFFSET_PCT
EXIT_DELAY_MINUTES=$EXIT_DELAY_MINUTES
EXTENDED_HOURS=$EXTENDED_HOURS
ENV_EOF
"

# Install and configure
echo -e "${GREEN}⚙️  Installing application...${NC}"
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --command='
        set -e

        # Ensure python3-venv is installed (in case startup script hasnt completed)
        sudo apt-get update >/dev/null 2>&1 || true
        sudo apt-get install -y python3-venv build-essential >/dev/null 2>&1 || true

        # Create app directory
        sudo mkdir -p /opt/news-trader

        # Move files
        sudo mv /tmp/actors /opt/news-trader/
        sudo mv /tmp/strategies /opt/news-trader/
        sudo mv /tmp/run_news_trader.py /opt/news-trader/
        sudo mv /tmp/requirements.txt /opt/news-trader/
        sudo mv /tmp/.env /opt/news-trader/

        # Create virtual environment and install dependencies
        cd /opt/news-trader
        sudo python3 -m venv venv
        sudo ./venv/bin/pip install --upgrade pip

        # Install Nautilus and dependencies
        echo "📦 Installing Nautilus Trader and dependencies..."
        sudo ./venv/bin/pip install -r requirements.txt

        # Make runner script executable
        sudo chmod +x run_news_trader.py

        # Create systemd service
        sudo tee /etc/systemd/system/news-trader.service > /dev/null << "SERVICE_EOF"
[Unit]
Description=Nautilus News Trading Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/news-trader
EnvironmentFile=/opt/news-trader/.env
ExecStart=/opt/news-trader/venv/bin/python3 /opt/news-trader/run_news_trader.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/news-trader.log
StandardError=append:/var/log/news-trader-error.log

[Install]
WantedBy=multi-user.target
SERVICE_EOF

        # Start service
        sudo systemctl daemon-reload
        sudo systemctl enable news-trader
        sudo systemctl start news-trader

        echo "✅ Nautilus News Trader installed and started!"
    '

# Wait for service to start
sleep 5

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
    --command='sudo systemctl status news-trader --no-pager'

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Deployment Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}VM Details:${NC}"
echo "  Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Type: $MACHINE_TYPE"
echo "  External IP: $EXTERNAL_IP"
echo ""
echo -e "${BLUE}Service Management:${NC}"
echo "  Status: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl status news-trader'"
echo "  Logs: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo journalctl -u news-trader -f'"
echo "  Restart: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl restart news-trader'"
echo ""
echo -e "${BLUE}Monitoring:${NC}"
echo "  Tail logs: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo tail -f /var/log/news-trader-error.log'"
echo ""
echo -e "${GREEN}📰 Now listening for news on Pub/Sub topic: benzinga-news${NC}"
echo -e "${YELLOW}⚠️  Using standard Nautilus installation - copy patched version to /opt/nautilus_trader if needed${NC}"
echo ""

# Clean up
rm /tmp/startup-script.sh
