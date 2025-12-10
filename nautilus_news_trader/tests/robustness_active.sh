#!/bin/bash
# Robustness Test with Active Tickers
#
# Uses a predefined list of high-activity tickers instead of API
#
# Usage:
#   ./robustness_active.sh           # Run 10 iterations, 8 min delay
#   ./robustness_active.sh 5         # Run 5 iterations
#   ./robustness_active.sh 3 120     # 3 iterations, 2 minute delay

set -e

PROJECT_ID="gnw-trader"
TOPIC_ID="benzinga-news"

# Active tickers from screenshot - high volume, should have trading activity
TICKERS=(
    "KTTA:Pasithea Therapeutics Corp."
    "BFLY:Butterfly Network, Inc."
    "CIFR:Cipher Mining Inc."
    "BBAI:BigBear.ai, Inc."
    "OPEN:Opendoor Technologies Inc"
    "QBTS:D-Wave Quantum Inc."
    "STUB:StubHub Holdings, Inc."
    "BTG:B2Gold Corp"
    "SMR:NuScale Power Corporation"
    "EQX:Equinox Gold Corp."
    "GRAB:Grab Holdings Limited"
    "CLF:Cleveland-Cliffs Inc."
    "SOUN:SoundHound AI, Inc."
    "TDOC:Teladoc Health, Inc."
    "RKT:Rocket Companies, Inc."
    "AEO:American Eagle Outfitters, Inc."
    "HPE:Hewlett Packard Enterprise Company"
    "LAC:Lithium Americas Corp."
)

ITERATIONS=${1:-10}
DELAY_SECONDS=${2:-480}  # 8 minutes default

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  ROBUSTNESS TEST - Active Tickers${NC}"
echo -e "${GREEN}============================================================${NC}"
echo -e "Tickers: ${#TICKERS[@]} active stocks"
echo -e "Iterations: ${ITERATIONS}"
echo -e "Delay between rounds: ${DELAY_SECONDS}s ($((DELAY_SECONDS / 60)) minutes)"
echo -e "${GREEN}============================================================${NC}"
echo ""

publish_news() {
    local ticker=$1
    local company_name=$2
    local test_round=$3

    local test_id="robustness_${test_round}_$(date +%s%N | cut -c1-13)"
    local now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    # Set created_at 1s ago so Pub/Sub latency (~1.7s) brings total age to ~2.7s
    if [[ "$OSTYPE" == "darwin"* ]]; then
        local created_at=$(date -u -v-1S +"%Y-%m-%dT%H:%M:%SZ")
    else
        local created_at=$(date -u -d "-1 second" +"%Y-%m-%dT%H:%M:%SZ")
    fi

    local headline="[ROBUSTNESS] Round ${test_round} - ${ticker} momentum signal - ${company_name}"

    local json_payload=$(cat <<EOF
{
  "id": "${test_id}",
  "storyId": "${test_id}",
  "nodeId": 99999999,
  "headline": "${headline}",
  "teaserText": "${company_name} (${ticker}) showing momentum",
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

    echo -e "  ${GREEN}✓${NC} ${ticker}: ${company_name}"
}

for ((round=1; round<=ITERATIONS; round++)); do
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  ROUND ${round}/${ITERATIONS} - $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    echo -e "\nPublishing news for active tickers:"
    count=0
    for entry in "${TICKERS[@]}"; do
        ticker="${entry%%:*}"
        name="${entry#*:}"
        if [ $count -lt 10 ]; then
            publish_news "$ticker" "$name" "$round" &
            ((count++))
        fi
    done
    wait  # Wait for all background publishes to complete

    echo -e "\n${GREEN}Published ${count} news items for round ${round}${NC}"

    # Show recent logs
    echo -e "\nRecent activity (wait 10s)..."
    sleep 10
    gcloud logging read 'jsonPayload.message=~"ROBUSTNESS|Round '\"${round}\"'|Spawning|BUY"' \
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
