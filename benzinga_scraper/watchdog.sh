#!/bin/bash
# Benzinga Scraper Watchdog
# Monitors news flow and restarts scraper if no news detected during market hours
#
# Market hours (UTC): 14:00-21:00 (9:30 AM - 4:00 PM ET)
# Extended hours (UTC): 09:00-14:00 pre-market, 21:00-01:00 after-hours

LOG_FILE="/var/log/benzinga-scraper.log"
WATCHDOG_LOG="/var/log/watchdog.log"
SERVICE_NAME="benzinga-scraper"

# Threshold: restart if no news for this many minutes during market hours
MARKET_HOURS_THRESHOLD=60
EXTENDED_HOURS_THRESHOLD=120

log() {
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $1" >> "$WATCHDOG_LOG"
}

# Get minutes since last published news
get_minutes_since_last_news() {
    local last_news_line=$(grep "Published.*news items to Pub/Sub" "$LOG_FILE" | tail -1)
    if [ -z "$last_news_line" ]; then
        echo "9999"
        return
    fi

    local last_news_time=$(echo "$last_news_line" | grep -oP '\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')
    if [ -z "$last_news_time" ]; then
        echo "9999"
        return
    fi

    local last_news_epoch=$(date -d "$last_news_time" +%s 2>/dev/null)
    if [ -z "$last_news_epoch" ] || [ "$last_news_epoch" -eq 0 ]; then
        echo "9999"
        return
    fi

    local now_epoch=$(date +%s)
    echo $(( (now_epoch - last_news_epoch) / 60 ))
}

# Check if we're in market hours (UTC)
# Regular: 14:30-21:00 UTC (9:30 AM - 4:00 PM ET)
# Pre-market: 09:00-14:30 UTC (4:00 AM - 9:30 AM ET)
# After-hours: 21:00-01:00 UTC (4:00 PM - 8:00 PM ET)
get_market_period() {
    local hour=$(date -u +%H)
    local minute=$(date -u +%M)
    local day=$(date -u +%u)  # 1=Monday, 7=Sunday

    # Weekend - no trading
    if [ "$day" -eq 6 ] || [ "$day" -eq 7 ]; then
        echo "closed"
        return
    fi

    # Convert to minutes since midnight for easier comparison
    local time_mins=$((hour * 60 + minute))

    # Regular hours: 14:30-21:00 UTC (870-1260 mins)
    if [ "$time_mins" -ge 870 ] && [ "$time_mins" -lt 1260 ]; then
        echo "regular"
        return
    fi

    # Pre-market: 09:00-14:30 UTC (540-870 mins)
    if [ "$time_mins" -ge 540 ] && [ "$time_mins" -lt 870 ]; then
        echo "premarket"
        return
    fi

    # After-hours: 21:00-01:00 UTC (1260-1440 or 0-60 mins)
    if [ "$time_mins" -ge 1260 ] || [ "$time_mins" -lt 60 ]; then
        echo "afterhours"
        return
    fi

    echo "closed"
}

# Check if service is running
is_service_running() {
    systemctl is-active --quiet "$SERVICE_NAME"
}

# Restart the scraper
restart_scraper() {
    log "RESTART: Initiating scraper restart..."
    systemctl restart "$SERVICE_NAME"
    sleep 5

    if is_service_running; then
        log "RESTART: Scraper restarted successfully"
    else
        log "ERROR: Scraper failed to restart!"
    fi
}

# Main watchdog logic
main() {
    local market_period=$(get_market_period)
    local minutes_since_news=$(get_minutes_since_last_news)
    local threshold=0

    case "$market_period" in
        "regular")
            threshold=$MARKET_HOURS_THRESHOLD
            ;;
        "premarket"|"afterhours")
            threshold=$EXTENDED_HOURS_THRESHOLD
            ;;
        "closed")
            log "CHECK: Market closed, skipping (last news: ${minutes_since_news} min ago)"
            exit 0
            ;;
    esac

    log "CHECK: Period=$market_period, LastNews=${minutes_since_news}min, Threshold=${threshold}min"

    # Check if service is running
    if ! is_service_running; then
        log "ALERT: Service not running! Starting..."
        systemctl start "$SERVICE_NAME"
        exit 0
    fi

    # Check if news threshold exceeded
    if [ "$minutes_since_news" -gt "$threshold" ]; then
        log "ALERT: No news for ${minutes_since_news} minutes (threshold: ${threshold}). Restarting..."
        restart_scraper
    fi
}

main
