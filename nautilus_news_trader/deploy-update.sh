#!/bin/bash
#
# Deploy updated code to existing news-trader VM
#
# Usage:
#   ./deploy-update.sh              # Deploy code only
#   ./deploy-update.sh --start      # Deploy and start all strategies
#   ./deploy-update.sh --restart    # Deploy and restart strategies
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-gnw-trader}"
VM_NAME="${VM_NAME:-news-trader}"
ZONE="${ZONE:-us-east4-a}"
REMOTE_PATH="/opt/news-trader"

echo "=========================================="
echo "Deploying to existing VM: $VM_NAME"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Zone: $ZONE"
echo "Remote: $REMOTE_PATH"
echo ""

# Files/folders to deploy
echo "Creating archive..."
tar --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='runner' \
    --exclude='.git' \
    --exclude='*.tar.gz' \
    -czf /tmp/news_trader_deploy.tar.gz \
    shared/ strategies/ utils/ actors/ \
    run_all_strategies.sh requirements.txt

echo "Archive: $(du -h /tmp/news_trader_deploy.tar.gz | cut -f1)"

# Copy to VM
echo ""
echo "Copying to VM..."
gcloud compute scp /tmp/news_trader_deploy.tar.gz "$VM_NAME:~/" \
    --zone="$ZONE" --project="$PROJECT_ID"

# Also copy .env if exists
if [ -f .env ]; then
    echo "Copying .env..."
    gcloud compute scp .env "$VM_NAME:~/.env_new" \
        --zone="$ZONE" --project="$PROJECT_ID"
fi

# Extract and setup on VM
echo ""
echo "Deploying on VM..."
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
    set -e

    REMOTE_PATH=$REMOTE_PATH

    # Stop running strategies if script exists
    if [ -f \$REMOTE_PATH/run_all_strategies.sh ]; then
        echo 'Stopping running strategies...'
        cd \$REMOTE_PATH && ./run_all_strategies.sh stop 2>/dev/null || true
        sleep 2
    fi

    # Create directory if needed
    sudo mkdir -p \$REMOTE_PATH
    sudo chown \$(whoami) \$REMOTE_PATH

    # Extract new code
    echo 'Extracting new code...'
    tar -xzf ~/news_trader_deploy.tar.gz -C \$REMOTE_PATH
    rm ~/news_trader_deploy.tar.gz

    # Update .env if copied
    if [ -f ~/.env_new ]; then
        echo 'Updating .env...'
        mv ~/.env_new \$REMOTE_PATH/.env
    fi

    # Set permissions
    chmod +x \$REMOTE_PATH/run_all_strategies.sh
    find \$REMOTE_PATH/strategies -name 'run.py' -exec chmod +x {} \;

    # Create runner directory
    mkdir -p \$REMOTE_PATH/runner

    echo ''
    echo 'Deployment complete!'
    echo ''
    ls -la \$REMOTE_PATH/
    echo ''
    echo 'New structure:'
    find \$REMOTE_PATH/strategies -type d -maxdepth 2 | head -20
"

# Cleanup local
rm /tmp/news_trader_deploy.tar.gz

echo ""
echo "=========================================="
echo "Deployment successful!"
echo "=========================================="

# Handle --start or --restart flags
if [ "$1" == "--start" ] || [ "$1" == "--restart" ]; then
    echo ""
    echo "Starting strategies..."
    gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
        cd $REMOTE_PATH
        source .env 2>/dev/null || true
        ./run_all_strategies.sh start
        sleep 3
        ./run_all_strategies.sh status
    "
fi

echo ""
echo "Commands:"
echo "  Start:  gcloud compute ssh $VM_NAME --zone=$ZONE -- 'cd $REMOTE_PATH && ./run_all_strategies.sh start'"
echo "  Status: gcloud compute ssh $VM_NAME --zone=$ZONE -- 'cd $REMOTE_PATH && ./run_all_strategies.sh status'"
echo "  Logs:   gcloud compute ssh $VM_NAME --zone=$ZONE -- 'cd $REMOTE_PATH && ./run_all_strategies.sh logs trend'"
echo ""
