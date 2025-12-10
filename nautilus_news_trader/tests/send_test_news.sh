#!/bin/bash
# Send test news to Pub/Sub using gcloud CLI
#
# Usage:
#   ./send_test_news.sh AAPL "TC1 Happy Path"
#   ./send_test_news.sh AAPL,MSFT "TC10 Multi"
#   ./send_test_news.sh "" "TC5 No Tickers"
#   ./send_test_news.sh AAPL "TC6 Too Old" 15
#   ./send_test_news.sh AAPL "TC7 Too Fresh" 1

set -e

PROJECT_ID="gnw-trader"
TOPIC_ID="benzinga-news"

TICKERS=${1:-"AAPL"}
TEST_NAME=${2:-"E2E Test"}
AGE_SECONDS=${3:-5}

# Generate unique ID
TEST_ID="test_$(date +%s%N | cut -c1-13)"

# Calculate timestamps
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    CREATED_AT=$(date -u -v-${AGE_SECONDS}S +"%Y-%m-%dT%H:%M:%SZ")
else
    # Linux
    CREATED_AT=$(date -u -d "-${AGE_SECONDS} seconds" +"%Y-%m-%dT%H:%M:%SZ")
fi

# Build tickers array
if [ -z "$TICKERS" ]; then
    TICKERS_JSON="[]"
    HEADLINE="[TEST] ${TEST_NAME} - No tickers"
else
    # Convert comma-separated to JSON array
    TICKERS_JSON=$(echo "$TICKERS" | sed 's/,/","/g' | sed 's/^/["/' | sed 's/$/"]/')
    HEADLINE="[TEST] ${TEST_NAME} for ${TICKERS}"
fi

# Build JSON payload
JSON_PAYLOAD=$(cat <<EOF
{
  "id": "${TEST_ID}",
  "storyId": "${TEST_ID}",
  "nodeId": 99999999,
  "headline": "${HEADLINE}",
  "teaserText": "Test news for E2E testing - ${TEST_NAME}",
  "body": "This is a test news article. Test ID: ${TEST_ID}",
  "author": "Test Bot",
  "createdAt": "${CREATED_AT}",
  "updatedAt": "${CREATED_AT}",
  "tickers": ${TICKERS_JSON},
  "quotes": [],
  "source": "Test",
  "sourceGroup": "test",
  "sourceFull": "Test Bot",
  "channels": ["test"],
  "tags": ["test"],
  "sentiment": "neutral",
  "isBzPost": false,
  "isBzProPost": false,
  "partnerURL": "",
  "eventId": null,
  "capturedAt": "${NOW}"
}
EOF
)

# Publish to Pub/Sub
echo ""
echo "============================================================"
echo "  TEST NEWS PUBLISHING"
echo "============================================================"
echo "Test Name:    ${TEST_NAME}"
echo "Test ID:      ${TEST_ID}"
echo "Tickers:      ${TICKERS:-None}"
echo "Headline:     ${HEADLINE}"
echo "Age:          ${AGE_SECONDS}s (created at ${CREATED_AT})"
echo "Published at: ${NOW}"
echo "============================================================"

# Publish
gcloud pubsub topics publish ${TOPIC_ID} \
    --project=${PROJECT_ID} \
    --message="${JSON_PAYLOAD}"

echo ""
echo "Expected behavior:"
if [ -z "$TICKERS" ]; then
    echo "  - News should be SKIPPED (no tickers)"
elif [ "$AGE_SECONDS" -lt 2 ]; then
    echo "  - News should be SKIPPED (too fresh: ${AGE_SECONDS}s < 2s)"
elif [ "$AGE_SECONDS" -gt 10 ]; then
    echo "  - News should be SKIPPED (too old: ${AGE_SECONDS}s > 10s)"
else
    echo "  - Strategy should SPAWN for each ticker"
    echo "  - BUY order should be placed (mock volume data)"
    echo "  - Exit timer scheduled (2 min)"
    echo "  - SELL order after timeout"
fi

echo ""
echo "Monitor with:"
echo "  gcloud logging read 'jsonPayload.message=~\"${TEST_ID:0:20}|${TICKERS%%,*}\"' --project=${PROJECT_ID} --limit=30 --format='table(timestamp,jsonPayload.message)'"
