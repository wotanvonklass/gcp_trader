# Deploy Polygon Proxy to GCP - Quick Start

Deploy all 3 Polygon proxy services to a single e2-small Spot VM in us-east4 for **~$4/month**.

## Prerequisites

- GCP account with billing enabled
- gcloud CLI installed
- Polygon.io API key

## Quick Deploy

```bash
# 1. Configure
cp .env.example .env
nano .env  # Set GCP_PROJECT_ID and POLYGON_API_KEY

# 2. Load variables
source .env

# 3. Deploy
./deploy-gcp.sh
```

**Wait 5-10 minutes** for Rust services to build and start.

## What Gets Deployed

**VM Specs:**
- Type: e2-small (2 vCPU, 2GB RAM)
- Cost: ~$4/month (Spot pricing)
- Zone: us-east4-a
- OS: Debian 12

**Services Running:**
1. **Firehose Proxy** (port 8767) - Connects to Polygon.io
2. **Ms-Aggregator** (port 8768) - Generates millisecond bars
3. **Filtered Proxy** (port 8765) - Client connection point

All services auto-start on boot via systemd.

## Connect to Proxy

```python
import websockets
import json

async def connect():
    # Use your VM's external IP
    async with websockets.connect("ws://YOUR_VM_IP:8765") as ws:
        # Authenticate
        await ws.send(json.dumps({
            "action": "auth",
            "params": "YOUR_POLYGON_API_KEY"
        }))

        # Subscribe to 100ms bars for AAPL
        await ws.send(json.dumps({
            "action": "subscribe",
            "params": "100Ms.AAPL,T.AAPL"
        }))

        # Receive data
        while True:
            msg = await ws.recv()
            print(msg)
```

## Firewall Setup

If you can't connect from external clients:

```bash
# Allow external connections to port 8765
gcloud compute firewall-rules create allow-polygon-proxy \
    --allow tcp:8765 \
    --target-tags polygon-proxy \
    --project=$GCP_PROJECT_ID
```

## Monitor Services

```bash
# SSH into VM
gcloud compute ssh polygon-proxy --zone=us-east4-a

# Check service status
sudo systemctl status firehose-proxy ms-aggregator filtered-proxy

# View logs
sudo journalctl -u firehose-proxy -f
sudo journalctl -u ms-aggregator -f
sudo journalctl -u filtered-proxy -f

# Restart a service
sudo systemctl restart firehose-proxy
```

## VM Management

```bash
# Stop VM (save money)
gcloud compute instances stop polygon-proxy --zone=us-east4-a

# Start VM
gcloud compute instances start polygon-proxy --zone=us-east4-a

# Delete VM
gcloud compute instances delete polygon-proxy --zone=us-east4-a
```

## Troubleshooting

### Services not starting?

```bash
# SSH into VM
gcloud compute ssh polygon-proxy --zone=us-east4-a

# Check build logs
tail -n 100 /var/log/syslog | grep polygon

# Rebuild manually
cd /home/polygonproxy/polygon_proxy
cd firehose-proxy && cargo build --release && cd ..
cd ms-aggregator && cargo build --release && cd ..
cd filtered-proxy && cargo build --release && cd ..

# Restart services
sudo systemctl restart firehose-proxy ms-aggregator filtered-proxy
```

### Can't connect to port 8765?

1. Check firewall rule exists
2. Verify all 3 services are running
3. Check VM external IP hasn't changed

### VM got preempted?

Spot VMs can be stopped by Google. Just restart:

```bash
gcloud compute instances start polygon-proxy --zone=us-east4-a
```

Services will auto-start on boot.

## Cost Breakdown

| Component | Cost/Month |
|-----------|------------|
| e2-small spot VM | $4.00 |
| 20GB disk | $0.80 |
| Egress | ~$0.50 |
| **Total** | **~$5.30/month** |

## Upgrade to Regular VM

If spot preemptions are too frequent (~$14/month):

```bash
# Delete spot VM
gcloud compute instances delete polygon-proxy --zone=us-east4-a

# Edit deploy-gcp.sh and remove:
#   --provisioning-model=SPOT \
#   --instance-termination-action=STOP \

# Redeploy
./deploy-gcp.sh
```

## Architecture

```
┌─────────────────────────────────────┐
│     GCP VM (us-east4-a)             │
│  ┌───────────────────────────────┐  │
│  │  Firehose Proxy (8767)        │  │
│  │    ↓                           │  │
│  │  Ms-Aggregator (8768)          │  │
│  │    ↓                           │  │
│  │  Filtered Proxy (8765) ←───── │  │ ← Your clients connect here
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
         ↕
    Polygon.io
```

## Next Steps

After deployment:
1. Wait 5-10 minutes for build to complete
2. Create firewall rule for port 8765
3. Test connection from your trading bot
4. Set up auto-restart for spot preemptions (optional)
