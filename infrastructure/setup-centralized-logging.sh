#!/bin/bash
# Setup Centralized Logging for GCP-Trader
# Installs Ops Agent on all VMs to send logs to Cloud Logging

set -e

PROJECT_ID="gnw-trader"
ZONE="us-east4-a"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔍 Setting up centralized logging for GCP-Trader${NC}"
echo ""
echo -e "${BLUE}Project:${NC} $PROJECT_ID"
echo -e "${BLUE}Zone:${NC} $ZONE"
echo ""

# Function to install Ops Agent on a VM
install_ops_agent() {
  local vm=$1

  echo -e "${BLUE}Installing Ops Agent on $vm...${NC}"

  gcloud compute ssh $vm --zone=$ZONE --project=$PROJECT_ID --command='
    set -e

    # Download and install Ops Agent
    echo "  → Downloading Ops Agent..."
    curl -sSO https://dl.google.com/cloudagent/add-google-cloud-ops-agent-repo.sh

    echo "  → Installing Ops Agent..."
    sudo bash add-google-cloud-ops-agent-repo.sh --also-install 2>&1 | grep -v "^Get:" || true

    # Create configuration
    echo "  → Configuring log collection..."
    sudo tee /etc/google-cloud-ops-agent/config.yaml > /dev/null << "EOF"
logging:
  receivers:
    # System logs
    syslog:
      type: files
      include_paths:
        - /var/log/syslog
        - /var/log/messages

    # Application logs in /var/log
    app_logs:
      type: files
      include_paths:
        - /var/log/*.log

    # Application logs in /opt
    opt_logs:
      type: files
      include_paths:
        - /opt/*/logs/*.log
        - /opt/*/*/logs/*.log

    # Systemd journal (all services)
    systemd:
      type: systemd_journald

  processors:
    # Add VM metadata to logs
    add_metadata:
      type: resource_metadata

  service:
    pipelines:
      default_pipeline:
        receivers: [syslog, app_logs, opt_logs, systemd]
        processors: [add_metadata]
EOF

    # Restart agent to apply config
    echo "  → Restarting Ops Agent..."
    sudo systemctl restart google-cloud-ops-agent

    # Verify it is running
    if sudo systemctl is-active --quiet google-cloud-ops-agent; then
      echo "  ✓ Ops Agent running"
    else
      echo "  ✗ Ops Agent failed to start"
      exit 1
    fi

    # Clean up
    rm -f add-google-cloud-ops-agent-repo.sh

  ' && echo -e "${GREEN}✓ $vm configured successfully${NC}" || echo -e "${YELLOW}✗ $vm failed - may already be configured${NC}"

  echo ""
}

# Install on all VMs
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Installing on polygon-proxy-standard...${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
install_ops_agent "polygon-proxy-standard"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Installing on news-trader...${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
install_ops_agent "news-trader"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Installing on benzinga-scraper...${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
install_ops_agent "benzinga-scraper"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Centralized logging setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}Logs will appear in Cloud Logging within 2-3 minutes.${NC}"
echo ""
echo -e "${BLUE}View logs:${NC}"
echo "  https://console.cloud.google.com/logs/query?project=$PROJECT_ID"
echo ""
echo -e "${BLUE}Example queries:${NC}"
echo ""
echo -e "${YELLOW}# All errors across all VMs${NC}"
echo '  severity >= ERROR'
echo ""
echo -e "${YELLOW}# Polygon proxy logs${NC}"
echo '  resource.labels.instance_id="polygon-proxy-standard"'
echo ""
echo -e "${YELLOW}# Trade execution logs${NC}"
echo '  jsonPayload.message=~"order placed"'
echo ""
echo -e "${YELLOW}# News trader logs${NC}"
echo '  resource.labels.instance_id="news-trader"'
echo ""
echo -e "${YELLOW}# Last hour of logs${NC}"
echo '  timestamp >= "'$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')'"'
echo ""
