#!/bin/bash
# Pre-deploy check script
# Run before deploying to catch basic errors

set -e

cd "$(dirname "$0")"

echo "=== Pre-Deploy Checks ==="
echo ""

# 1. Python syntax check (catches syntax errors)
echo "1. Syntax check..."
python3 -m py_compile strategies/news_volume_strategy.py
python3 -m py_compile actors/pubsub_news_controller.py
echo "   ✓ Syntax OK"

# 2. Ruff linting (catches bare except, undefined vars, common bugs)
echo "2. Ruff lint..."
if command -v ruff &> /dev/null; then
    # B = flake8-bugbear (common bugs), E722 = bare except
    ISSUES=$(ruff check strategies/ actors/ --select=E722,B,F821,F841 --output-format=concise 2>&1 || true)
    if [ -n "$ISSUES" ]; then
        echo "$ISSUES"
        echo ""
        echo "   ⚠ Ruff found potential bugs - review before deploy"
    else
        echo "   ✓ Ruff OK"
    fi
else
    echo "   ⚠ Ruff not installed (pip install ruff)"
fi

# 3. Check for common NautilusTrader pitfalls
echo "3. NautilusTrader pattern check..."
PITFALLS=0

# Check for calling properties as methods (common bug)
if grep -rn "\.unrealized_pnl(" strategies/ actors/ 2>/dev/null; then
    echo "   ⚠ unrealized_pnl is a property, not a method!"
    PITFALLS=1
fi

if grep -rn "\.realized_pnl(" strategies/ actors/ 2>/dev/null; then
    echo "   ⚠ realized_pnl is a property, not a method!"
    PITFALLS=1
fi

# Check for wrong event attribute access
if grep -rn "order\.status" strategies/ actors/ 2>/dev/null | grep -v "# " | grep -v "TODO"; then
    echo "   ⚠ Check: order.status vs event.reason in rejection handlers"
    PITFALLS=1
fi

if [ $PITFALLS -eq 0 ]; then
    echo "   ✓ No known pitfalls found"
fi

echo ""
echo "=== Local checks complete ==="
echo ""
echo "To run full tests on GCP (where nautilus_trader is installed):"
echo "  gcloud compute scp tests/test_strategy_handlers.py news-trader:/opt/news-trader/tests/ --zone=us-east4-a"
echo "  gcloud compute ssh news-trader --zone=us-east4-a --command='cd /opt/news-trader && python -m pytest tests/test_strategy_handlers.py -v'"
echo ""
echo "Deploy with: ./deploy.sh"
