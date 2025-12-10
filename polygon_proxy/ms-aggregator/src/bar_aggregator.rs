use crate::types::{MsBar, PolygonTrade};
use std::time::{SystemTime, UNIX_EPOCH};

/// Aggregates trades into OHLCV bars
#[derive(Debug, Clone)]
pub struct BarAggregator {
    symbol: String,
    interval_ms: u64,
    open: Option<f64>,
    high: Option<f64>,
    low: Option<f64>,
    close: Option<f64>,
    volume: u64,
    num_trades: u32,
    window_start: u64,
    window_end: u64,
    last_trade_time: u64,
}

impl BarAggregator {
    pub fn new(symbol: String, interval_ms: u64) -> Self {
        let now = current_timestamp_ms();
        let window_start = (now / interval_ms) * interval_ms;
        let window_end = window_start + interval_ms;

        Self {
            symbol,
            interval_ms,
            open: None,
            high: None,
            low: None,
            close: None,
            volume: 0,
            num_trades: 0,
            window_start,
            window_end,
            last_trade_time: 0,
        }
    }

    /// Add a trade to the current bar
    pub fn add_trade(&mut self, trade: &PolygonTrade) {
        let trade_time = trade.timestamp;

        // If trade is before current window, ignore it (late data)
        if trade_time < self.window_start {
            return;
        }

        // If trade is in a future window, we need to handle window boundaries
        // For now, we'll just accumulate within the current window
        if trade_time >= self.window_end {
            return;
        }

        // Update OHLCV
        if self.open.is_none() {
            self.open = Some(trade.price);
        }

        self.high = Some(
            self.high
                .map(|h| h.max(trade.price))
                .unwrap_or(trade.price),
        );

        self.low = Some(
            self.low
                .map(|l| l.min(trade.price))
                .unwrap_or(trade.price),
        );

        self.close = Some(trade.price);
        self.volume += trade.size;
        self.num_trades += 1;
        self.last_trade_time = trade_time;
    }

    /// Check if the current bar is ready to be emitted
    /// Returns true if current time is past window_end + delay
    pub fn is_ready(&self, delay_ms: u64) -> bool {
        let now = current_timestamp_ms();
        now >= self.window_end + delay_ms
    }

    /// Check if this aggregator has any data
    pub fn has_data(&self) -> bool {
        self.open.is_some()
    }

    /// Emit the current bar and reset for the next window
    pub fn emit_and_reset(&mut self) -> Option<MsBar> {
        if !self.has_data() {
            // No trades in this window, advance to next window
            self.advance_window();
            return None;
        }

        let bar = MsBar {
            event_type: "MB".to_string(),
            symbol: self.symbol.clone(),
            interval_ms: self.interval_ms,
            open: self.open.unwrap(),
            high: self.high.unwrap(),
            low: self.low.unwrap(),
            close: self.close.unwrap(),
            volume: self.volume,
            start_timestamp: self.window_start,
            end_timestamp: self.window_end,
            num_trades: self.num_trades,
        };

        // Reset for next window
        self.advance_window();

        Some(bar)
    }

    /// Advance to the next time window
    fn advance_window(&mut self) {
        self.window_start = self.window_end;
        self.window_end = self.window_start + self.interval_ms;
        self.open = None;
        self.high = None;
        self.low = None;
        self.close = None;
        self.volume = 0;
        self.num_trades = 0;
    }

    /// Force emit current bar (even if not complete) and advance
    pub fn force_emit(&mut self) -> Option<MsBar> {
        self.emit_and_reset()
    }

    pub fn symbol(&self) -> &str {
        &self.symbol
    }

    pub fn interval_ms(&self) -> u64 {
        self.interval_ms
    }

    pub fn window_end(&self) -> u64 {
        self.window_end
    }
}

/// Get current timestamp in milliseconds
fn current_timestamp_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bar_aggregator_basic() {
        let mut agg = BarAggregator::new("AAPL".to_string(), 1000);

        // Create a trade in the current window
        let trade = PolygonTrade {
            symbol: "AAPL".to_string(),
            price: 150.0,
            size: 100,
            timestamp: agg.window_start + 100,
            extra: serde_json::Value::Null,
        };

        agg.add_trade(&trade);
        assert!(agg.has_data());
        assert_eq!(agg.num_trades, 1);
        assert_eq!(agg.volume, 100);
    }

    #[test]
    fn test_bar_aggregator_ohlc() {
        let mut agg = BarAggregator::new("AAPL".to_string(), 1000);
        let base_time = agg.window_start;

        let trades = vec![
            (base_time + 100, 150.0, 100),
            (base_time + 200, 152.0, 50),
            (base_time + 300, 149.0, 75),
            (base_time + 400, 151.0, 25),
        ];

        for (ts, price, size) in trades {
            let trade = PolygonTrade {
                symbol: "AAPL".to_string(),
                price,
                size,
                timestamp: ts,
                extra: serde_json::Value::Null,
            };
            agg.add_trade(&trade);
        }

        assert_eq!(agg.open, Some(150.0));
        assert_eq!(agg.high, Some(152.0));
        assert_eq!(agg.low, Some(149.0));
        assert_eq!(agg.close, Some(151.0));
        assert_eq!(agg.volume, 250);
        assert_eq!(agg.num_trades, 4);
    }

    #[test]
    fn test_bar_aggregator_emit() {
        let mut agg = BarAggregator::new("AAPL".to_string(), 1000);
        let base_time = agg.window_start;

        let trade = PolygonTrade {
            symbol: "AAPL".to_string(),
            price: 150.0,
            size: 100,
            timestamp: base_time + 100,
            extra: serde_json::Value::Null,
        };

        agg.add_trade(&trade);

        let bar = agg.emit_and_reset();
        assert!(bar.is_some());

        let bar = bar.unwrap();
        assert_eq!(bar.symbol, "AAPL");
        assert_eq!(bar.interval_ms, 1000);
        assert_eq!(bar.open, 150.0);
        assert_eq!(bar.volume, 100);

        // After emit, aggregator should be reset
        assert!(!agg.has_data());
    }
}
