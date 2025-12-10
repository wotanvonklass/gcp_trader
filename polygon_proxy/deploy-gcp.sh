#!/bin/bash

# Deploy Polygon Proxy to GCP Spot VM
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}🚀 Deploying Polygon Proxy to GCP Spot VM${NC}"
echo ""

# Load environment from parent .env if exists
if [ -f ../.env ]; then
    echo -e "${GREEN}✓ Loading credentials from parent .env${NC}"
    export $(grep -v '^#' ../.env | xargs)
fi

# Configuration
PROJECT_ID="${GCP_PROJECT_ID}"
VM_NAME="${VM_NAME:-polygon-proxy}"
ZONE="${ZONE:-us-east4-a}"
MACHINE_TYPE="e2-small"  # Cheapest that can run 3 services (~$4/month spot)
POLYGON_API_KEY="${POLYGON_API_KEY}"

if [ -z "$PROJECT_ID" ]; then
    echo -e "${YELLOW}Set GCP_PROJECT_ID in environment${NC}"
    exit 1
fi

if [ -z "$POLYGON_API_KEY" ]; then
    echo -e "${YELLOW}Set POLYGON_API_KEY in environment${NC}"
    exit 1
fi

echo -e "${BLUE}Configuration:${NC}"
echo "  Project: $PROJECT_ID"
echo "  VM Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Machine Type: $MACHINE_TYPE (spot)"
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
cat > /tmp/polygon-startup.sh << 'STARTUP_EOF'
#!/bin/bash
set -e

# Wait for network
until ping -c1 google.com &>/dev/null; do
    echo "Waiting for network..."
    sleep 2
done

# Install dependencies
apt-get update
apt-get install -y git build-essential pkg-config libssl-dev python3-requests python3-websockets

# Create polygonproxy user
if ! id -u polygonproxy &>/dev/null; then
    useradd -m -s /bin/bash polygonproxy
fi

# Clone repo as root first (more reliable networking)
cd /home/polygonproxy
if [ ! -d "polygon_proxy" ]; then
    git clone REPO_URL_PLACEHOLDER polygon_proxy
    chown -R polygonproxy:polygonproxy polygon_proxy
fi

# Install Rust and build services as polygonproxy user
su - polygonproxy << 'USEREOF'
set -e

# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source $HOME/.cargo/env

# Build services
cd /home/polygonproxy/polygon_proxy

# Build all services
echo "Building firehose-proxy..."
cd firehose-proxy
cargo build --release
cd ..

echo "Building ms-aggregator..."
cd ms-aggregator
cargo build --release
cd ..

echo "Building filtered-proxy..."
cd filtered-proxy
cargo build --release
cd ..

echo "Build completed successfully!"
USEREOF

# Create systemd services
cat > /tmp/firehose-proxy.service << 'EOF'
[Unit]
Description=Polygon Firehose Proxy
After=network.target

[Service]
Type=simple
User=polygonproxy
WorkingDirectory=/home/polygonproxy/polygon_proxy/firehose-proxy
Environment="POLYGON_API_KEY=POLYGON_KEY_PLACEHOLDER"
Environment="FIREHOSE_PORT=8767"
ExecStart=/home/polygonproxy/polygon_proxy/firehose-proxy/target/release/firehose_proxy
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /tmp/ms-aggregator.service << 'EOF'
[Unit]
Description=Polygon Millisecond Aggregator
After=network.target firehose-proxy.service

[Service]
Type=simple
User=polygonproxy
WorkingDirectory=/home/polygonproxy/polygon_proxy/ms-aggregator
Environment="MS_AGGREGATOR_PORT=8768"
Environment="FIREHOSE_URL=ws://localhost:8767"
Environment="POLYGON_API_KEY=POLYGON_KEY_PLACEHOLDER"
ExecStart=/home/polygonproxy/polygon_proxy/ms-aggregator/target/release/ms_aggregator
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /tmp/filtered-proxy.service << 'EOF'
[Unit]
Description=Polygon Filtered Proxy
After=network.target ms-aggregator.service

[Service]
Type=simple
User=polygonproxy
WorkingDirectory=/home/polygonproxy/polygon_proxy/filtered-proxy
Environment="FILTERED_PROXY_PORT=8765"
Environment="FIREHOSE_WS_URL=ws://localhost:8767"
Environment="MS_AGGREGATOR_WS_URL=ws://localhost:8768"
ExecStart=/home/polygonproxy/polygon_proxy/filtered-proxy/target/release/polygon_filtered_proxy
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /tmp/polygon-monitor.service << 'EOF'
[Unit]
Description=Polygon Proxy Health Monitor
After=network.target filtered-proxy.service ms-aggregator.service

[Service]
Type=simple
User=polygonproxy
WorkingDirectory=/home/polygonproxy/polygon_proxy
ExecStart=/usr/bin/python3 /home/polygonproxy/polygon_proxy/monitor.py
Restart=always
RestartSec=30
StandardOutput=append:/var/log/polygon-monitor.log
StandardError=append:/var/log/polygon-monitor.log

[Install]
WantedBy=multi-user.target
EOF

# Install systemd services
sudo mv /tmp/firehose-proxy.service /etc/systemd/system/
sudo mv /tmp/ms-aggregator.service /etc/systemd/system/
sudo mv /tmp/filtered-proxy.service /etc/systemd/system/
sudo mv /tmp/polygon-monitor.service /etc/systemd/system/

# Create log directories
sudo mkdir -p /var/log
sudo touch /var/log/polygon-monitor.log /var/log/polygon-alerts.log
sudo chown polygonproxy:polygonproxy /var/log/polygon-monitor.log /var/log/polygon-alerts.log

# Start services
sudo systemctl daemon-reload
sudo systemctl enable firehose-proxy ms-aggregator filtered-proxy polygon-monitor
sudo systemctl start firehose-proxy
sleep 5
sudo systemctl start ms-aggregator
sleep 5
sudo systemctl start filtered-proxy
sleep 2
sudo systemctl start polygon-monitor

echo "Polygon Proxy services started!"
sudo systemctl status firehose-proxy ms-aggregator filtered-proxy polygon-monitor
STARTUP_EOF

# Replace placeholders
sed -i.bak "s|POLYGON_KEY_PLACEHOLDER|$POLYGON_API_KEY|g" /tmp/polygon-startup.sh
sed -i.bak "s|REPO_URL_PLACEHOLDER|https://github.com/wotanvonklass/polygon_proxy.git|g" /tmp/polygon-startup.sh

# Create the VM
echo -e "${GREEN}🖥️  Creating Spot VM...${NC}"
gcloud compute instances create $VM_NAME \
    --project=$PROJECT_ID \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --provisioning-model=SPOT \
    --instance-termination-action=STOP \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-standard \
    --scopes=cloud-platform \
    --tags=polygon-proxy,http-server \
    --metadata-from-file=startup-script=/tmp/polygon-startup.sh

# Get VM external IP
EXTERNAL_IP=$(gcloud compute instances describe $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Deployment Started!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}VM Details:${NC}"
echo "  Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Type: $MACHINE_TYPE (Spot)"
echo "  External IP: $EXTERNAL_IP"
echo ""
echo -e "${YELLOW}⚠️  Initial setup takes 5-10 minutes (building Rust services)${NC}"
echo ""
echo -e "${BLUE}Monitor Progress:${NC}"
echo "  SSH: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID"
echo "  Logs: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo journalctl -f'"
echo "  Build: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='tail -f /var/log/syslog | grep polygon'"
echo ""
echo -e "${BLUE}Check Services:${NC}"
echo "  gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl status firehose-proxy ms-aggregator filtered-proxy'"
echo ""
echo -e "${BLUE}Connect to Proxy:${NC}"
echo "  WebSocket: ws://$EXTERNAL_IP:8765"
echo ""
echo -e "${BLUE}Firewall (if needed):${NC}"
echo "  gcloud compute firewall-rules create allow-polygon-proxy \\"
echo "    --allow tcp:8765 \\"
echo "    --target-tags polygon-proxy \\"
echo "    --project=$PROJECT_ID"
echo ""
echo -e "${GREEN}💰 Cost: ~$4/month (spot)${NC}"
echo ""

# Clean up
rm /tmp/polygon-startup.sh /tmp/polygon-startup.sh.bak
