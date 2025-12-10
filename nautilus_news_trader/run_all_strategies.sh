#!/bin/bash
#
# Run all 3 trading strategies as independent processes.
#
# Each strategy runs in its own process with:
# - Separate PID file (prevents duplicates)
# - Separate log directory
# - Separate NautilusTrader instance
#
# Usage:
#   ./run_all_strategies.sh           # Run all 3 in background
#   ./run_all_strategies.sh stop      # Stop all
#   ./run_all_strategies.sh status    # Check status
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Find Python executable (prefer nautilus venv with all dependencies)
if [ -f "/opt/nautilus_trader_private/.venv/bin/python" ]; then
    PYTHON="/opt/nautilus_trader_private/.venv/bin/python"
elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

# Strategy runners
STRATEGIES=(
    "strategies/volume_5pct/run.py"
    "strategies/volume_10pct/run.py"
    "strategies/trend/run.py"
)

STRATEGY_NAMES=("volume_5pct" "volume_10pct" "trend")

# Use local runner dir for development, /opt for production
if [ -d "/opt/news-trader" ] && [ -w "/opt/news-trader" ]; then
    PID_DIR="/opt/news-trader/runner"
else
    PID_DIR="$SCRIPT_DIR/runner"
fi

case "${1:-start}" in
    start)
        echo "Starting all strategies..."
        echo ""

        for i in "${!STRATEGIES[@]}"; do
            name="${STRATEGY_NAMES[$i]}"
            script="${STRATEGIES[$i]}"
            pid_file="$PID_DIR/$name/process.pid"
            log_file="$PID_DIR/$name/logs/stdout.log"

            # Check if already running
            if [ -f "$pid_file" ]; then
                pid=$(cat "$pid_file")
                if kill -0 "$pid" 2>/dev/null; then
                    echo "[$name] Already running (PID: $pid)"
                    continue
                fi
            fi

            # Create log directory
            mkdir -p "$PID_DIR/$name/logs"

            # Start in background
            echo "[$name] Starting..."
            nohup $PYTHON "$script" > "$log_file" 2>&1 &

            # Wait for PID file (NautilusTrader takes ~3-5s to initialize)
            sleep 5

            if [ -f "$pid_file" ]; then
                pid=$(cat "$pid_file")
                echo "[$name] Started (PID: $pid)"
            else
                echo "[$name] Failed to start (check logs)"
            fi
        done

        echo ""
        echo "All strategies started. Check status with: $0 status"
        ;;

    stop)
        echo "Stopping all strategies..."
        echo ""

        for name in "${STRATEGY_NAMES[@]}"; do
            pid_file="$PID_DIR/$name/process.pid"

            if [ -f "$pid_file" ]; then
                pid=$(cat "$pid_file")
                if kill -0 "$pid" 2>/dev/null; then
                    echo "[$name] Stopping (PID: $pid)..."
                    kill "$pid"
                    sleep 1

                    if kill -0 "$pid" 2>/dev/null; then
                        echo "[$name] Force killing..."
                        kill -9 "$pid"
                    fi

                    rm -f "$pid_file"
                    echo "[$name] Stopped"
                else
                    echo "[$name] Not running (stale PID file)"
                    rm -f "$pid_file"
                fi
            else
                echo "[$name] Not running"
            fi
        done

        echo ""
        echo "All strategies stopped."
        ;;

    status)
        echo "Strategy Status"
        echo "==============="
        echo ""

        for name in "${STRATEGY_NAMES[@]}"; do
            pid_file="$PID_DIR/$name/process.pid"

            if [ -f "$pid_file" ]; then
                pid=$(cat "$pid_file")
                if kill -0 "$pid" 2>/dev/null; then
                    echo "[$name] RUNNING (PID: $pid)"
                else
                    echo "[$name] STOPPED (stale PID file)"
                fi
            else
                echo "[$name] STOPPED"
            fi
        done
        ;;

    logs)
        name="${2:-volume_5pct}"
        log_file="$PID_DIR/$name/logs/stdout.log"

        if [ -f "$log_file" ]; then
            tail -f "$log_file"
        else
            echo "No logs found for $name"
        fi
        ;;

    *)
        echo "Usage: $0 {start|stop|status|logs [strategy_name]}"
        echo ""
        echo "Commands:"
        echo "  start   - Start all strategies in background"
        echo "  stop    - Stop all strategies"
        echo "  status  - Show running status"
        echo "  logs    - Tail logs (default: volume_5pct)"
        echo ""
        echo "Strategies: volume_5pct, volume_10pct, trend"
        ;;
esac
