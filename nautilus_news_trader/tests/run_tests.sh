#!/bin/bash
# E2E Test Runner for NewsVolumeStrategy
# Usage: ./run_tests.sh [test_number]
#
# Examples:
#   ./run_tests.sh 1      # Run TC1 only
#   ./run_tests.sh        # Run all tests (interactive)

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_ID="gnw-trader"
VM_NAME="news-trader"
ZONE="us-east4-a"

# Change to script directory
cd "$(dirname "$0")"

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  News Trading Strategy E2E Tests    ${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check service status
if gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='systemctl is-active news-trader' 2>/dev/null | grep -q "active"; then
    echo -e "  ${GREEN}✓${NC} news-trader service is running"
else
    echo -e "  ${RED}✗${NC} news-trader service is NOT running"
    exit 1
fi

# Check exit delay
EXIT_DELAY=$(gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='grep EXIT_DELAY_MINUTES /opt/news-trader/.env' 2>/dev/null | cut -d'=' -f2)
echo -e "  ${GREEN}✓${NC} Exit delay: ${EXIT_DELAY} minutes"

echo ""

# Function to run a test and wait for logs
run_test() {
    local test_num=$1
    local test_name=$2
    local ticker=$3
    local extra_args=$4

    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  TC${test_num}: ${test_name}${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # Send test news
    python3 send_test_news.py --ticker "$ticker" --test-name "TC${test_num} ${test_name}" $extra_args

    echo ""
    echo "Waiting for logs (5s)..."
    sleep 5

    # Show recent logs
    echo ""
    echo "Recent logs:"
    gcloud logging read "resource.type=\"gce_instance\" AND labels.\"compute.googleapis.com/resource_name\"=\"news-trader\" AND jsonPayload.message=~\"TC${test_num}|${ticker}\"" \
        --project=$PROJECT_ID --limit=15 --format="table(timestamp,jsonPayload.message)" 2>/dev/null | head -20

    echo ""
}

# Function to restart service
restart_service() {
    echo "Restarting news-trader service..."
    gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT_ID --command='sudo systemctl restart news-trader' 2>/dev/null
    echo "Waiting for restart (5s)..."
    sleep 5
}

# Test selection
TEST_NUM=${1:-""}

case $TEST_NUM in
    1)
        echo -e "${GREEN}Running TC1: Happy Path${NC}"
        run_test 1 "Happy Path" "AAPL"
        echo ""
        echo -e "${YELLOW}Wait 2+ minutes for exit timer, then check:${NC}"
        echo "  gcloud logging read 'jsonPayload.message=~\"AAPL.*SELL|Exit timer\"' --project=$PROJECT_ID --limit=20"
        ;;
    2)
        echo -e "${GREEN}Running TC2: Restart with Open Position${NC}"
        run_test 2 "Restart Test" "SPY"
        echo ""
        echo "Waiting 30s before restart..."
        sleep 30
        restart_service
        echo ""
        echo "Checking for exit order on stop:"
        sleep 5
        gcloud logging read 'jsonPayload.message=~"on_stop|EXIT ON STOP|SPY"' --project=$PROJECT_ID --limit=20 --format="table(timestamp,jsonPayload.message)" | head -25
        ;;
    3)
        echo -e "${GREEN}Running TC3: Restart with Pending Entry${NC}"
        # Use low-liquidity stock that might not fill immediately
        run_test 3 "Cancel Entry Test" "AAPL"
        echo ""
        echo "Restarting immediately (before fill)..."
        sleep 2
        restart_service
        echo ""
        echo "Checking for cancelled entry order:"
        gcloud logging read 'jsonPayload.message=~"Cancelling|cancel|AAPL"' --project=$PROJECT_ID --limit=20 --format="table(timestamp,jsonPayload.message)" | head -25
        ;;
    5)
        echo -e "${GREEN}Running TC5: No Tickers${NC}"
        python3 send_test_news.py --no-ticker --test-name "TC5 No Tickers"
        sleep 5
        echo ""
        echo "Checking logs:"
        gcloud logging read 'jsonPayload.message=~"No tickers|TC5"' --project=$PROJECT_ID --limit=10 --format="table(timestamp,jsonPayload.message)"
        ;;
    6)
        echo -e "${GREEN}Running TC6: News Too Old${NC}"
        python3 send_test_news.py --ticker AAPL --age 15 --test-name "TC6 Too Old"
        sleep 5
        echo ""
        echo "Checking logs:"
        gcloud logging read 'jsonPayload.message=~"too old|TC6"' --project=$PROJECT_ID --limit=10 --format="table(timestamp,jsonPayload.message)"
        ;;
    7)
        echo -e "${GREEN}Running TC7: News Too Fresh${NC}"
        python3 send_test_news.py --ticker AAPL --age 1 --test-name "TC7 Too Fresh"
        sleep 5
        echo ""
        echo "Checking logs:"
        gcloud logging read 'jsonPayload.message=~"too fresh|TC7"' --project=$PROJECT_ID --limit=10 --format="table(timestamp,jsonPayload.message)"
        ;;
    8)
        echo -e "${GREEN}Running TC8: Duplicate Strategy Prevention${NC}"
        run_test 8 "First MSFT" "MSFT"
        echo ""
        echo "Sending second news for same ticker..."
        sleep 3
        python3 send_test_news.py --ticker MSFT --test-name "TC8 Duplicate"
        sleep 5
        echo ""
        echo "Checking for skip message:"
        gcloud logging read 'jsonPayload.message=~"already has position|MSFT"' --project=$PROJECT_ID --limit=15 --format="table(timestamp,jsonPayload.message)"
        ;;
    10)
        echo -e "${GREEN}Running TC10: Multiple Tickers${NC}"
        python3 send_test_news.py --tickers GOOG,AMZN --test-name "TC10 Multi"
        sleep 5
        echo ""
        echo "Checking logs for both strategies:"
        gcloud logging read 'jsonPayload.message=~"GOOG|AMZN|TC10"' --project=$PROJECT_ID --limit=20 --format="table(timestamp,jsonPayload.message)"
        ;;
    "all")
        echo "Running all tests sequentially..."
        for t in 5 6 7 1; do
            $0 $t
            echo ""
            echo "Press Enter to continue to next test..."
            read
        done
        ;;
    *)
        echo "Available tests:"
        echo "  1  - TC1: Happy Path (full buy/sell cycle)"
        echo "  2  - TC2: Restart with open position"
        echo "  3  - TC3: Restart with pending entry"
        echo "  5  - TC5: No tickers in news"
        echo "  6  - TC6: News too old"
        echo "  7  - TC7: News too fresh"
        echo "  8  - TC8: Duplicate strategy prevention"
        echo "  10 - TC10: Multiple tickers"
        echo "  all - Run all tests"
        echo ""
        echo "Usage: $0 <test_number>"
        ;;
esac

echo ""
echo -e "${GREEN}Done${NC}"
