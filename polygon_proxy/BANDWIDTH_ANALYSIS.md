# Network Bandwidth Analysis - Polygon Proxy

## TL;DR

**Network Capacity:** ✅ No problem - even e2-micro has 1 Gbps
**Egress Costs:** ⚠️ Could be expensive depending on subscription volume

## Your Setup
- Firehose: 1 Polygon connection + 2 filtered proxies
- Filtered: 1 firehose connection + 2 end clients
- **Total external bandwidth:** Data from Polygon → Your 2 clients

## GCP Network Specs

| Instance Type | Network Bandwidth | Egress Cost |
|---------------|-------------------|-------------|
| e2-micro | 1 Gbps | Same as others |
| e2-small | 1 Gbps | Same as others |
| e2-medium | 2 Gbps | Same as others |
| n2-standard-2 | 10 Gbps | Same as others |

**Egress Pricing (to internet):**
- First 1 GB/month: FREE
- 1-10 TB: $0.085/GB ($85/TB)
- 10-150 TB: $0.065/GB ($65/TB)
- 150+ TB: $0.05/GB ($50/TB)

**Egress within GCP (same region):** FREE
**Ingress (incoming):** FREE

## Bandwidth Calculation by Subscription Type

### Scenario 1: Specific Symbols (Low Volume)
**Example:** Subscribe to `T.AAPL, Q.AAPL, T.GOOGL, Q.GOOGL` (4 subscriptions)

**Message rate:**
- AAPL trades: ~50-100/sec during active trading
- AAPL quotes: ~100-200/sec
- GOOGL trades: ~30-50/sec
- GOOGL quotes: ~80-150/sec
- **Total: ~300-500 msgs/sec**

**Bandwidth:**
- Message size: ~400 bytes average
- 500 msgs/sec × 400 bytes = 200 KB/sec = **1.6 Mbps**

**Monthly data transfer:**
- Trading hours: 6.5 hours/day × 5 days = 32.5 hours/week
- 200 KB/sec × 32.5 hours × 4 weeks = ~94 GB/month

**Cost:**
- First 1 GB: FREE
- 93 GB @ $0.085/GB = **~$8/month egress**

✅ **Bandwidth:** 1.6 Mbps (0.16% of 1 Gbps) - no issue
✅ **Cost:** ~$8/month - manageable

### Scenario 2: Multiple Symbols (Medium Volume)
**Example:** Subscribe to 20 popular stocks (T.* and Q.* for each)

**Message rate:**
- ~20 stocks × 150 msgs/sec average = **~3,000 msgs/sec**

**Bandwidth:**
- 3,000 msgs/sec × 400 bytes = 1.2 MB/sec = **9.6 Mbps**

**Monthly data transfer:**
- 1.2 MB/sec × 32.5 hours × 4 weeks = ~560 GB/month

**Cost:**
- 560 GB @ $0.085/GB = **~$48/month egress**

✅ **Bandwidth:** 9.6 Mbps (1% of 1 Gbps) - no issue
⚠️ **Cost:** ~$48/month - moderate

### Scenario 3: Heavy Subscriptions (High Volume)
**Example:** Subscribe to `T.*` (all trades) or top 100 stocks

**Message rate:**
- Market-wide: ~50,000-100,000 msgs/sec during peak
- For 2 clients with specific feeds: ~10,000-20,000 msgs/sec

**Bandwidth:**
- 20,000 msgs/sec × 400 bytes = 8 MB/sec = **64 Mbps**

**Monthly data transfer:**
- 8 MB/sec × 32.5 hours × 4 weeks = ~3.7 TB/month

**Cost:**
- 1 TB @ $0.085 = $85
- 2.7 TB @ $0.085 = $230
- **Total: ~$315/month egress** 💸

✅ **Bandwidth:** 64 Mbps (6.4% of 1 Gbps) - still no issue
❌ **Cost:** ~$315/month - expensive!

### Scenario 4: Wildcard or Full Market (Extreme)
**Example:** Subscribe to `*` (everything from Polygon)

**Message rate:**
- Full market: 100,000-500,000 msgs/sec during peak
- Average sustained: ~100,000 msgs/sec

**Bandwidth:**
- 100,000 msgs/sec × 400 bytes = 40 MB/sec = **320 Mbps**

**Monthly data transfer:**
- 40 MB/sec × 32.5 hours × 4 weeks = ~18.7 TB/month

**Cost:**
- 10 TB @ $0.085 = $850
- 8.7 TB @ $0.065 = $566
- **Total: ~$1,416/month egress** 💸💸💸

⚠️ **Bandwidth:** 320 Mbps (32% of 1 Gbps) - approaching limits
❌ **Cost:** ~$1,416/month - very expensive!

## Network Bandwidth: Is 1 Gbps Enough?

### For Your Use Case (2 clients):

| Subscription Type | Bandwidth Needed | % of 1 Gbps | Status |
|-------------------|------------------|-------------|--------|
| 1-5 symbols | 1-5 Mbps | 0.1-0.5% | ✅ Plenty |
| 10-20 symbols | 5-20 Mbps | 0.5-2% | ✅ Plenty |
| 50-100 symbols | 20-80 Mbps | 2-8% | ✅ Good |
| 500+ symbols | 100-300 Mbps | 10-30% | ✅ OK |
| Wildcard (*) | 300-800 Mbps | 30-80% | ⚠️ Tight |

**Conclusion:** 1 Gbps is enough for almost all scenarios with 2 clients.

### When You'd Need More Bandwidth:
- **10+ Gbps needed if:**
  - 50+ concurrent clients
  - Each client has wildcard subscription
  - OR 500+ clients with specific symbols

- **For 2 clients:** Even with wildcard, 1 Gbps is sufficient

## The Real Issue: Egress Costs 💰

**Bandwidth capacity is NOT the problem.**
**Egress costs ARE the potential problem.**

### Cost Optimization Strategies

#### 1. **Use Internal Traffic (FREE)**
If your clients are also on GCP in the same region:

```
Polygon → Firehose VM (us-central1-a)
            ↓ (FREE - internal)
         Filtered VM (us-central1-a)
            ↓ (FREE - internal)
         Client VMs (us-central1-a)

Total egress cost: $0 (except Polygon ingress, which is FREE)
```

✅ **Best option if your clients are on GCP**

#### 2. **Use Cloud CDN (if applicable)**
If serving many clients with same data:
- Cloud CDN: $0.02-0.08/GB (cheaper than direct egress)
- But doesn't work well for WebSocket/real-time

#### 3. **Compress Data**
Enable WebSocket compression:

```rust
// In your WebSocket config
use flate2::Compression;

// Compress messages before sending
let compressed = compress_message(&message)?;
```

**Savings:** 60-80% bandwidth reduction
**Example:** 1 TB/month → 200-400 GB/month = **save $50-70/month**

#### 4. **Client-Side Filtering (Not Always Possible)**
Instead of sending all data and filtering at proxy:
- Send minimal data to client
- Client requests specific updates

**But:** You're already doing this with filtered proxy! ✅

#### 5. **Use Committed Use Discount for Network**
GCP offers committed egress:
- 1-year commit: Save ~25%
- 3-year commit: Save ~50%

## Bandwidth Monitoring

### Check your actual usage:

```bash
# View network egress in last 24 hours
gcloud monitoring time-series list \
  --filter='metric.type="compute.googleapis.com/instance/network/sent_bytes_count"' \
  --format=json \
  --start-time=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)

# View bandwidth utilization
gcloud monitoring time-series list \
  --filter='metric.type="compute.googleapis.com/instance/network/sent_packets_count"' \
  --format=json
```

### Set up billing alerts:

```bash
# Alert when egress exceeds $50/month
gcloud alpha billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT \
  --display-name="Polygon Proxy Bandwidth Alert" \
  --budget-amount=50USD \
  --threshold-rule=percent=80 \
  --threshold-rule=percent=100
```

## Architecture to Minimize Egress Costs

### Option 1: Clients on Same GCP VM (FREE egress)
```
┌────────────────────────────────────────┐
│  Single GCP VM (us-central1-a)         │
│                                        │
│  ┌──────────────┐                      │
│  │  Firehose    │                      │
│  │  :8767       │                      │
│  └──────┬───────┘                      │
│         ↓ (local)                      │
│  ┌──────────────┐                      │
│  │  Filtered    │                      │
│  │  :8765       │                      │
│  └──────┬───────┘                      │
│         ↓ (local)                      │
│  ┌──────────────┐                      │
│  │  Your App    │                      │
│  │  (client)    │                      │
│  └──────────────┘                      │
│                                        │
│  Egress to internet: $0 ✅             │
└────────────────────────────────────────┘
```

### Option 2: Clients on Separate GCP VMs (FREE egress)
```
Firehose VM ─(internal)→ Filtered VM ─(internal)→ Client VMs
(us-central1-a)         (us-central1-a)         (us-central1-a)

All traffic: FREE (same region) ✅
```

### Option 3: Clients Outside GCP (Egress costs apply)
```
Firehose VM ─(internal)→ Filtered VM ─(INTERNET)→ External Clients
(us-central1-a)         (us-central1-a)         (egress costs $)

Only filtered → client traffic costs money
```

## Recommendations Based on Data Volume

### Low Volume (< 100 GB/month)
**Subscriptions:** 1-10 specific symbols
**Egress cost:** ~$8/month
**Bandwidth:** < 10 Mbps
**Instance:** e2-small (1 Gbps) ✅
**No action needed**

### Medium Volume (100 GB - 1 TB/month)
**Subscriptions:** 10-50 symbols
**Egress cost:** ~$50-85/month
**Bandwidth:** 10-100 Mbps
**Instance:** e2-medium (2 Gbps) ✅
**Consider:** Compression, internal clients

### High Volume (1-10 TB/month)
**Subscriptions:** 100+ symbols or selective wildcard
**Egress cost:** ~$85-650/month
**Bandwidth:** 100-500 Mbps
**Instance:** e2-medium or n2-standard-2 ✅
**Must:** Compression, move clients to GCP

### Extreme Volume (10+ TB/month)
**Subscriptions:** Full wildcard (*)
**Egress cost:** ~$650+/month
**Bandwidth:** 500 Mbps - 1 Gbps
**Instance:** n2-standard-2 (10 Gbps) ✅
**Must:** All clients on GCP (same region), compression

## Sample Egress Calculation

**Your setup with different subscriptions:**

| Symbols | Msgs/Sec | Bandwidth | GB/Month | Egress Cost |
|---------|----------|-----------|----------|-------------|
| 1 symbol | 200 | 0.8 Mbps | 30 GB | **$2.50** |
| 5 symbols | 1,000 | 4 Mbps | 150 GB | **$12** |
| 20 symbols | 3,000 | 12 Mbps | 450 GB | **$38** |
| 100 symbols | 15,000 | 60 Mbps | 2.2 TB | **$180** |
| Wildcard (*) | 100,000 | 400 Mbps | 15 TB | **$1,200** |

## Quick Decision Matrix

### If Your Clients Are:

**On GCP (same region):**
- ✅ Bandwidth: No issue (1 Gbps plenty)
- ✅ Cost: FREE egress
- ✅ Use: e2-small ($16/month total)

**On GCP (different region):**
- ✅ Bandwidth: No issue
- ⚠️ Cost: $0.01/GB egress (cheaper than internet)
- ✅ Use: e2-small + budget for egress

**Outside GCP (internet):**
- ✅ Bandwidth: No issue (up to 500 Mbps)
- ❌ Cost: $0.085/GB+ (can be expensive)
- ⚠️ Use: e2-small + compression + monitor costs

**High-volume outside GCP:**
- ⚠️ Bandwidth: May need 2+ Gbps (use e2-medium)
- ❌ Cost: Very expensive
- 💡 Consider: Moving clients to GCP or other solution

## Summary

### Network Bandwidth Capacity: ✅ NOT AN ISSUE
- e2-micro (1 Gbps): Handles up to 500 Mbps easy
- e2-small (1 Gbps): Handles up to 800 Mbps
- e2-medium (2 Gbps): Handles 1.5 Gbps+

**For 2 clients: Even e2-micro is MORE than enough**

### Egress Costs: ⚠️ DEPENDS ON YOUR SUBSCRIPTIONS

**If clients are on GCP (same region):**
- ✅ FREE egress - no worries!

**If clients are external:**
- Few symbols: ~$10-50/month - OK
- Many symbols: ~$100-500/month - expensive
- Wildcard: ~$500-2000/month - very expensive

### What You Should Do:

1. **Check your subscription volume:**
   - What symbols will you subscribe to?
   - How many messages/sec expected?

2. **If high volume + external clients:**
   - Enable compression (save 60-80%)
   - Consider moving clients to GCP
   - Monitor egress costs closely

3. **For low-medium volume:**
   - e2-small is perfect
   - Egress costs will be minimal
   - No special optimization needed

**Want me to calculate exact bandwidth for your specific use case?** Tell me:
- What symbols/types you'll subscribe to
- Where your clients are located (GCP/external)
