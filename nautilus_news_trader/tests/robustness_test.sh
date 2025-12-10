#!/bin/bash
# Robustness Test: Inject news for top movers every 8 minutes
#
# Fetches top 10 stocks from localhost API (breaking_news) and publishes
# test news to GCP Pub/Sub for the news trading system.
#
# Usage:
#   ./robustness_test.sh           # Run 10 iterations, 8 min delay
#   ./robustness_test.sh 5         # Run 5 iterations
#   ./robustness_test.sh 3 120     # 3 iterations, 2 minute delay

set -e

PROJECT_ID="gnw-trader"
TOPIC_ID="benzinga-news"
API_URL="http://localhost:8001/api/v1/stocks"

ITERATIONS=${1:-10}
DELAY_SECONDS=${2:-480}  # 8 minutes default

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  ROBUSTNESS TEST - News Injection for Top Movers${NC}"
echo -e "${GREEN}============================================================${NC}"
echo -e "API URL: ${API_URL}"
echo -e "Iterations: ${ITERATIONS}"
echo -e "Delay between rounds: ${DELAY_SECONDS}s ($((DELAY_SECONDS / 60)) minutes)"
echo -e "${GREEN}============================================================${NC}"
echo ""

get_top_movers() {
    # Get top movers from localhost API (breaking_news)
    curl -s "${API_URL}?sort=change_percent&volume_min=1000000&order=desc&limit=10" | \
        python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    stocks = data.get('data', [])[:10]
    for s in stocks:
        ticker = s.get('ticker', '')
        change_pct = s.get('today_change_percent', 0)
        volume = int(s.get('last_volume', 0))
        price = s.get('last_price', 0)
        name = s.get('name', ticker)
        if ticker and volume >= 1000000:
            print(f'{ticker},{change_pct:.2f},{volume},{price:.2f},{name}')
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
" 2>/dev/null || echo ""
}

publish_news() {
    local ticker=$1
    local change_pct=$2
    local price=$3
    local test_round=$4
    local company_name=$5

    local test_id="robustness_${test_round}_$(date +%s%N | cut -c1-13)"
    local now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    # Calculate created_at (5 seconds ago for proper age)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        local created_at=$(date -u -v-5S +"%Y-%m-%dT%H:%M:%SZ")
    else
        local created_at=$(date -u -d "-5 seconds" +"%Y-%m-%dT%H:%M:%SZ")
    fi

    local direction="surges"
    if (( $(echo "$change_pct < 0" | bc -l) )); then
        direction="drops"
    fi

    local headline="[ROBUSTNESS] Round ${test_round} - ${ticker} ${direction} ${change_pct}% - ${company_name}"

    local json_payload=$(cat <<EOF
{
  "id": "${test_id}",
  "storyId": "${test_id}",
  "nodeId": 99999999,
  "headline": "${headline}",
  "teaserText": "${company_name} (${ticker}) ${direction} ${change_pct}% on high volume",
  "body": "Robustness test news article for ${ticker}. Test ID: ${test_id}",
  "author": "Robustness Bot",
  "createdAt": "${created_at}",
  "updatedAt": "${created_at}",
  "tickers": ["${ticker}"],
  "quotes": [],
  "source": "Test",
  "sourceGroup": "test",
  "sourceFull": "Robustness Bot",
  "channels": ["test"],
  "tags": ["robustness", "momentum"],
  "sentiment": "positive",
  "isBzPost": false,
  "isBzProPost": false,
  "partnerURL": "",
  "eventId": null,
  "capturedAt": "${now}"
}
EOF
)

    gcloud pubsub topics publish ${TOPIC_ID} \
        --project=${PROJECT_ID} \
        --message="${json_payload}" 2>/dev/null

    echo -e "  ${GREEN}✓${NC} ${ticker}: ${change_pct}% @ \$${price}"
}

for ((round=1; round<=ITERATIONS; round++)); do
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  ROUND ${round}/${ITERATIONS} - $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    echo -e "\nFetching top movers from localhost API..."
    movers=$(get_top_movers)

    if [ -z "$movers" ]; then
        echo -e "${RED}  No stocks found from API. Check if breaking_news is running.${NC}"
        echo -e "${YELLOW}  Skipping this round...${NC}"
        if [ $round -lt $ITERATIONS ]; then
            echo -e "${YELLOW}Waiting ${DELAY_SECONDS}s before next round...${NC}"
            sleep $DELAY_SECONDS
        fi
        continue
    fi

    echo -e "\nPublishing news for top movers:"
    count=0
    while IFS=',' read -r ticker change_pct volume price name; do
        if [ -n "$ticker" ] && [ $count -lt 10 ]; then
            publish_news "$ticker" "$change_pct" "$price" "$round" "$name"
            ((count++))
            sleep 0.5  # Small delay between publishes
        fi
    done <<< "$movers"

    echo -e "\n${GREEN}Published ${count} news items for round ${round}${NC}"

    # Show recent logs
    echo -e "\nRecent activity (wait 10s)..."
    sleep 10
    gcloud logging read 'jsonPayload.message=~"ROBUSTNESS|Round '"${round}"'"' \
        --project=$PROJECT_ID --limit=20 \
        --format='table(timestamp,jsonPayload.message)' 2>/dev/null | head -25

    if [ $round -lt $ITERATIONS ]; then
        echo ""
        echo -e "${YELLOW}Waiting ${DELAY_SECONDS}s ($((DELAY_SECONDS / 60)) minutes) before next round...${NC}"
        next_time=$(date -v+${DELAY_SECONDS}S '+%H:%M:%S' 2>/dev/null || date -d "+${DELAY_SECONDS} seconds" '+%H:%M:%S' 2>/dev/null || echo "soon")
        echo -e "Next round at: ${next_time}"
        sleep $DELAY_SECONDS
    fi
done

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  ROBUSTNESS TEST COMPLETE${NC}"
echo -e "${GREEN}============================================================${NC}"
echo -e "Total rounds: ${ITERATIONS}"
echo -e "Check logs with:"
echo -e "  gcloud logging read 'jsonPayload.message=~\"ROBUSTNESS\"' --project=$PROJECT_ID --limit=100"
