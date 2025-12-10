# Centralized Logging - GCP Cloud Logging

## ✅ Implementation Complete!

All VMs now send logs to GCP Cloud Logging automatically.

---

## What Was Installed

### Ops Agent on All VMs:
- ✅ **polygon-proxy-standard** - Ops Agent running
- ✅ **news-trader** - Ops Agent running
- ✅ **benzinga-scraper** - Ops Agent running

### What Logs Are Collected:
- System logs (`/var/log/syslog`)
- Application logs (`/var/log/*.log`)
- Application logs in `/opt` (`/opt/*/logs/*.log`)
- Systemd journal (all services)
- VM metadata attached to each log entry

---

## View Logs (Console - Easiest)

**Main URL:**
```
https://console.cloud.google.com/logs/query?project=gnw-trader
```

### Example Queries:

**All errors across all VMs:**
```
severity >= ERROR
```

**Polygon proxy logs:**
```
resource.labels.instance_id="polygon-proxy-standard"
```

**News trader logs:**
```
resource.labels.instance_id="news-trader"
```

**Benzinga scraper logs:**
```
resource.labels.instance_id="benzinga-scraper"
```

**Trade execution logs:**
```
jsonPayload.message=~"order placed"
```

**Last hour only:**
```
timestamp >= "2025-11-23T08:00:00Z"
```

**Specific service logs:**
```
resource.labels.instance_id="polygon-proxy-standard"
AND jsonPayload.message=~"firehose-proxy"
```

**Combine filters:**
```
resource.labels.instance_id="news-trader"
AND severity >= WARNING
AND timestamp >= "2025-11-23T00:00:00Z"
```

---

## View Logs (CLI)

### Recent logs from all VMs:
```bash
gcloud logging read "resource.type=gce_instance" \
  --limit=50 \
  --project=gnw-trader \
  --format="table(timestamp,resource.labels.instance_id,severity,textPayload)"
```

### Polygon proxy logs only:
```bash
gcloud logging read 'resource.labels.instance_id="polygon-proxy-standard"' \
  --limit=100 \
  --project=gnw-trader \
  --freshness=1h
```

### Errors only:
```bash
gcloud logging read 'severity >= ERROR' \
  --limit=50 \
  --project=gnw-trader \
  --freshness=1h \
  --format="table(timestamp,resource.labels.instance_id,textPayload)"
```

### Tail logs in real-time:
```bash
gcloud logging tail "resource.type=gce_instance" \
  --project=gnw-trader
```

---

## Configuration Files

### Location on VMs:
```
/etc/google-cloud-ops-agent/config.yaml
```

### Current Config:
```yaml
logging:
  receivers:
    syslog:
      type: files
      include_paths:
        - /var/log/syslog
        - /var/log/*.log
    systemd:
      type: systemd_journald
  service:
    pipelines:
      default_pipeline:
        receivers: [syslog, systemd]
```

### Add More Logs:

SSH into VM and edit config:
```bash
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader

sudo nano /etc/google-cloud-ops-agent/config.yaml
```

Add to `include_paths`:
```yaml
- /opt/myapp/logs/*.log
- /var/log/custom/*.log
```

Restart agent:
```bash
sudo systemctl restart google-cloud-ops-agent
```

---

## Cost

**Current Usage:**
- 3 VMs sending logs
- Estimated: ~5-10 GB/month

**Pricing:**
- First 50 GB/month: **FREE** ✅
- After 50 GB: $0.50/GB

**Your cost: $0/month** (within free tier)

---

## Useful Features

### 1. Save Queries

In the Cloud Logging console:
1. Create a query
2. Click "Save Query"
3. Give it a name ("Polygon Errors", "Trade Logs", etc.)
4. Access from sidebar

### 2. Create Log-Based Metrics

Track specific events:
```bash
# Count trade executions
gcloud logging metrics create trade_count \
  --description="Number of trades executed" \
  --log-filter='jsonPayload.message=~"order placed"' \
  --project=gnw-trader

# Count errors per VM
gcloud logging metrics create error_rate \
  --description="Error rate by VM" \
  --log-filter='severity >= ERROR' \
  --project=gnw-trader
```

View metrics:
```
https://console.cloud.google.com/logs/metrics?project=gnw-trader
```

### 3. Export to BigQuery (Optional)

For SQL analytics on logs:
```bash
# Create dataset
bq mk --dataset --location=US gnw-trader:logs

# Create export sink
gcloud logging sinks create logs-to-bigquery \
  bigquery.googleapis.com/projects/gnw-trader/datasets/logs \
  --log-filter='resource.type="gce_instance"' \
  --project=gnw-trader
```

Then query in BigQuery:
```sql
SELECT
  timestamp,
  resource.labels.instance_id as vm,
  severity,
  textPayload
FROM `gnw-trader.logs.syslog_*`
WHERE severity = 'ERROR'
ORDER BY timestamp DESC
LIMIT 100
```

### 4. Set Up Alerts

Alert on high error rate:
```bash
# Get notification channel
CHANNEL_ID=$(gcloud alpha monitoring channels list \
  --project=gnw-trader \
  --filter="labels.email_address='v.onklass@gmail.com'" \
  --format="value(name)" | head -1)

# Create alert policy
gcloud alpha monitoring policies create \
  --notification-channels=$CHANNEL_ID \
  --display-name="High Error Rate" \
  --condition-display-name="More than 10 errors in 5 min" \
  --project=gnw-trader
```

---

## Troubleshooting

### Logs not appearing?

**1. Check Ops Agent is running:**
```bash
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo systemctl status google-cloud-ops-agent'
```

**2. Check configuration:**
```bash
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='cat /etc/google-cloud-ops-agent/config.yaml'
```

**3. Restart agent:**
```bash
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo systemctl restart google-cloud-ops-agent'
```

**4. Check agent logs:**
```bash
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo journalctl -u google-cloud-ops-agent -n 50'
```

**5. Verify permissions:**
Ops Agent needs `roles/logging.logWriter` - should be automatic with Compute Engine default service account.

### Logs taking too long to appear?

- Initial delay: 1-2 minutes normal
- After config change: Restart agent
- Check system time is correct on VM

---

## Common Use Cases

### 1. Debug a Service Crash

```
resource.labels.instance_id="polygon-proxy-standard"
AND (textPayload=~"error" OR severity >= ERROR)
AND timestamp >= "2025-11-23T08:00:00Z"
```

### 2. Monitor Trade Activity

```
resource.labels.instance_id="news-trader"
AND jsonPayload.message=~"BUY order placed|SELL order placed"
```

### 3. Check Service Restarts

```
resource.type="gce_instance"
AND jsonPayload.message=~"Started|Stopped"
```

### 4. Find Polygon Proxy Issues

```
resource.labels.instance_id="polygon-proxy-standard"
AND (
  jsonPayload.message=~"firehose-proxy" OR
  jsonPayload.message=~"ms-aggregator" OR
  jsonPayload.message=~"filtered-proxy"
)
```

---

## Comparison: Before vs After

### Before (SSH to each VM):
```bash
# Check polygon logs
gcloud compute ssh polygon-proxy-standard --command='tail -100 /var/log/polygon-monitor.log'

# Check news trader logs
gcloud compute ssh news-trader --command='tail -100 /opt/news-trader/logs/trader.log'

# Check benzinga logs
gcloud compute ssh benzinga-scraper --command='journalctl -u benzinga-scraper -n 100'
```

### After (Single dashboard):
1. Open: https://console.cloud.google.com/logs?project=gnw-trader
2. Select VM from dropdown
3. Select time range
4. Filter by service/severity
5. Done! 🎉

---

## Next Steps (Optional)

1. ✅ **Logs are centralized** - Working now
2. ⏭️ **Create saved queries** for common searches
3. ⏭️ **Set up error alerts** (email when >10 errors/5min)
4. ⏭️ **Export to BigQuery** for analytics
5. ⏭️ **Create dashboard** in Logs Explorer

---

## Documentation

**GCP Cloud Logging:**
https://cloud.google.com/logging/docs

**Ops Agent:**
https://cloud.google.com/logging/docs/agent/ops-agent

**Query Syntax:**
https://cloud.google.com/logging/docs/view/logging-query-language

---

## Support

**View in Console:**
https://console.cloud.google.com/logs/query?project=gnw-trader

**Logs retention:** 30 days (free)
**Cost:** $0/month (within free tier)
**Notification email:** v.onklass@gmail.com
