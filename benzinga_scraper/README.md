# Benzinga Scraper on Compute Engine Spot VM

**Cost: ~$4/month** - Run 24/7 headless Chrome scraper on Google Cloud Platform

## What This Does

- Runs headless Chrome with your Benzinga extension on a Spot VM
- Logs into Benzinga Pro automatically
- Captures real-time news 24/7
- Sends news to webhook (optional)
- Auto-restarts on failure
- **Super cheap**: ~$4/month with spot pricing

## Prerequisites

1. **GCP Account** with billing enabled
2. **gcloud CLI** installed ([install guide](https://cloud.google.com/sdk/docs/install))
3. **Benzinga Pro** subscription with login credentials
4. **Benzinga extension** (benzinga-addon folder)

## Quick Deploy

```bash
# 1. Configure environment variables
cp .env.example .env
nano .env  # Set GCP_PROJECT_ID, BENZINGA_EMAIL, BENZINGA_PASSWORD

# 2. Load environment variables
source .env

# 3. Make scripts executable
chmod +x deploy-vm.sh vm-monitor.sh

# 4. Deploy the VM
./deploy-vm.sh
```

This will:
1. Build your Docker image
2. Create an e2-small spot VM
3. Deploy the container with auto-restart
4. Return the external IP address

## What You Get

- **e2-small spot VM**: 2 vCPUs, 2 GB RAM
- **Container-Optimized OS**: Optimized for Docker
- **Auto-restart**: Container restarts automatically on failure
- **Spot instance**: ~$4/month (may be preempted, auto-restarts)
- **24/7 operation**: Continuous scraping

## Configuration

Edit `.env` file:

```bash
# GCP Settings
GCP_PROJECT_ID=your-project-id
VM_NAME=benzinga-scraper
ZONE=us-east4-a

# Benzinga Credentials
BENZINGA_EMAIL=your-email@example.com
BENZINGA_PASSWORD=your-password

# Optional
WEBHOOK_URL=https://your-api.com/webhook/news
```

## Monitoring

### Check Status

```bash
# Monitor VM and service status
./vm-monitor.sh

# View live logs
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker logs -f benzinga-scraper'

# SSH into VM
gcloud compute ssh benzinga-scraper --zone=us-east4-a

# Check service health
curl http://EXTERNAL_IP:8080
curl http://EXTERNAL_IP:8080/news
```

### Available Endpoints

- `GET /` - Health check & status
- `GET /scrape` - Manually trigger a scrape
- `GET /news` - Get latest scraped news

## Managing the VM

### Start/Stop

```bash
# Stop VM (saves money when not needed)
gcloud compute instances stop benzinga-scraper --zone=us-east4-a

# Start VM
gcloud compute instances start benzinga-scraper --zone=us-east4-a
```

### Restart Container

```bash
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker restart benzinga-scraper'
```

### Update Extension or Code

```bash
# 1. Update your code/extension locally
cp -r ../benzinga-addon ./benzinga-addon

# 2. Rebuild and push new image
gcloud builds submit --tag gcr.io/${GCP_PROJECT_ID}/benzinga-scraper

# 3. SSH into VM
gcloud compute ssh benzinga-scraper --zone=us-east4-a

# 4. Update container (run on VM)
docker pull gcr.io/${GCP_PROJECT_ID}/benzinga-scraper
docker stop benzinga-scraper
docker rm benzinga-scraper
docker run -d --name benzinga-scraper --restart=always \
    -p 8080:8080 \
    -e BENZINGA_EMAIL="${BENZINGA_EMAIL}" \
    -e BENZINGA_PASSWORD="${BENZINGA_PASSWORD}" \
    -e RUN_MODE="continuous" \
    -e SCRAPE_INTERVAL="60000" \
    gcr.io/${GCP_PROJECT_ID}/benzinga-scraper
```

### Delete VM

```bash
gcloud compute instances delete benzinga-scraper --zone=us-east4-a
```

## Spot Instance Behavior

**Spot VMs can be preempted** (terminated by Google) with 30 seconds notice. When this happens:
- VM stops automatically
- You can restart it manually or set up auto-restart
- Costs ~$4/month vs ~$14/month for regular VM

**Preemption frequency**: Typically rare (days to weeks), depends on GCP capacity

### Auto-Restart on Preemption (Optional)

Create a Cloud Scheduler job to periodically check and restart:

```bash
# Create a Cloud Scheduler job that runs every 5 minutes
gcloud scheduler jobs create http vm-restart-check \
    --location=us-central1 \
    --schedule="*/5 * * * *" \
    --uri="https://us-central1-${GCP_PROJECT_ID}.cloudfunctions.net/restart-vm" \
    --http-method=POST
```

Or simple cron job on your local machine:

```bash
# Add to crontab
*/5 * * * * gcloud compute instances start benzinga-scraper --zone=us-east4-a 2>/dev/null || true
```

## Upgrade to Regular VM (100% uptime)

If spot preemptions are too frequent, convert to regular VM (~$14/month):

```bash
# Delete spot VM
gcloud compute instances delete benzinga-scraper --zone=us-east4-a

# Edit deploy-vm.sh and remove these lines:
#   --provisioning-model=SPOT \
#   --instance-termination-action=STOP \

# Redeploy
./deploy-vm.sh
```

## Cost Breakdown

| Component | Spot VM | Regular VM |
|-----------|---------|------------|
| e2-small VM | $4.00 | $14.00 |
| 20GB disk | $0.80 | $0.80 |
| Egress | $0.50 | $0.50 |
| **Total** | **~$5.30/month** | **~$15.30/month** |

## Troubleshooting

### Container won't start

```bash
# Check Docker logs
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker logs benzinga-scraper'

# Check all containers
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker ps -a'

# Restart Docker
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='sudo systemctl restart docker'
```

### Login failures

```bash
# Verify credentials in startup script
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker exec benzinga-scraper env | grep BENZINGA'

# Check application logs for login errors
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker logs benzinga-scraper 2>&1 | grep -i login'
```

### Can't access via HTTP

```bash
# Check firewall rules
gcloud compute firewall-rules list

# Create firewall rule if needed
gcloud compute firewall-rules create allow-http \
    --allow tcp:8080 \
    --target-tags http-server

# Verify VM has correct network tags
gcloud compute instances describe benzinga-scraper \
    --zone=us-east4-a \
    --format='get(tags.items[])'

# Get VM external IP
gcloud compute instances describe benzinga-scraper \
    --zone=us-east4-a \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

### VM keeps getting preempted

Switch to regular VM for $14/month (still very affordable!)

### Extension not loading

```bash
# Check if extension files are in the container
gcloud compute ssh benzinga-scraper --zone=us-east4-a \
    --command='docker exec benzinga-scraper ls -la /app/benzinga-addon'

# Rebuild with extension
cp -r ../benzinga-addon ./
gcloud builds submit --tag gcr.io/${GCP_PROJECT_ID}/benzinga-scraper
```

## Local Testing

Test the Docker container locally before deploying:

```bash
# Build image
docker build -t benzinga-scraper .

# Run locally
docker run -it --rm \
    -p 8080:8080 \
    -e BENZINGA_EMAIL="your-email" \
    -e BENZINGA_PASSWORD="your-password" \
    -e RUN_MODE="single" \
    benzinga-scraper

# Test in another terminal
curl http://localhost:8080
curl http://localhost:8080/scrape
```

## Architecture

```
┌─────────────────────────────────────────┐
│         GCP Compute Engine              │
│  ┌───────────────────────────────────┐  │
│  │   Container-Optimized OS (COS)    │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │   Docker Container          │  │  │
│  │  │  ┌───────────────────────┐  │  │  │
│  │  │  │  Node.js App          │  │  │  │
│  │  │  │  - Express Server     │  │  │  │
│  │  │  │  - Puppeteer          │  │  │  │
│  │  │  │  ┌─────────────────┐  │  │  │  │
│  │  │  │  │ Headless Chrome │  │  │  │  │
│  │  │  │  │ + Extension     │  │  │  │  │
│  │  │  │  └─────────────────┘  │  │  │  │
│  │  │  └───────────────────────┘  │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
         │
         ▼
   Internet / Benzinga Pro
         │
         ▼
   Your Webhook (optional)
```

## Next Steps

After deployment:
1. Run `./vm-monitor.sh` to verify it's working
2. Check logs to ensure news is being captured
3. Set up alerts in Cloud Console (optional)
4. Configure webhook to send news to your backend (optional)
5. Set up auto-restart script for preemptions (optional)

## Support

- View logs: `gcloud compute ssh benzinga-scraper --zone=us-east4-a --command='docker logs -f benzinga-scraper'`
- GCP Compute Engine docs: https://cloud.google.com/compute/docs
- Puppeteer docs: https://pptr.dev

## License

MIT - Use freely for personal or commercial purposes
