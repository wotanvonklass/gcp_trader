#!/bin/bash

# View Benzinga Scraper Logs from Cloud Logging
PROJECT_ID="gnw-trader"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}📋 Benzinga Scraper Logs${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

FILTER=""
LIMIT=50

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --news)
            FILTER='textPayload:"NEWS"'
            echo -e "${YELLOW}Filtering for news items only${NC}"
            echo ""
            shift
            ;;
        --errors)
            FILTER='severity>=ERROR'
            echo -e "${YELLOW}Filtering for errors only${NC}"
            echo ""
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --tail|-f)
            echo -e "${YELLOW}Tailing logs (Press Ctrl+C to stop)${NC}"
            echo ""
            gcloud logging tail --project=$PROJECT_ID \
                --format="table(timestamp,severity,textPayload)" 2>/dev/null
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build the query
QUERY='resource.type="gce_instance"'
if [ ! -z "$FILTER" ]; then
    QUERY="$QUERY AND $FILTER"
fi

echo "Fetching last $LIMIT log entries..."
echo ""

gcloud logging read "$QUERY" \
    --project=$PROJECT_ID \
    --limit=$LIMIT \
    --format="table(timestamp,severity,textPayload)" \
    2>/dev/null

echo ""
echo -e "${BLUE}Usage:${NC}"
echo "  $0              - View last 50 logs"
echo "  $0 --news       - View only news-related logs"
echo "  $0 --errors     - View only errors"
echo "  $0 --limit 100  - View last 100 logs"
echo "  $0 --tail       - Tail logs in real-time"
echo ""
