# GCP Monitoring & Alerting Guide for Polygon Proxy

## Current Monitoring Setup

### Local Health Monitor (Deployed ✅)

The `monitor.py` script is running as a systemd service on the VM:

**What it monitors:**
- Market status (checks if markets are open)
- TSLA trade flow every 5 minutes when markets are open
- ms-aggregator health (verifying bar production)

**Logs:**
- Main log: `/var/log/polygon-monitor.log`
- Alerts: `/var/log/polygon-alerts.log`

**Status:**
```bash
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo systemctl status polygon-monitor'
```

**View logs:**
```bash
# Real-time monitoring
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo tail -f /var/log/polygon-monitor.log'

# View alerts
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo cat /var/log/polygon-alerts.log'
```

---

## GCP Cloud Monitoring Integration

### 1. VM Monitoring (Free Tier)

GCP provides automatic VM metrics without additional setup:

**Available Metrics:**
- CPU utilization
- Disk I/O
- Network traffic
- Memory usage (requires Ops Agent)

**View in Console:**
```
https://console.cloud.google.com/monitoring/dashboards
```

### 2. Install Cloud Ops Agent (Recommended)

The Ops Agent collects logs and metrics for Cloud Monitoring:

```bash
# Install on the VM
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader --command='
curl -sSO https://dl.google.com/cloudagent/add-google-cloud-ops-agent-repo.sh
sudo bash add-google-cloud-ops-agent-repo.sh --also-install
'
```

**Configure log collection:**
```bash
# SSH into VM
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader

# Edit config
sudo nano /etc/google-cloud-ops-agent/config.yaml
```

Add this configuration:
```yaml
logging:
  receivers:
    polygon_monitor:
      type: files
      include_paths:
        - /var/log/polygon-monitor.log
    polygon_alerts:
      type: files
      include_paths:
        - /var/log/polygon-alerts.log
    firehose_logs:
      type: systemd_journald
      units:
        - firehose-proxy.service
        - ms-aggregator.service
        - filtered-proxy.service
        - polygon-monitor.service

  service:
    pipelines:
      default_pipeline:
        receivers:
          - polygon_monitor
          - polygon_alerts
          - firehose_logs
```

Restart the agent:
```bash
sudo systemctl restart google-cloud-ops-agent
```

### 3. Create Alerting Policies

#### Alert on Service Failures

```bash
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Polygon Proxy Service Down" \
  --condition-display-name="Service not running" \
  --condition-threshold-value=0 \
  --condition-threshold-duration=300s \
  --condition-filter='
    resource.type="gce_instance" AND
    resource.labels.instance_id="INSTANCE_ID" AND
    metric.type="agent.googleapis.com/processes/count_by_state" AND
    metric.labels.process_name="firehose_proxy"'
```

#### Alert on High CPU

```bash
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Polygon Proxy High CPU" \
  --condition-display-name="CPU above 80%" \
  --condition-threshold-value=0.8 \
  --condition-threshold-duration=300s \
  --condition-filter='
    resource.type="gce_instance" AND
    resource.labels.instance_id="INSTANCE_ID" AND
    metric.type="compute.googleapis.com/instance/cpu/utilization"'
```

#### Alert on TSLA Trade Flow Issues

Since our monitor writes to `/var/log/polygon-alerts.log`, we can alert on new entries:

```bash
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Polygon Proxy Alert Triggered" \
  --condition-display-name="Alert log has entries" \
  --condition-filter='
    resource.type="gce_instance" AND
    log_name="projects/gnw-trader/logs/polygon-alerts"'
```

### 4. Notification Channels

#### Email Notifications (Free)

```bash
gcloud alpha monitoring channels create \
  --display-name="Email Alert" \
  --type=email \
  --channel-labels=email_address=your-email@example.com
```

#### Slack Integration

1. Create a Slack webhook at https://api.slack.com/messaging/webhooks
2. Create channel:
```bash
gcloud alpha monitoring channels create \
  --display-name="Slack Alert" \
  --type=slack \
  --channel-labels=url=YOUR_WEBHOOK_URL
```

#### SMS via Twilio (requires setup)

```bash
gcloud alpha monitoring channels create \
  --display-name="SMS Alert" \
  --type=sms \
  --channel-labels=phone_number=+1234567890
```

### 5. Custom Metrics (Advanced)

For more granular monitoring, send custom metrics from monitor.py:

```python
from google.cloud import monitoring_v3
import time

def send_custom_metric(value, metric_type):
    """Send custom metric to Cloud Monitoring"""
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/gnw-trader"

    series = monitoring_v3.TimeSeries()
    series.metric.type = f"custom.googleapis.com/polygon_proxy/{metric_type}"
    series.resource.type = "gce_instance"

    point = monitoring_v3.Point()
    point.value.double_value = value
    point.interval.end_time.seconds = int(time.time())

    series.points = [point]
    client.create_time_series(name=project_name, time_series=[series])

# Example usage in monitor.py:
# send_custom_metric(1.0, "tsla_trades_healthy")
# send_custom_metric(0.0, "tsla_trades_failing")
```

### 6. Uptime Checks

Monitor WebSocket endpoint availability:

```bash
gcloud monitoring uptime create ws-endpoint \
  --display-name="Polygon Proxy WebSocket" \
  --resource-type=uptime-url \
  --host=136.107.56.54 \
  --port=8765
```

**Note:** Uptime checks don't support WebSocket protocol directly, so you may need a custom HTTP health endpoint.

---

## Cost Optimization

### Free Tier Limits (as of 2024):
- **Logs ingestion:** First 50 GB/month free
- **Metrics ingestion:** First 150 MB/month free
- **Monitoring API calls:** First 1M calls/month free
- **Alerting:** Unlimited free email notifications
- **Uptime checks:** First 1M checks/month free

### Estimated Costs:
With current setup:
- Logs: ~1-2 GB/month (under free tier)
- Metrics: Minimal (under free tier)
- **Total monitoring cost: $0/month**

---

## Recommended Setup (Step-by-Step)

1. **Install Ops Agent** (5 min)
   ```bash
   gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader --command='
   curl -sSO https://dl.google.com/cloudagent/add-google-cloud-ops-agent-repo.sh
   sudo bash add-google-cloud-ops-agent-repo.sh --also-install
   '
   ```

2. **Create Email Notification Channel** (2 min)
   ```bash
   gcloud alpha monitoring channels create \
     --display-name="Polygon Alerts" \
     --type=email \
     --channel-labels=email_address=your-email@example.com \
     --project=gnw-trader
   ```

   Save the channel ID from the output.

3. **Create Alert for Service Failures** (3 min)
   ```bash
   # Get instance ID
   INSTANCE_ID=$(gcloud compute instances describe polygon-proxy-standard \
     --zone=us-east4-a --project=gnw-trader \
     --format='get(id)')

   # Create alert (replace CHANNEL_ID)
   gcloud alpha monitoring policies create \
     --notification-channels=CHANNEL_ID \
     --display-name="Polygon Service Down" \
     --project=gnw-trader
   ```

4. **View Dashboard** (1 min)
   - Visit: https://console.cloud.google.com/monitoring
   - Select project: gnw-trader
   - Create custom dashboard for polygon-proxy-standard VM

5. **Test Alerting**
   ```bash
   # Stop a service to test alerting
   gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
     --command='sudo systemctl stop firehose-proxy'

   # Wait for alert (usually 5-10 minutes)
   # Then restart
   gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
     --command='sudo systemctl start firehose-proxy'
   ```

---

## Monitoring Best Practices

1. **Log Retention:** Adjust in Cloud Logging settings
   - Default: 30 days
   - Recommendation: 90 days for production

2. **Alert Fatigue:** Start with critical alerts only
   - Service down
   - No TSLA trades during market hours
   - VM stopped/terminated

3. **Escalation:** Set up multiple notification channels
   - Email for non-critical
   - SMS/Slack for critical

4. **Regular Review:** Check alerts weekly
   - False positives → adjust thresholds
   - Missed issues → add new alerts

5. **Cost Monitoring:** Set up budget alerts
   ```bash
   gcloud billing budgets create \
     --billing-account=BILLING_ACCOUNT_ID \
     --display-name="Polygon Proxy Budget" \
     --budget-amount=50 \
     --threshold-rule=percent=80
   ```

---

## Troubleshooting Commands

```bash
# Check all services
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo systemctl status firehose-proxy ms-aggregator filtered-proxy polygon-monitor'

# View monitor logs
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo tail -100 /var/log/polygon-monitor.log'

# Check for alerts
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo tail -100 /var/log/polygon-alerts.log'

# Check service logs
gcloud compute ssh polygon-proxy-standard --zone=us-east4-a --project=gnw-trader \
  --command='sudo journalctl -u firehose-proxy -n 50'

# Check VM metrics
gcloud compute instances describe polygon-proxy-standard \
  --zone=us-east4-a --project=gnw-trader
```

---

## External Monitoring Services (Optional)

### 1. **UptimeRobot** (Free tier: 50 monitors)
   - Monitors WebSocket connectivity from external locations
   - Free email/SMS alerts
   - https://uptimerobot.com

### 2. **Better Uptime** (Free tier: 10 monitors)
   - Advanced uptime monitoring
   - Status pages
   - https://betteruptime.com

### 3. **Datadog** (Free trial, then $15/host/month)
   - Comprehensive monitoring
   - Custom dashboards
   - APM integration

---

## Next Steps

1. ✅ **Local monitoring is deployed and running**
2. ⏭️  **Install Cloud Ops Agent** for centralized logging
3. ⏭️  **Set up email notification channel**
4. ⏭️  **Create alerting policy for service failures**
5. ⏭️  **Test alerts during next market session**

For questions or issues, check:
- Monitor logs: `/var/log/polygon-monitor.log`
- Alert logs: `/var/log/polygon-alerts.log`
- Service status: `sudo systemctl status polygon-monitor`
