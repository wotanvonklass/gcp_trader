#!/bin/bash

# Update container on VM with new image
# Usage: ./update-vm-container.sh

set -e

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "🔄 Updating container on VM..."

# SSH into VM and update container
gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${GCP_PROJECT_ID} --command="
  sudo docker pull gcr.io/${GCP_PROJECT_ID}/benzinga-scraper:latest && \
  sudo docker stop benzinga-scraper && \
  sudo docker rm benzinga-scraper && \
  sudo docker run -d --name benzinga-scraper --restart=always \
    -p 8080:8080 \
    -e BENZINGA_EMAIL='${BENZINGA_EMAIL}' \
    -e BENZINGA_PASSWORD='${BENZINGA_PASSWORD}' \
    -e RUN_MODE='continuous' \
    -e SCRAPE_INTERVAL='60000' \
    -e ENABLE_PUBSUB='false' \
    gcr.io/${GCP_PROJECT_ID}/benzinga-scraper:latest && \
  echo '✓ Container updated successfully'
"

echo "✓ Container update complete!"
echo ""
echo "Check logs: gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${GCP_PROJECT_ID} --command='sudo docker logs -f benzinga-scraper'"
