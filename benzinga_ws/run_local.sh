#!/bin/bash
# Run benzinga_ws locally
set -e

# Load environment from parent .env
if [ -f ../.env ]; then
    export $(grep -E '^(BENZINGA_API_KEY|GCP_PROJECT_ID)=' ../.env | xargs)
fi

# Check required env vars
if [ -z "$BENZINGA_API_KEY" ]; then
    echo "ERROR: BENZINGA_API_KEY not set"
    exit 1
fi

echo "Starting Benzinga WebSocket client..."
echo "GCP Project: ${GCP_PROJECT_ID:-gnw-trader}"

python main.py
