#!/bin/bash

# Monitor Benzinga News from Pub/Sub
# This script pulls and displays news messages from the Pub/Sub subscription

PROJECT_ID="gnw-trader"
SUBSCRIPTION="benzinga-news-monitor"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}📰 Benzinga News Monitor${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ "$1" == "--continuous" ] || [ "$1" == "-c" ]; then
    echo -e "${YELLOW}Continuous mode - Press Ctrl+C to stop${NC}"
    echo ""

    while true; do
        # Pull messages without auto-ack
        MESSAGES=$(gcloud pubsub subscriptions pull $SUBSCRIPTION \
            --project=$PROJECT_ID \
            --limit=5 \
            --format=json 2>/dev/null)

        if [ ! -z "$MESSAGES" ] && [ "$MESSAGES" != "[]" ]; then
            echo "$MESSAGES" | jq -r '.[] |
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 \(.message.data | @base64d | fromjson | .headline)
🏷️  Tickers: \(.message.data | @base64d | fromjson | .tickers | join(", "))
📡 Source: \(.message.data | @base64d | fromjson | .source)
⏰ Time: \(.message.data | @base64d | fromjson | .capturedAt)
🆔 ID: \(.message.data | @base64d | fromjson | .id)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"'
        else
            echo -e "${BLUE}[$(date +%H:%M:%S)] No new messages...${NC}"
        fi

        sleep 5
    done
else
    # Single pull
    LIMIT=${1:-10}
    echo -e "Pulling last ${LIMIT} messages..."
    echo ""

    gcloud pubsub subscriptions pull $SUBSCRIPTION \
        --project=$PROJECT_ID \
        --limit=$LIMIT \
        --format=json 2>/dev/null | jq -r '.[] |
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 \(.message.data | @base64d | fromjson | .headline)
🏷️  Tickers: \(.message.data | @base64d | fromjson | .tickers | join(", "))
📡 Source: \(.message.data | @base64d | fromjson | .source)
⏰ Time: \(.message.data | @base64d | fromjson | .capturedAt)
🆔 ID: \(.message.data | @base64d | fromjson | .id)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"'
fi

echo ""
echo -e "${BLUE}Usage:${NC}"
echo "  $0           - Pull last 10 messages"
echo "  $0 20        - Pull last 20 messages"
echo "  $0 -c        - Continuous monitoring mode"
echo ""
