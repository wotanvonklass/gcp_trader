#!/bin/bash

# Convert benzinga-scraper from Spot/Preemptible to Standard VM
set -e

PROJECT_ID="gnw-trader"
VM_NAME="benzinga-scraper"
ZONE="us-east4-a"
MACHINE_TYPE="e2-medium"
NEW_VM_NAME="benzinga-scraper"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}⚠️  WARNING: This will recreate the VM as non-preemptible${NC}"
echo ""
echo "Current VM: $VM_NAME (preemptible)"
echo "New VM: $NEW_VM_NAME (standard)"
echo ""
read -p "Continue? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo -e "${GREEN}Step 1: Creating disk snapshot${NC}"
gcloud compute disks snapshot $VM_NAME \
    --snapshot-names="${VM_NAME}-pre-standard-$(date +%Y%m%d-%H%M%S)" \
    --zone=$ZONE \
    --project=$PROJECT_ID

echo ""
echo -e "${GREEN}Step 2: Getting current VM metadata${NC}"
NETWORK=$(gcloud compute instances describe $VM_NAME --zone=$ZONE --project=$PROJECT_ID --format="value(networkInterfaces[0].network.basename())")
SUBNET=$(gcloud compute instances describe $VM_NAME --zone=$ZONE --project=$PROJECT_ID --format="value(networkInterfaces[0].subnetwork.basename())")
TAGS=$(gcloud compute instances describe $VM_NAME --zone=$ZONE --project=$PROJECT_ID --format="value(tags.items)" | tr ';' ',')

echo "Network: $NETWORK"
echo "Subnet: $SUBNET"
echo "Tags: $TAGS"

echo ""
echo -e "${GREEN}Step 3: Stopping VM${NC}"
gcloud compute instances stop $VM_NAME --zone=$ZONE --project=$PROJECT_ID

echo ""
echo -e "${GREEN}Step 4: Creating image from disk${NC}"
IMAGE_NAME="${VM_NAME}-image-$(date +%Y%m%d-%H%M%S)"
gcloud compute images create $IMAGE_NAME \
    --source-disk=$VM_NAME \
    --source-disk-zone=$ZONE \
    --project=$PROJECT_ID

echo ""
echo -e "${GREEN}Step 5: Deleting old preemptible VM${NC}"
gcloud compute instances delete $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT_ID \
    --quiet

echo ""
echo -e "${GREEN}Step 6: Creating new standard (non-preemptible) VM${NC}"
gcloud compute instances create $NEW_VM_NAME \
    --project=$PROJECT_ID \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --network-interface=network-tier=PREMIUM,subnet=$SUBNET \
    --maintenance-policy=MIGRATE \
    --provisioning-model=STANDARD \
    --service-account=default \
    --scopes=https://www.googleapis.com/auth/cloud-platform \
    --tags=$TAGS \
    --create-disk=auto-delete=yes,boot=yes,device-name=$NEW_VM_NAME,image=$IMAGE_NAME,mode=rw,size=10,type=pd-balanced \
    --no-shielded-secure-boot \
    --shielded-vtpm \
    --shielded-integrity-monitoring \
    --labels=goog-ec-src=vm_add-gcloud \
    --reservation-affinity=any

echo ""
echo -e "${GREEN}Step 7: Waiting for VM to start${NC}"
sleep 20

echo ""
echo -e "${GREEN}Step 8: Checking service status${NC}"
gcloud compute ssh $NEW_VM_NAME --zone=$ZONE --project=$PROJECT_ID --command="sudo systemctl status benzinga-scraper --no-pager" || true

echo ""
echo -e "${GREEN}✅ Conversion complete!${NC}"
echo ""
echo "New VM: $NEW_VM_NAME (standard, non-preemptible)"
echo "Old image saved as: $IMAGE_NAME"
echo ""
echo "Next steps:"
echo "1. Verify service is running: gcloud compute ssh $NEW_VM_NAME --zone=$ZONE --command='sudo systemctl status benzinga-scraper'"
echo "2. Check logs: gcloud compute ssh $NEW_VM_NAME --zone=$ZONE --command='sudo tail -50 /var/log/benzinga-scraper.log'"
echo "3. Delete old image after verification: gcloud compute images delete $IMAGE_NAME --project=$PROJECT_ID"
