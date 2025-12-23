use crate::types::{MsBar, PolygonTrade};
use dashmap::DashMap;
use std::collections::VecDeque;
use std::time::{SystemTime, UNIX_EPOCH};
use tracing::debug;

/// Buffer duration in milliseconds (60 seconds)
const BUFFER_DURATION_MS: u64 = 60_000;

/// A simple trade record for buffering (smaller than full PolygonTrade)
#[derive(Debug, Clone)]
pub struct BufferedTrade {
    pub timestamp: u64,  // ms
    pub price: f64,
    pub size: u64,
}

impl From<&PolygonTrade> for BufferedTrade {
    fn from(trade: &PolygonTrade) -> Self {
        Self {
            timestamp: trade.timestamp,
            price: trade.price,
            size: trade.size,
        }
    }
}

/// Rolling buffer of trades per symbol
pub struct TradeBuffer {
    /// symbol -> deque of trades (oldest first)
    trades: DashMap<String, VecDeque<BufferedTrade>>,
    /// Maximum age of trades to keep (ms)
    max_age_ms: u64,
}

impl TradeBuffer {
    pub fn new() -> Self {
        Self::with_duration(BUFFER_DURATION_MS)
    }

    pub fn with_duration(max_age_ms: u64) -> Self {
        Self {
            trades: DashMap::new(),
            max_age_ms,
        }
    }

    /// Store a trade in the buffer
    pub fn store(&self, trade: &PolygonTrade) {
        let buffered = BufferedTrade::from(trade);
        let symbol = trade.symbol.clone();

        let mut queue = self.trades.entry(symbol).or_insert_with(VecDeque::new);
        queue.push_back(buffered);

        // Prune old trades from the front
        self.prune_queue(&mut queue, trade.timestamp);
    }

    /// Prune trades older than max_age_ms from the front of the queue
    fn prune_queue(&self, queue: &mut VecDeque<BufferedTrade>, current_time: u64) {
        let cutoff = current_time.saturating_sub(self.max_age_ms);
        while let Some(front) = queue.front() {
            if front.timestamp < cutoff {
                queue.pop_front();
            } else {
                break;
            }
        }
    }

    /// Get all trades for a symbol since a given timestamp
    pub fn get_trades_since(&self, symbol: &str, since_ms: u64) -> Vec<BufferedTrade> {
        self.trades
            .get(symbol)
            .map(|queue| {
                queue
                    .iter()
                    .filter(|t| t.timestamp >= since_ms)
                    .cloned()
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Generate bars from buffered trades for a symbol
    /// Returns bars from `since_ms` up to the last trade, with the given interval
    pub fn generate_bars_since(
        &self,
        symbol: &str,
        interval_ms: u64,
        since_ms: u64,
    ) -> Vec<MsBar> {
        let trades = self.get_trades_since(symbol, since_ms);
        if trades.is_empty() {
            return Vec::new();
        }

        // Align since_ms to interval boundary
        let first_window_start = (since_ms / interval_ms) * interval_ms;

        // Find the last trade timestamp to limit iteration
        let last_trade_ts = trades.iter().map(|t| t.timestamp).max().unwrap_or(since_ms);

        // Group trades into windows and create bars
        let mut bars = Vec::new();
        let mut current_window_start = first_window_start;

        // Only iterate up to the last trade (+ one interval to include it)
        while current_window_start <= last_trade_ts {
            let window_end = current_window_start + interval_ms;

            // Collect trades in this window
            let window_trades: Vec<&BufferedTrade> = trades
                .iter()
                .filter(|t| t.timestamp >= current_window_start && t.timestamp < window_end)
                .collect();

            if !window_trades.is_empty() {
                // Compute OHLCV
                let open = window_trades.first().unwrap().price;
                let close = window_trades.last().unwrap().price;
                let high = window_trades.iter().map(|t| t.price).fold(f64::MIN, f64::max);
                let low = window_trades.iter().map(|t| t.price).fold(f64::MAX, f64::min);
                let volume: u64 = window_trades.iter().map(|t| t.size).sum();
                let num_trades = window_trades.len() as u32;

                bars.push(MsBar {
                    event_type: "MB".to_string(),
                    symbol: symbol.to_string(),
                    interval_ms,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    start_timestamp: current_window_start,
                    end_timestamp: window_end,
                    num_trades,
                });
            }

            current_window_start = window_end;
        }

        debug!(
            "Generated {} bars for {} since {} with interval {}ms",
            bars.len(),
            symbol,
            since_ms,
            interval_ms
        );

        bars
    }

    /// Get statistics about the buffer
    pub fn stats(&self) -> TradeBufferStats {
        let mut total_trades = 0;
        let mut symbols = 0;

        for entry in self.trades.iter() {
            symbols += 1;
            total_trades += entry.value().len();
        }

        TradeBufferStats {
            num_symbols: symbols,
            total_trades,
            max_age_ms: self.max_age_ms,
        }
    }

    /// Prune all old trades (call periodically)
    pub fn prune_all(&self) {
        let now = current_timestamp_ms();
        let cutoff = now.saturating_sub(self.max_age_ms);

        for mut entry in self.trades.iter_mut() {
            let queue = entry.value_mut();
            while let Some(front) = queue.front() {
                if front.timestamp < cutoff {
                    queue.pop_front();
                } else {
                    break;
                }
            }
        }

        // Remove empty queues
        self.trades.retain(|_, queue| !queue.is_empty());
    }
}

impl Default for TradeBuffer {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug)]
pub struct TradeBufferStats {
    pub num_symbols: usize,
    pub total_trades: usize,
    pub max_age_ms: u64,
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

    fn make_trade(symbol: &str, timestamp: u64, price: f64, size: u64) -> PolygonTrade {
        PolygonTrade {
            symbol: symbol.to_string(),
            timestamp,
            price,
            size,
            extra: serde_json::Value::Null,
        }
    }

    #[test]
    fn test_store_and_retrieve() {
        let buffer = TradeBuffer::with_duration(10_000); // 10 seconds

        let trade1 = make_trade("AAPL", 1000, 150.0, 100);
        let trade2 = make_trade("AAPL", 2000, 151.0, 200);
        let trade3 = make_trade("AAPL", 3000, 149.0, 150);

        buffer.store(&trade1);
        buffer.store(&trade2);
        buffer.store(&trade3);

        let trades = buffer.get_trades_since("AAPL", 0);
        assert_eq!(trades.len(), 3);

        let trades = buffer.get_trades_since("AAPL", 2000);
        assert_eq!(trades.len(), 2);

        let trades = buffer.get_trades_since("AAPL", 5000);
        assert_eq!(trades.len(), 0);
    }

    #[test]
    fn test_pruning() {
        let buffer = TradeBuffer::with_duration(5_000); // 5 seconds

        // Store old trades
        buffer.store(&make_trade("AAPL", 1000, 150.0, 100));
        buffer.store(&make_trade("AAPL", 2000, 151.0, 200));

        // Store a recent trade that triggers pruning
        buffer.store(&make_trade("AAPL", 10000, 152.0, 300));

        // Old trades should be pruned (10000 - 5000 = 5000 cutoff)
        let trades = buffer.get_trades_since("AAPL", 0);
        assert_eq!(trades.len(), 1);
        assert_eq!(trades[0].timestamp, 10000);
    }

    #[test]
    fn test_generate_bars() {
        let buffer = TradeBuffer::with_duration(60_000);

        // Trades spanning multiple 250ms windows
        let base_time = 1000000;
        buffer.store(&make_trade("MGRX", base_time + 50, 1.60, 500));
        buffer.store(&make_trade("MGRX", base_time + 120, 1.62, 200));
        buffer.store(&make_trade("MGRX", base_time + 180, 1.65, 800));
        buffer.store(&make_trade("MGRX", base_time + 300, 1.64, 400));
        buffer.store(&make_trade("MGRX", base_time + 450, 1.68, 300));

        let bars = buffer.generate_bars_since("MGRX", 250, base_time);

        // Should have 2 bars: [base..base+250] and [base+250..base+500]
        assert_eq!(bars.len(), 2);

        // First bar: trades at 50, 120, 180
        assert_eq!(bars[0].open, 1.60);
        assert_eq!(bars[0].close, 1.65);
        assert_eq!(bars[0].high, 1.65);
        assert_eq!(bars[0].low, 1.60);
        assert_eq!(bars[0].volume, 1500); // 500 + 200 + 800
        assert_eq!(bars[0].num_trades, 3);

        // Second bar: trades at 300, 450
        assert_eq!(bars[1].open, 1.64);
        assert_eq!(bars[1].close, 1.68);
        assert_eq!(bars[1].volume, 700); // 400 + 300
        assert_eq!(bars[1].num_trades, 2);
    }

    #[test]
    fn test_multiple_symbols() {
        let buffer = TradeBuffer::with_duration(60_000);

        buffer.store(&make_trade("AAPL", 1000, 150.0, 100));
        buffer.store(&make_trade("MGRX", 1000, 1.60, 500));
        buffer.store(&make_trade("TSLA", 1000, 250.0, 50));

        assert_eq!(buffer.get_trades_since("AAPL", 0).len(), 1);
        assert_eq!(buffer.get_trades_since("MGRX", 0).len(), 1);
        assert_eq!(buffer.get_trades_since("TSLA", 0).len(), 1);
        assert_eq!(buffer.get_trades_since("UNKNOWN", 0).len(), 0);

        let stats = buffer.stats();
        assert_eq!(stats.num_symbols, 3);
        assert_eq!(stats.total_trades, 3);
    }
}
