#!/bin/bash

# Deploy Benzinga WebSocket Client to Compute Engine VM
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}🚀 Deploying Benzinga WebSocket Client to GCP VM${NC}"
echo ""

# Load .env file from parent directory
if [ -f ../.env ]; then
    export $(grep -v '^#' ../.env | xargs)
    echo -e "${GREEN}✓ Loaded ../.env file${NC}"
fi

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-gnw-trader}"
VM_NAME="benzinga-ws"
ZONE="${ZONE:-us-east4-a}"
MACHINE_TYPE="e2-micro"

echo -e "${BLUE}Configuration:${NC}"
echo "  Project: $PROJECT_ID"
echo "  VM Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Machine Type: $MACHINE_TYPE"
echo ""

# Check required env vars
if [ -z "$BENZINGA_API_KEY" ]; then
    echo -e "${YELLOW}ERROR: BENZINGA_API_KEY not set in ../.env${NC}"
    exit 1
fi

# Check if VM already exists
if gcloud compute instances describe $VM_NAME --zone=$ZONE --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  VM '$VM_NAME' already exists - updating...${NC}"

    # Just update files and restart service
    echo -e "${GREEN}📦 Copying application files...${NC}"
    gcloud compute scp --zone=$ZONE --project=$PROJECT_ID \
        main.py requirements.txt \
        $VM_NAME:/tmp/

    # Create .env and restart
    gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command="
        sudo mv /tmp/main.py /opt/benzinga-ws/
        sudo mv /tmp/requirements.txt /opt/benzinga-ws/
        cd /opt/benzinga-ws && sudo pip3 install -r requirements.txt
        echo 'BENZINGA_API_KEY=$BENZINGA_API_KEY' | sudo tee /opt/benzinga-ws/.env
        echo 'GCP_PROJECT_ID=$PROJECT_ID' | sudo tee -a /opt/benzinga-ws/.env
        sudo systemctl restart benzinga-ws
        sleep 2
        sudo systemctl status benzinga-ws --no-pager
    "

    echo -e "${GREEN}✅ Updated and restarted!${NC}"
    exit 0
fi

# Create startup script
cat > /tmp/startup-script.sh << 'STARTUP_EOF'
#!/bin/bash
set -e
exec > >(tee -a /var/log/benzinga-ws-startup.log) 2>&1

echo "================================"
echo "Benzinga WebSocket VM Setup"
echo "================================"

apt-get update
apt-get install -y python3 python3-pip python3-venv

mkdir -p /opt/benzinga-ws

echo "✅ Base system setup complete"
STARTUP_EOF

# Create the VM
echo -e "${GREEN}🖥️  Creating VM...${NC}"
gcloud compute instances create $VM_NAME \
    --project=$PROJECT_ID \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --provisioning-model=STANDARD \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=10GB \
    --boot-disk-type=pd-standard \
    --scopes=cloud-platform \
    --metadata-from-file=startup-script=/tmp/startup-script.sh

echo -e "${BLUE}⏳ Waiting for VM to initialize (60 seconds)...${NC}"
sleep 60

# Copy application files
echo -e "${GREEN}📦 Copying application files...${NC}"
gcloud compute scp --zone=$ZONE --project=$PROJECT_ID \
    main.py requirements.txt \
    $VM_NAME:/tmp/

# Install and configure
echo -e "${GREEN}⚙️  Installing application...${NC}"
gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command="
    set -e

    sudo mv /tmp/main.py /opt/benzinga-ws/
    sudo mv /tmp/requirements.txt /opt/benzinga-ws/

    cd /opt/benzinga-ws
    sudo pip3 install -r requirements.txt --break-system-packages

    # Create .env
    echo 'BENZINGA_API_KEY=$BENZINGA_API_KEY' | sudo tee /opt/benzinga-ws/.env
    echo 'GCP_PROJECT_ID=$PROJECT_ID' | sudo tee -a /opt/benzinga-ws/.env

    # Create systemd service
    sudo tee /etc/systemd/system/benzinga-ws.service > /dev/null << 'SERVICE_EOF'
[Unit]
Description=Benzinga WebSocket News Client
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/benzinga-ws
EnvironmentFile=/opt/benzinga-ws/.env
ExecStart=/usr/bin/python3 -u main.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/benzinga-ws.log
StandardError=append:/var/log/benzinga-ws.log

[Install]
WantedBy=multi-user.target
SERVICE_EOF

    sudo systemctl daemon-reload
    sudo systemctl enable benzinga-ws
    sudo systemctl start benzinga-ws

    echo '✅ Benzinga WebSocket client installed and started!'
"

sleep 5

# Check status
echo -e "${BLUE}📊 Checking service status...${NC}"
gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID \
    --command='sudo systemctl status benzinga-ws --no-pager'

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Deployment Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}Commands:${NC}"
echo "  SSH: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo "  Logs: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo tail -f /var/log/benzinga-ws.log'"
echo "  Status: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl status benzinga-ws'"
echo "  Restart: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl restart benzinga-ws'"
echo ""
echo -e "${BLUE}GCP Logs:${NC}"
echo "  gcloud logging read 'logName=\"projects/$PROJECT_ID/logs/benzinga-news-ws\"' --project=$PROJECT_ID --limit=20"
echo ""
echo -e "${GREEN}💰 Cost: ~\$4/month (e2-micro)${NC}"
echo ""

rm -f /tmp/startup-script.sh
