# ⚡ Quick Start Guide - 5 Minutes to Deployment

Deploy a $4/month Benzinga scraper on Google Cloud Spot VM

## Prerequisites (5 minutes to install)
- Google Cloud account with billing enabled
- gcloud CLI: `brew install google-cloud-sdk` (Mac) or [download](https://cloud.google.com/sdk/docs/install)
- Benzinga Pro credentials

## Step-by-Step Deployment

### 1. Initial Setup (1 minute)
```bash
cd /Users/wotanvonklass/Development/GCP-Trader/cloud-run-scraper

# Login to GCP
gcloud auth login

# Set your project ID
export GCP_PROJECT_ID=your-project-id
gcloud config set project $GCP_PROJECT_ID

# Copy environment template
cp .env.example .env
```

### 2. Configure Credentials (1 minute)
Edit `.env` and set:
```bash
GCP_PROJECT_ID=your-project-id
BENZINGA_EMAIL=your-email@example.com
BENZINGA_PASSWORD=your-password
ZONE=us-east4-a
VM_NAME=benzinga-scraper
```

### 3. Copy Extension (30 seconds)
```bash
cp -r ../benzinga-addon ./benzinga-addon
```

### 4. Deploy to Spot VM (3-5 minutes)
```bash
# Load environment variables
source .env

# Make deploy script executable
chmod +x deploy-vm.sh

# Deploy!
./deploy-vm.sh
```

The script will:
- Build Docker container (~2-3 min)
- Push to Google Container Registry
- Create Spot VM with Container-Optimized OS
- Deploy container with auto-restart
- Output your VM's external IP

### 5. Test It! (30 seconds)
```bash
# Get your VM's IP (shown after deployment)
export EXTERNAL_IP=<your-vm-ip>

# Check health
curl http://$EXTERNAL_IP:8080

# Trigger a scrape
curl http://$EXTERNAL_IP:8080/scrape

# View news
curl http://$EXTERNAL_IP:8080/news
```

## 🎉 Done!

Your scraper is now running 24/7 on a Spot VM for ~$4/month!

## Next Steps

### Monitor Your VM
```bash
# Check VM status
./vm-monitor.sh

# View live logs
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker logs -f benzinga-scraper'

# SSH into VM
gcloud compute ssh benzinga-scraper --zone=us-east4-a
```

### Update Configuration
```bash
# Change scrape interval (currently 60 seconds)
# Edit and redeploy, or SSH into VM and update container env vars
gcloud compute ssh benzinga-scraper --zone=us-east4-a
# Then run: docker restart benzinga-scraper
```

### Add Webhook
```bash
# Edit deploy-vm.sh and add to startup script:
#   -e WEBHOOK_URL="https://your-api.com/webhook" \
# Then redeploy
./deploy-vm.sh
```

## 💰 Cost Estimate

**Spot VM**: ~$4/month
**Regular VM** (if spot preempted too often): ~$14/month

Both are significantly cheaper than managed alternatives!

## Managing Your VM

### Start/Stop
```bash
# Stop VM to save money
gcloud compute instances stop benzinga-scraper --zone=us-east4-a

# Start VM
gcloud compute instances start benzinga-scraper --zone=us-east4-a
```

### Delete VM
```bash
gcloud compute instances delete benzinga-scraper --zone=us-east4-a
```

## 🐛 Troubleshooting

### Deployment fails?
```bash
# Check if billing is enabled
gcloud beta billing projects describe $GCP_PROJECT_ID

# Enable required APIs manually
gcloud services enable compute.googleapis.com cloudbuild.googleapis.com
```

### Extension not loading?
```bash
# Verify extension exists locally
ls -la benzinga-addon/

# Check if extension is in container
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker exec benzinga-scraper ls -la /app/benzinga-addon'
```

### Login failing?
```bash
# Check container logs for login errors
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker logs benzinga-scraper 2>&1 | grep -i login'

# Verify credentials are set
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker exec benzinga-scraper env | grep BENZINGA'
```

### Can't access via HTTP?
```bash
# Check firewall rules
gcloud compute firewall-rules list

# Create firewall rule if needed
gcloud compute firewall-rules create allow-http \
    --allow tcp:8080 \
    --target-tags http-server

# Get VM IP
gcloud compute instances describe benzinga-scraper \
    --zone=us-east4-a \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

### VM gets preempted?
Spot VMs can be preempted by Google. Options:
1. Restart manually: `gcloud compute instances start benzinga-scraper --zone=us-east4-a`
2. Set up auto-restart (see README.md)
3. Upgrade to regular VM (~$14/month) by editing deploy-vm.sh

## 📚 Full Documentation

See [README.md](README.md) for:
- Detailed monitoring guide
- Auto-restart on preemption
- Upgrade to regular VM
- Complete troubleshooting guide
- Architecture diagram
