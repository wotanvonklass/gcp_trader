# GCP Deployment Guide - Polygon Proxy

## Recommended GCP Machine Types

### Option 1: Development/Testing (Low Cost)
**Machine Type:** `e2-micro` or `e2-small`

**Specs:**
- **e2-micro**: 2 vCPUs, 1 GB RAM (~$7/month)
- **e2-small**: 2 vCPUs, 2 GB RAM (~$14/month)

**Good for:**
- ✅ Development and testing
- ✅ Low volume (< 10 concurrent clients)
- ✅ Single symbol subscriptions
- ✅ Learning and experimentation

**Limitations:**
- ⚠️ May struggle with high message rates
- ⚠️ Limited concurrent connections
- ⚠️ Swap may be needed for e2-micro

### Option 2: Production Light (Balanced)
**Machine Type:** `e2-medium` or `n2-standard-2`

**Specs:**
- **e2-medium**: 2 vCPUs, 4 GB RAM (~$28/month)
- **n2-standard-2**: 2 vCPUs, 8 GB RAM (~$70/month)

**Good for:**
- ✅ Production with moderate load
- ✅ 50-100 concurrent clients
- ✅ Multiple symbol subscriptions
- ✅ Wildcard subscribers (few)
- ✅ Real-time trading applications

**Performance:**
- Messages/sec: ~10,000-50,000
- Client connections: 50-100
- Memory usage: ~2-4 GB under load

### Option 3: Production High Volume (Recommended)
**Machine Type:** `n2-standard-4` or `c2-standard-4`

**Specs:**
- **n2-standard-4**: 4 vCPUs, 16 GB RAM (~$140/month)
- **c2-standard-4**: 4 vCPUs, 16 GB RAM, optimized CPU (~$152/month)

**Good for:**
- ✅ High-volume production
- ✅ 100-500 concurrent clients
- ✅ Wildcard subscriptions
- ✅ High message throughput
- ✅ Multiple filtered proxies

**Performance:**
- Messages/sec: ~100,000+
- Client connections: 100-500
- Memory usage: ~4-8 GB under load

### Option 4: Enterprise/Ultra High Volume
**Machine Type:** `n2-standard-8` or `c2-standard-8`

**Specs:**
- **n2-standard-8**: 8 vCPUs, 32 GB RAM (~$280/month)
- **c2-standard-8**: 8 vCPUs, 32 GB RAM, compute-optimized (~$304/month)

**Good for:**
- ✅ Enterprise deployments
- ✅ 500+ concurrent clients
- ✅ Multiple wildcard subscribers
- ✅ Ultra-high throughput
- ✅ Multiple firehose + filtered proxy pairs

**Performance:**
- Messages/sec: ~500,000+
- Client connections: 500-1000+
- Memory usage: ~8-16 GB under load

## Architecture Deployment Patterns

### Pattern 1: Single VM (Simple)
**Cost: $14-70/month**

```
┌─────────────────────────────────┐
│   Single GCP VM (e2-medium+)    │
│                                 │
│   ┌─────────────────────────┐   │
│   │  Firehose Proxy :8767   │   │
│   └─────────────────────────┘   │
│             ↕                   │
│   ┌─────────────────────────┐   │
│   │  Filtered Proxy :8765   │   │
│   └─────────────────────────┘   │
└─────────────────────────────────┘
```

**Use when:**
- Small to medium load
- Cost is primary concern
- Simple deployment preferred

**Recommended specs:**
- Minimum: `e2-medium` (2 vCPU, 4 GB RAM)
- Recommended: `n2-standard-2` (2 vCPU, 8 GB RAM)

### Pattern 2: Separate VMs (Scalable)
**Cost: $28-140/month**

```
┌──────────────────────────┐      ┌──────────────────────────┐
│  Firehose VM             │      │  Filtered VM(s)          │
│  (e2-small/n2-standard-2)│      │  (e2-medium+)            │
│                          │      │                          │
│  ┌────────────────────┐  │      │  ┌────────────────────┐  │
│  │ Firehose Proxy     │  │◄─────┤  │ Filtered Proxy 1   │  │
│  │ :8767              │  │      │  │ :8765              │  │
│  └────────────────────┘  │      │  └────────────────────┘  │
└──────────────────────────┘      │                          │
                                  │  ┌────────────────────┐  │
                                  │  │ Filtered Proxy 2   │  │
                                  │  │ :8775              │  │
                                  │  └────────────────────┘  │
                                  └──────────────────────────┘
```

**Use when:**
- Need to scale filtered proxies independently
- High availability required
- Want to isolate failure domains

**Recommended specs:**
- Firehose VM: `n2-standard-2` (2 vCPU, 8 GB RAM)
- Filtered VM(s): `n2-standard-2` or `n2-standard-4`

### Pattern 3: High Availability (Production)
**Cost: $140-560/month**

```
┌──────────────┐  ┌──────────────┐
│  Firehose 1  │  │  Firehose 2  │  (Primary + Backup)
│  n2-standard-4│  │  n2-standard-4│
└──────┬───────┘  └──────┬───────┘
       │                 │
       └────────┬────────┘
                ↓
        ┌──────────────┐
        │ Load Balancer│
        └──────┬───────┘
               ↓
     ┌─────────┴─────────┐
     ↓                   ↓
┌──────────┐      ┌──────────┐
│Filtered 1│      │Filtered 2│  (Scale as needed)
│n2-standard-4│    │n2-standard-4│
└──────────┘      └──────────┘
```

**Use when:**
- Production system with SLA requirements
- Cannot afford downtime
- High concurrent client load

**Recommended specs:**
- Firehose VMs: `n2-standard-4` (4 vCPU, 16 GB RAM) each
- Filtered VMs: `n2-standard-4` (4 vCPU, 16 GB RAM) each
- Load Balancer: GCP Load Balancer (TCP/WebSocket)

## Resource Sizing Guide

### Memory Requirements

**Firehose Proxy:**
```
Base: 100 MB
+ Per symbol subscribed: ~1 MB
+ Message buffers: 200-500 MB
+ Connection overhead: ~50 MB

Example:
- 100 symbols: ~650 MB
- 1000 symbols: ~1.5 GB
```

**Filtered Proxy:**
```
Base: 100 MB
+ Per client connection: ~2-5 MB
+ Subscription tracking: ~1 MB per 100 clients
+ Message buffers: 200-500 MB

Example:
- 50 clients: ~500 MB
- 200 clients: ~1.5 GB
- 500 clients: ~3 GB
```

### CPU Requirements

**Firehose Proxy:**
- Baseline: 1 vCPU (< 10k msgs/sec)
- Medium: 2 vCPUs (10k-50k msgs/sec)
- High: 4+ vCPUs (50k+ msgs/sec)

**Filtered Proxy:**
- Baseline: 1 vCPU (< 50 clients)
- Medium: 2 vCPUs (50-200 clients)
- High: 4+ vCPUs (200+ clients)

### Network Requirements

**Bandwidth estimates:**
- Per trade message: ~200-500 bytes
- 10k msgs/sec: ~5-10 Mbps
- 100k msgs/sec: ~50-100 Mbps

**GCP Network tiers:**
- Standard tier: Usually sufficient
- Premium tier: Use for global deployment

## Cost Optimization

### 1. Use Committed Use Discounts (CUD)
Save 37-55% with 1-year or 3-year commits:

```
n2-standard-2:
- On-demand: ~$70/month
- 1-year CUD: ~$44/month (37% off)
- 3-year CUD: ~$32/month (55% off)
```

### 2. Use Spot/Preemptible VMs for Non-Critical
Save 60-91% for dev/test:

```
n2-standard-2:
- On-demand: ~$70/month
- Spot: ~$16/month (77% off)
```

⚠️ Not recommended for production (can be terminated)

### 3. Right-Size Your VMs

Start small and scale up:
```bash
# Monitor actual usage
gcloud compute instances describe INSTANCE_NAME \
  --format="get(machineType)"

# Check metrics
gcloud monitoring time-series list \
  --filter="resource.type=gce_instance"
```

### 4. Use Autoscaling for Filtered Proxies

Create instance template + managed instance group:
```bash
# Scale filtered proxies based on load
gcloud compute instance-groups managed set-autoscaling \
  filtered-proxy-group \
  --max-num-replicas=10 \
  --min-num-replicas=2 \
  --target-cpu-utilization=0.7
```

## My Recommendations

### For Development (You're just starting)
```
1 VM: e2-medium (2 vCPU, 4 GB RAM) @ $28/month
- Run both firehose and filtered on same VM
- Use systemd to manage both services
- Monitor resource usage
```

### For Production (< 100 clients)
```
1 VM: n2-standard-2 (2 vCPU, 8 GB RAM) @ $70/month
OR
2 VMs:
  - Firehose: e2-medium @ $28/month
  - Filtered: e2-medium @ $28/month
Total: $56/month
```

### For Production (100-500 clients)
```
2 VMs:
  - Firehose: n2-standard-2 (2 vCPU, 8 GB RAM) @ $70/month
  - Filtered: n2-standard-4 (4 vCPU, 16 GB RAM) @ $140/month
Total: $210/month
```

### For Production (500+ clients or HA)
```
4 VMs:
  - 2x Firehose: n2-standard-4 @ $140/month each
  - 2x Filtered: n2-standard-4 @ $140/month each
  + Load Balancer: ~$20/month
Total: $580/month
```

## GCP-Specific Optimizations

### 1. Use Custom Machine Types
Fine-tune vCPU/RAM ratio:

```bash
# Create custom machine with 2 vCPUs, 6 GB RAM
gcloud compute instances create firehose-proxy \
  --custom-cpu=2 \
  --custom-memory=6GB \
  --zone=us-central1-a
```

### 2. Use Local SSD for Caching (Optional)
If you add caching/replay features:

```bash
gcloud compute instances create filtered-proxy \
  --machine-type=n2-standard-2 \
  --local-ssd=interface=NVME \
  --zone=us-central1-a
```

### 3. Enable Maintenance Policies
Prevent disruptions:

```bash
gcloud compute instances create firehose-proxy \
  --maintenance-policy=MIGRATE \
  --machine-type=n2-standard-2
```

### 4. Use Regional Persistent Disks
For high availability:

```bash
gcloud compute disks create firehose-data \
  --type=pd-balanced \
  --size=50GB \
  --replica-zones=us-central1-a,us-central1-b
```

## Quick Start: Launch Commands

### Single VM Deployment (Development)

```bash
# Create VM
gcloud compute instances create polygon-proxy \
  --machine-type=e2-medium \
  --zone=us-central1-a \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB \
  --tags=http-server,https-server,websocket

# Allow WebSocket ports
gcloud compute firewall-rules create allow-polygon-proxy \
  --allow=tcp:8765,tcp:8767 \
  --target-tags=websocket

# SSH and setup
gcloud compute ssh polygon-proxy --zone=us-central1-a

# Install Rust (on VM)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# Clone and build
git clone <your-repo>
cd polygon_proxy/firehose-proxy && cargo build --release &
cd polygon_proxy/filtered-proxy && cargo build --release &

# Run with systemd (see systemd section below)
```

### Two-VM Deployment (Production)

```bash
# Create firehose VM
gcloud compute instances create firehose-proxy \
  --machine-type=n2-standard-2 \
  --zone=us-central1-a \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB \
  --tags=firehose-server

# Create filtered VM
gcloud compute instances create filtered-proxy \
  --machine-type=n2-standard-2 \
  --zone=us-central1-a \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB \
  --tags=filtered-server

# Firewall rules
gcloud compute firewall-rules create allow-firehose \
  --allow=tcp:8767 \
  --target-tags=firehose-server \
  --source-tags=filtered-server

gcloud compute firewall-rules create allow-filtered-external \
  --allow=tcp:8765 \
  --target-tags=filtered-server
```

## Systemd Service Files

### Firehose Service: `/etc/systemd/system/polygon-firehose.service`

```ini
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
```

### Filtered Service: `/etc/systemd/system/polygon-filtered.service`

```ini
[Unit]
Description=Polygon Filtered Proxy
After=network.target

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
```

### Enable services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable polygon-firehose
sudo systemctl enable polygon-filtered
sudo systemctl start polygon-firehose
sudo systemctl start polygon-filtered

# Check status
sudo systemctl status polygon-firehose
sudo systemctl status polygon-filtered

# View logs
sudo journalctl -u polygon-firehose -f
sudo journalctl -u polygon-filtered -f
```

## Monitoring Setup

### Install monitoring agent:

```bash
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
sudo bash add-google-cloud-ops-agent-repo.sh --also-install

# Configure
sudo nano /etc/google-cloud-ops-agent/config.yaml
```

### Monitor metrics:

```yaml
# /etc/google-cloud-ops-agent/config.yaml
metrics:
  receivers:
    hostmetrics:
      collection_interval: 60s
  service:
    pipelines:
      default_pipeline:
        receivers: [hostmetrics]

logging:
  receivers:
    syslog:
      type: files
      include_paths:
      - /var/log/syslog
      - /var/log/messages
  processors:
    parse_json:
      type: parse_json
  service:
    pipelines:
      default_pipeline:
        receivers: [syslog]
        processors: [parse_json]
```

## Summary: My Top Picks

| Scenario | Machine Type | Monthly Cost | Use Case |
|----------|--------------|--------------|----------|
| **Development** | e2-medium | $28 | Learning, testing, low volume |
| **Production Starter** | n2-standard-2 | $70 | < 100 clients, real-time apps |
| **Production Standard** | n2-standard-4 | $140 | 100-500 clients, multiple symbols |
| **Production HA** | 2x n2-standard-4 + LB | $300 | High availability, 500+ clients |
| **Enterprise** | c2-standard-8 | $304+ | Ultra-high volume, 1000+ clients |

**Start here:** `e2-medium` ($28/month) or `n2-standard-2` ($70/month) for production

**Scale to:** `n2-standard-4` ($140/month) when you hit 100+ concurrent clients

**High availability:** Add redundancy with multiple VMs + load balancer
