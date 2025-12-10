# GCP Deployment - Minimal Setup (2 Clients per Service)

## Your Use Case

**Firehose Proxy:**
- 1 connection to Polygon
- 2 filtered proxy clients
- **Total: 3 connections**

**Filtered Proxy:**
- 1 connection to firehose
- 2 end-user clients
- **Total: 3 connections**

This is **extremely light load** - even the smallest GCP instances will work perfectly!

## Recommended Configurations

### Option 1: Ultra-Minimal (Best Value) 💰
**Machine Type:** `e2-micro` (Shared core)

**Specs:**
- **vCPUs:** 2 (shared, 0.25-2.0 vCPU)
- **RAM:** 1 GB
- **Cost:** ~$7/month per VM
- **Network:** 1 Gbps

**Deployment:**
```
Total cost: ~$14/month for both VMs
```

**Performance for your use case:**
- ✅ Perfect for 2-3 connections per VM
- ✅ Can handle 10,000+ messages/sec
- ✅ Sub-millisecond routing latency
- ✅ Plenty of headroom

**Limitations:**
- Shared CPU (may have occasional slowdowns during GCP maintenance)
- Limited to 1 GB RAM (fine for 2-3 connections)

### Option 2: Small Dedicated (Recommended) ⭐
**Machine Type:** `e2-small`

**Specs:**
- **vCPUs:** 2 (dedicated)
- **RAM:** 2 GB
- **Cost:** ~$14/month per VM
- **Network:** 1 Gbps

**Deployment:**
```
Total cost: ~$28/month for both VMs
```

**Performance for your use case:**
- ✅ Dedicated CPU (no sharing)
- ✅ 2 GB RAM (overkill for 2-3 connections)
- ✅ Can easily handle 50,000+ messages/sec
- ✅ Rock-solid stability

**Why this is best:**
- Only $14 more than e2-micro setup
- No CPU throttling during peak times
- Plenty of room to add more clients later (up to 20-30)
- Production-ready stability

### Option 3: Single VM (Most Cost-Effective) 💎
**Machine Type:** `e2-small` or `e2-medium`

**Run BOTH proxies on one VM:**

```
┌─────────────────────────────────────┐
│   Single GCP VM (e2-small)          │
│                                     │
│   Firehose Proxy :8767              │
│   Filtered Proxy :8765              │
│                                     │
│   CPU usage: ~5-10%                 │
│   RAM usage: ~300-500 MB            │
└─────────────────────────────────────┘
```

**Cost:**
- `e2-small`: ~$14/month
- `e2-medium`: ~$28/month (if you want extra headroom)

**Performance:**
- ✅ Both services run comfortably
- ✅ Low resource usage (plenty of spare capacity)
- ✅ Simplest deployment
- ✅ Can handle 10x current load

## My Recommendation for You

### 🎯 Best Choice: Single `e2-small` VM ($14/month)

**Why:**
1. **More than enough power** for your use case
2. **Simplest deployment** - one VM, one setup
3. **Cheapest option** - single VM costs
4. **Easy to scale** - upgrade to e2-medium if needed

**Resource usage estimate:**
```
Firehose (2 filtered clients):
- CPU: ~2-5%
- RAM: ~150-200 MB

Filtered (2 end clients):
- CPU: ~2-5%
- RAM: ~150-200 MB

Total on e2-small:
- CPU: ~10% (of 2 vCPUs)
- RAM: ~400 MB (of 2 GB)

You're using: 10% CPU, 20% RAM
Headroom: 90% CPU, 80% RAM 🚀
```

### 🎯 Alternative: Two `e2-micro` VMs ($14/month total)

**If you want separation:**

**Firehose VM (e2-micro):**
- Cost: $7/month
- CPU: 5-10% usage
- RAM: ~200 MB of 1 GB

**Filtered VM (e2-micro):**
- Cost: $7/month
- CPU: 5-10% usage
- RAM: ~200 MB of 1 GB

**Benefits:**
- Same total cost as single e2-small
- Isolated failure domains
- Can scale independently

**Drawbacks:**
- Manage two VMs instead of one
- Shared CPU may throttle occasionally

## Deployment Commands

### Single VM Setup (Recommended)

```bash
# Create VM
gcloud compute instances create polygon-proxy \
  --machine-type=e2-small \
  --zone=us-central1-a \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=10GB \
  --boot-disk-type=pd-standard \
  --tags=websocket-server

# Allow WebSocket ports
gcloud compute firewall-rules create allow-polygon-websocket \
  --allow=tcp:8765,tcp:8767 \
  --target-tags=websocket-server \
  --description="Allow WebSocket connections for Polygon proxy"

# SSH into VM
gcloud compute ssh polygon-proxy --zone=us-central1-a
```

### Two VM Setup (If you want separation)

```bash
# Firehose VM (e2-micro)
gcloud compute instances create polygon-firehose \
  --machine-type=e2-micro \
  --zone=us-central1-a \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=10GB \
  --boot-disk-type=pd-standard \
  --tags=firehose-server

# Filtered VM (e2-micro)
gcloud compute instances create polygon-filtered \
  --machine-type=e2-micro \
  --zone=us-central1-a \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=10GB \
  --boot-disk-type=pd-standard \
  --tags=filtered-server

# Firewall: Allow filtered to connect to firehose
gcloud compute firewall-rules create allow-firehose-internal \
  --allow=tcp:8767 \
  --target-tags=firehose-server \
  --source-tags=filtered-server

# Firewall: Allow external clients to connect to filtered
gcloud compute firewall-rules create allow-filtered-external \
  --allow=tcp:8765 \
  --target-tags=filtered-server
```

## Setup on VM

```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# Clone your repo
git clone <your-repo-url>
cd polygon_proxy

# Build both proxies (release mode)
cd firehose-proxy && cargo build --release
cd ../filtered-proxy && cargo build --release

# Create .env files
cd ~/polygon_proxy/firehose-proxy
cat > .env << EOF
POLYGON_API_KEY=your_key_here
FIREHOSE_PORT=8767
LOG_LEVEL=info
EOF

cd ~/polygon_proxy/filtered-proxy
cat > .env << EOF
FIREHOSE_URL=ws://localhost:8767  # Same VM
POLYGON_API_KEY=your_key_here
FILTERED_PROXY_PORT=8765
LOG_LEVEL=info
EOF
```

## Systemd Services (Single VM)

### Firehose service

```bash
sudo tee /etc/systemd/system/polygon-firehose.service > /dev/null << EOF
[Unit]
Description=Polygon Firehose Proxy
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/polygon_proxy/firehose-proxy
Environment="PATH=/home/ubuntu/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/ubuntu/polygon_proxy/firehose-proxy/target/release/firehose_proxy
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

### Filtered service

```bash
sudo tee /etc/systemd/system/polygon-filtered.service > /dev/null << EOF
[Unit]
Description=Polygon Filtered Proxy
After=network.target polygon-firehose.service
Requires=polygon-firehose.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/polygon_proxy/filtered-proxy
Environment="PATH=/home/ubuntu/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/ubuntu/polygon_proxy/filtered-proxy/target/release/polygon_filtered_proxy
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

### Start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable polygon-firehose polygon-filtered
sudo systemctl start polygon-firehose
sleep 2  # Let firehose start first
sudo systemctl start polygon-filtered

# Check status
sudo systemctl status polygon-firehose
sudo systemctl status polygon-filtered

# View logs
sudo journalctl -u polygon-firehose -f
sudo journalctl -u polygon-filtered -f
```

## Cost Breakdown

### Single VM (e2-small) - RECOMMENDED
```
VM cost:           $14.00/month
Disk (10 GB):      $0.40/month
Network egress:    $1-2/month (minimal for 2 clients)
─────────────────────────────
TOTAL:            ~$16/month
```

### Two VMs (e2-micro each)
```
Firehose VM:       $7.00/month
Filtered VM:       $7.00/month
Disk (10 GB x2):   $0.80/month
Network egress:    $1-2/month
─────────────────────────────
TOTAL:            ~$16/month
```

### Cost Optimization: Use Spot VMs (if downtime OK)

```bash
# Same command with --provisioning-model=SPOT
gcloud compute instances create polygon-proxy \
  --machine-type=e2-small \
  --provisioning-model=SPOT \
  --instance-termination-action=STOP \
  --zone=us-central1-a \
  ...

# Cost: ~$4/month (vs $14/month)
# Risk: Can be terminated (usually rare, restarts automatically)
```

## Scaling Plan (Future)

**When you need more capacity:**

### From e2-small → e2-medium ($14 → $28/month)
```bash
gcloud compute instances stop polygon-proxy
gcloud compute instances set-machine-type polygon-proxy \
  --machine-type=e2-medium
gcloud compute instances start polygon-proxy
```

### From single VM → two VMs
1. Create second VM
2. Move filtered proxy to new VM
3. Update `FIREHOSE_URL` to point to first VM's internal IP

## Monitoring (Free Tier)

GCP provides free monitoring:

```bash
# View CPU usage
gcloud monitoring time-series list \
  --filter='metric.type="compute.googleapis.com/instance/cpu/utilization"' \
  --format=json

# View memory usage
gcloud monitoring time-series list \
  --filter='metric.type="compute.googleapis.com/instance/memory/utilization"' \
  --format=json
```

Or use Cloud Console → Monitoring → Dashboards

## Performance Expectations

### e2-small with your load (2 clients each):

**CPU Usage:**
- Idle: 1-2%
- Active (1k msgs/sec): 5-8%
- Peak (10k msgs/sec): 15-25%

**Memory Usage:**
- Firehose: ~200 MB
- Filtered: ~200 MB
- OS: ~300 MB
- **Total: ~700 MB of 2 GB (35%)**

**Network:**
- 2 clients @ 1k msgs/sec: ~2-5 Mbps
- Plenty of headroom on 1 Gbps link

**Latency:**
- Client → Filtered → Firehose → Polygon: < 5ms
- Message routing: < 1ms
- Total round-trip: < 10ms

## Production Checklist

- [ ] Use `e2-small` or better (not e2-micro for production)
- [ ] Enable automatic backups
- [ ] Set up monitoring alerts
- [ ] Configure HTTPS/WSS with SSL cert (use Caddy or nginx)
- [ ] Enable Cloud Logging
- [ ] Set up log rotation
- [ ] Document internal IPs in case of restart
- [ ] Test failover procedures

## SSL/TLS Setup (Optional but Recommended)

### Using Caddy (easiest)

```bash
# Install Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# Configure Caddy
sudo tee /etc/caddy/Caddyfile > /dev/null << EOF
yourdomain.com {
    reverse_proxy /filtered localhost:8765
}
EOF

sudo systemctl restart caddy
```

Now clients connect to: `wss://yourdomain.com/filtered`

## Summary: Your Perfect Setup

### 🏆 Winner: Single e2-small VM

**Specs:**
- Machine: e2-small (2 vCPU, 2 GB RAM)
- Cost: ~$16/month
- Region: us-central1-a (or nearest to Polygon servers)

**Why it's perfect:**
- ✅ Way more power than you need (90% idle)
- ✅ Simplest setup (one VM)
- ✅ Cheapest option
- ✅ Easy to upgrade later
- ✅ Can handle 10x your current load

**Command to launch:**
```bash
gcloud compute instances create polygon-proxy \
  --machine-type=e2-small \
  --zone=us-central1-a \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=10GB \
  --tags=websocket-server

gcloud compute firewall-rules create allow-polygon \
  --allow=tcp:8765,tcp:8767 \
  --target-tags=websocket-server
```

You're all set for **$16/month**! 🚀
