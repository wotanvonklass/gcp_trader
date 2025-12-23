use crate::bar_aggregator::BarAggregator;
use crate::trade_buffer::TradeBuffer;
use crate::types::{BarKey, MsBar, PolygonTrade, parse_ms_subscription};
use dashmap::DashMap;
use std::collections::HashSet;
use std::sync::Arc;
use tracing::{debug, info};
use uuid::Uuid;

pub type ClientId = Uuid;

/// Manages bar subscriptions for all clients
pub struct SubscriptionManager {
    /// Active bar aggregators (one per symbol+interval combination)
    aggregators: Arc<DashMap<BarKey, BarAggregator>>,

    /// Client subscriptions (clientId -> set of BarKeys)
    client_subscriptions: Arc<DashMap<ClientId, HashSet<BarKey>>>,

    /// Reverse mapping: BarKey -> set of ClientIds
    key_to_clients: Arc<DashMap<BarKey, HashSet<ClientId>>>,

    /// Wildcard subscriptions (clientId -> set of intervals for "*")
    wildcard_subscriptions: Arc<DashMap<ClientId, HashSet<u64>>>,

    /// Rolling trade buffer for all symbols (60 seconds)
    trade_buffer: Arc<TradeBuffer>,

    /// Bar emission delay in milliseconds
    bar_delay_ms: u64,

    /// Min/max interval validation
    min_interval_ms: u64,
    max_interval_ms: u64,
}

impl SubscriptionManager {
    pub fn new(min_interval_ms: u64, max_interval_ms: u64, bar_delay_ms: u64) -> Self {
        Self {
            aggregators: Arc::new(DashMap::new()),
            client_subscriptions: Arc::new(DashMap::new()),
            key_to_clients: Arc::new(DashMap::new()),
            wildcard_subscriptions: Arc::new(DashMap::new()),
            trade_buffer: Arc::new(TradeBuffer::new()),
            bar_delay_ms,
            min_interval_ms,
            max_interval_ms,
        }
    }

    /// Get reference to the trade buffer
    pub fn trade_buffer(&self) -> &TradeBuffer {
        &self.trade_buffer
    }

    /// Generate bars from buffered trades for a symbol since a given timestamp
    pub fn generate_bars_since(&self, symbol: &str, interval_ms: u64, since_ms: u64) -> Vec<MsBar> {
        self.trade_buffer.generate_bars_since(symbol, interval_ms, since_ms)
    }

    /// Subscribe a client to one or more bar intervals
    /// Format: "100Ms.AAPL,250Ms.AAPL,1000Ms.*"
    pub fn subscribe(&self, client_id: ClientId, params: &str) -> Result<Vec<String>, String> {
        let subscriptions: Vec<&str> = params.split(',').map(|s| s.trim()).collect();
        let mut subscribed = Vec::new();
        let mut errors = Vec::new();

        for sub in subscriptions {
            match parse_ms_subscription(sub) {
                Some(bar_sub) => {
                    // Validate interval
                    if bar_sub.interval_ms < self.min_interval_ms
                        || bar_sub.interval_ms > self.max_interval_ms
                    {
                        errors.push(format!(
                            "Interval {}ms out of range ({}-{} ms)",
                            bar_sub.interval_ms, self.min_interval_ms, self.max_interval_ms
                        ));
                        continue;
                    }

                    if bar_sub.symbol == "*" {
                        // Wildcard subscription
                        self.wildcard_subscriptions
                            .entry(client_id)
                            .or_insert_with(HashSet::new)
                            .insert(bar_sub.interval_ms);

                        subscribed.push(sub.to_string());
                        info!(
                            "Client {} subscribed to wildcard interval {}ms",
                            client_id, bar_sub.interval_ms
                        );
                    } else {
                        // Specific symbol subscription
                        let key = BarKey {
                            symbol: bar_sub.symbol.clone(),
                            interval_ms: bar_sub.interval_ms,
                        };

                        // Ensure aggregator exists
                        self.aggregators
                            .entry(key.clone())
                            .or_insert_with(|| {
                                info!("Created aggregator for {}.{}Ms", key.symbol, key.interval_ms);
                                BarAggregator::new(key.symbol.clone(), key.interval_ms)
                            });

                        // Add to client subscriptions
                        self.client_subscriptions
                            .entry(client_id)
                            .or_insert_with(HashSet::new)
                            .insert(key.clone());

                        // Add to reverse mapping
                        self.key_to_clients
                            .entry(key.clone())
                            .or_insert_with(HashSet::new)
                            .insert(client_id);

                        subscribed.push(sub.to_string());
                        info!("Client {} subscribed to {}", client_id, sub);
                    }
                }
                None => {
                    errors.push(format!("Invalid subscription format: {}", sub));
                }
            }
        }

        if !errors.is_empty() {
            Err(errors.join("; "))
        } else {
            Ok(subscribed)
        }
    }

    /// Unsubscribe a client from bar intervals
    pub fn unsubscribe(&self, client_id: ClientId, params: &str) -> Result<(), String> {
        let subscriptions: Vec<&str> = params.split(',').map(|s| s.trim()).collect();

        for sub in subscriptions {
            if let Some(bar_sub) = parse_ms_subscription(sub) {
                if bar_sub.symbol == "*" {
                    // Remove wildcard subscription
                    if let Some(mut wildcards) = self.wildcard_subscriptions.get_mut(&client_id) {
                        wildcards.remove(&bar_sub.interval_ms);
                    }
                } else {
                    let key = BarKey {
                        symbol: bar_sub.symbol.clone(),
                        interval_ms: bar_sub.interval_ms,
                    };

                    // Remove from client subscriptions
                    if let Some(mut subs) = self.client_subscriptions.get_mut(&client_id) {
                        subs.remove(&key);
                    }

                    // Remove from reverse mapping
                    if let Some(mut clients) = self.key_to_clients.get_mut(&key) {
                        clients.remove(&client_id);

                        // If no more clients, remove aggregator
                        if clients.is_empty() {
                            drop(clients);
                            self.key_to_clients.remove(&key);
                            self.aggregators.remove(&key);
                            debug!("Removed aggregator for {:?}", key);
                        }
                    }
                }

                info!("Client {} unsubscribed from {}", client_id, sub);
            }
        }

        Ok(())
    }

    /// Remove all subscriptions for a client
    pub fn remove_client(&self, client_id: ClientId) {
        // Remove specific subscriptions
        if let Some((_, keys)) = self.client_subscriptions.remove(&client_id) {
            for key in keys {
                if let Some(mut clients) = self.key_to_clients.get_mut(&key) {
                    clients.remove(&client_id);

                    if clients.is_empty() {
                        drop(clients);
                        self.key_to_clients.remove(&key);
                        self.aggregators.remove(&key);
                        debug!("Removed aggregator for {:?}", key);
                    }
                }
            }
        }

        // Remove wildcard subscriptions
        self.wildcard_subscriptions.remove(&client_id);

        info!("Removed all subscriptions for client {}", client_id);
    }

    /// Process a trade and update relevant aggregators
    pub fn process_trade(&self, trade: &PolygonTrade) {
        // Always store in buffer (for historical replay)
        self.trade_buffer.store(trade);

        // Early exit: if no aggregators exist, skip further processing
        if self.aggregators.is_empty() {
            return;
        }

        // Collect matching keys first to avoid borrow conflicts
        // Only check aggregators that match the trade symbol
        let matching_keys: Vec<BarKey> = self
            .aggregators
            .iter()
            .filter_map(|entry| {
                if entry.key().symbol == trade.symbol {
                    Some(entry.key().clone())
                } else {
                    None
                }
            })
            .collect();

        // Early exit: if no aggregators for this symbol, skip
        if matching_keys.is_empty() {
            return;
        }

        // Update each matching aggregator
        for key in matching_keys {
            if let Some(mut agg) = self.aggregators.get_mut(&key) {
                debug!(
                    "Processing {} trade: ${} @ {} size={}",
                    trade.symbol, trade.price, trade.timestamp, trade.size
                );
                agg.add_trade(trade);
            }
        }
    }

    /// Check all aggregators and emit ready bars
    /// Returns list of (ClientId, MsBar) tuples
    pub fn check_and_emit_bars(&self) -> Vec<(ClientId, MsBar)> {
        let mut bars_to_send = Vec::new();

        // Check each aggregator
        for mut entry in self.aggregators.iter_mut() {
            let key = entry.key().clone(); // Clone the key to avoid borrow conflicts
            let agg = entry.value_mut();

            if agg.is_ready(self.bar_delay_ms) {
                if let Some(bar) = agg.emit_and_reset() {
                    // Find all clients subscribed to this bar
                    let mut recipients = HashSet::new();

                    // Check specific subscriptions
                    if let Some(clients) = self.key_to_clients.get(&key) {
                        recipients.extend(clients.iter().copied());
                    }

                    // Check wildcard subscriptions
                    for entry in self.wildcard_subscriptions.iter() {
                        let client_id = entry.key();
                        let intervals = entry.value();
                        if intervals.contains(&key.interval_ms) {
                            recipients.insert(*client_id);
                        }
                    }

                    // Add bar for each recipient
                    for client_id in recipients {
                        bars_to_send.push((client_id, bar.clone()));
                    }

                    if !bars_to_send.is_empty() {
                        info!(
                            "Emitted bar for {}.{}Ms to {} clients",
                            bar.symbol,
                            bar.interval_ms,
                            bars_to_send.len()
                        );
                    }
                }
            }
        }

        bars_to_send
    }

    /// Get statistics about current state
    pub fn stats(&self) -> SubscriptionStats {
        let buffer_stats = self.trade_buffer.stats();
        SubscriptionStats {
            num_aggregators: self.aggregators.len(),
            num_clients: self.client_subscriptions.len(),
            num_wildcard_clients: self.wildcard_subscriptions.len(),
            buffer_symbols: buffer_stats.num_symbols,
            buffer_trades: buffer_stats.total_trades,
        }
    }

    /// Prune old trades from the buffer (call periodically)
    pub fn prune_buffer(&self) {
        self.trade_buffer.prune_all();
    }
}

#[derive(Debug)]
pub struct SubscriptionStats {
    pub num_aggregators: usize,
    pub num_clients: usize,
    pub num_wildcard_clients: usize,
    pub buffer_symbols: usize,
    pub buffer_trades: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_subscribe_specific() {
        let mgr = SubscriptionManager::new(1, 60000, 20);
        let client_id = Uuid::new_v4();

        let result = mgr.subscribe(client_id, "100Ms.AAPL,250Ms.AAPL");
        assert!(result.is_ok());

        let stats = mgr.stats();
        assert_eq!(stats.num_aggregators, 2);
        assert_eq!(stats.num_clients, 1);
    }

    #[test]
    fn test_subscribe_wildcard() {
        let mgr = SubscriptionManager::new(1, 60000, 20);
        let client_id = Uuid::new_v4();

        let result = mgr.subscribe(client_id, "100Ms.*");
        assert!(result.is_ok());

        let stats = mgr.stats();
        assert_eq!(stats.num_wildcard_clients, 1);
    }

    #[test]
    fn test_subscribe_invalid_interval() {
        let mgr = SubscriptionManager::new(1, 60000, 20);
        let client_id = Uuid::new_v4();

        let result = mgr.subscribe(client_id, "60001Ms.AAPL");
        assert!(result.is_err());

        let result = mgr.subscribe(client_id, "0Ms.AAPL");
        assert!(result.is_err());
    }

    #[test]
    fn test_remove_client() {
        let mgr = SubscriptionManager::new(1, 60000, 20);
        let client_id = Uuid::new_v4();

        mgr.subscribe(client_id, "100Ms.AAPL").unwrap();
        assert_eq!(mgr.stats().num_aggregators, 1);

        mgr.remove_client(client_id);
        assert_eq!(mgr.stats().num_aggregators, 0);
        assert_eq!(mgr.stats().num_clients, 0);
    }
}
