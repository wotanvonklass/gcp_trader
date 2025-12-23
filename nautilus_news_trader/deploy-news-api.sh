#!/bin/bash
# Deploy News API to GCP news-trader VM
set -e

VM_NAME="news-trader"
ZONE="us-east4-a"
PROJECT="gnw-trader"

echo "=== Deploying News API to $VM_NAME ==="

# Check if NEWS_API_KEY is set
if [ -z "$NEWS_API_KEY" ]; then
    echo "ERROR: NEWS_API_KEY environment variable not set"
    echo "Usage: NEWS_API_KEY=your-secret-key ./deploy-news-api.sh"
    exit 1
fi

# Copy files to VM
echo "Copying files..."
gcloud compute scp news_api.py ${VM_NAME}:/opt/news-trader/ --zone=$ZONE --project=$PROJECT
gcloud compute scp shared/trade_db.py ${VM_NAME}:/opt/news-trader/shared/ --zone=$ZONE --project=$PROJECT
gcloud compute scp news-api.service ${VM_NAME}:/tmp/ --zone=$ZONE --project=$PROJECT

# Install and configure on VM
echo "Installing service..."
gcloud compute ssh ${VM_NAME} --zone=$ZONE --project=$PROJECT --command="
    set -e

    # Install dependencies
    source /opt/news-trader/.venv/bin/activate
    pip install -q fastapi uvicorn

    # Add NEWS_API_KEY to .env if not present
    if ! grep -q 'NEWS_API_KEY' /opt/news-trader/.env 2>/dev/null; then
        echo 'NEWS_API_KEY=${NEWS_API_KEY}' >> /opt/news-trader/.env
    else
        sed -i 's/^NEWS_API_KEY=.*/NEWS_API_KEY=${NEWS_API_KEY}/' /opt/news-trader/.env
    fi

    # Install systemd service
    sudo mv /tmp/news-api.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable news-api
    sudo systemctl restart news-api

    echo 'Service status:'
    sudo systemctl status news-api --no-pager -l
"

# Open firewall port 8100
echo "Configuring firewall..."
gcloud compute firewall-rules describe allow-news-api --project=$PROJECT >/dev/null 2>&1 || \
    gcloud compute firewall-rules create allow-news-api \
        --project=$PROJECT \
        --direction=INGRESS \
        --priority=1000 \
        --network=default \
        --action=ALLOW \
        --rules=tcp:8100 \
        --source-ranges=0.0.0.0/0 \
        --target-tags=news-trader \
        --description="Allow News API access on port 8100"

# Get external IP
EXTERNAL_IP=$(gcloud compute instances describe ${VM_NAME} --zone=$ZONE --project=$PROJECT --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo ""
echo "=== Deployment Complete ==="
echo "API URL: http://${EXTERNAL_IP}:8100"
echo ""
echo "Test with:"
echo "  curl http://${EXTERNAL_IP}:8100/health"
echo "  curl -H 'X-API-Key: YOUR_KEY' http://${EXTERNAL_IP}:8100/news?limit=10"
