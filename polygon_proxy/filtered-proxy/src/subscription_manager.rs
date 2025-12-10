use crate::types::{is_bar_subscription, is_ms_bar_subscription, ClientId};
use std::collections::{HashMap, HashSet};
use tokio::time::{Duration, Instant};
use tracing::{debug, info};

pub struct SubscriptionManager {
    // Client ID -> Their subscriptions (can include "*" for wildcard)
    client_subs: HashMap<ClientId, HashSet<String>>,
    
    // Track who has wildcard
    wildcard_clients: HashSet<ClientId>,
    
    // Symbol -> Set of clients (for specific subscriptions)
    symbol_to_clients: HashMap<String, HashSet<ClientId>>,
    
    // Symbols to unsubscribe upstream (with timestamp for delayed cleanup)
    pending_unsubs: HashMap<String, Instant>,
}

impl SubscriptionManager {
    pub fn new() -> Self {
        Self {
            client_subs: HashMap::new(),
            wildcard_clients: HashSet::new(),
            symbol_to_clients: HashMap::new(),
            pending_unsubs: HashMap::new(),
        }
    }
    
    pub fn add_subscription(&mut self, client_id: ClientId, params: &str) {
        // Parse params: "T.AAPL,Q.AAPL,T.*" etc
        let symbols = self.parse_symbols(params);
        
        for symbol in symbols {
            if symbol == "*" {
                // Client wants everything
                self.wildcard_clients.insert(client_id);
                info!("Client {} subscribed to wildcard", client_id);
            } else {
                // Specific symbol subscription
                self.symbol_to_clients
                    .entry(symbol.clone())
                    .or_default()
                    .insert(client_id);
                debug!("Client {} subscribed to {}", client_id, symbol);
            }
            
            self.client_subs
                .entry(client_id)
                .or_default()
                .insert(symbol.clone());
                
            // Remove from pending unsubs if it was scheduled
            self.pending_unsubs.remove(&symbol);
        }
    }
    
    pub fn remove_subscription(&mut self, client_id: ClientId, params: &str) {
        let symbols = self.parse_symbols(params);
        
        for symbol in symbols {
            if symbol == "*" {
                self.wildcard_clients.remove(&client_id);
                info!("Client {} unsubscribed from wildcard", client_id);
            } else {
                if let Some(clients) = self.symbol_to_clients.get_mut(&symbol) {
                    clients.remove(&client_id);
                    
                    // Schedule upstream unsub if no clients left
                    if clients.is_empty() && self.wildcard_clients.is_empty() {
                        // Schedule for removal in 30 seconds
                        self.pending_unsubs.insert(symbol.clone(), Instant::now());
                        debug!("Scheduled {} for upstream unsubscribe", symbol);
                    }
                }
            }
            
            if let Some(subs) = self.client_subs.get_mut(&client_id) {
                subs.remove(&symbol);
            }
        }
    }
    
    pub fn get_filtered_messages_per_client(&self, message: &str) -> HashMap<ClientId, String> {
        use serde_json::Value;

        let mut result = HashMap::new();

        // Try to parse as JSON array
        if let Ok(Value::Array(messages)) = serde_json::from_str::<Value>(message) {
            // Build per-client filtered arrays
            let mut client_messages: HashMap<ClientId, Vec<Value>> = HashMap::new();

            // Initialize wildcard clients with empty arrays
            for client_id in &self.wildcard_clients {
                client_messages.insert(*client_id, Vec::new());
            }

            // Process each message in the array
            for msg_value in messages {
                // Extract sym and ev fields
                if let (Some(sym), Some(ev)) = (
                    msg_value.get("sym").and_then(|v| v.as_str()),
                    msg_value.get("ev").and_then(|v| v.as_str()),
                ) {
                    let subscription_key = format!("{}.{}", ev, sym);

                    // Add to wildcard clients
                    for client_id in &self.wildcard_clients {
                        client_messages.get_mut(client_id)
                            .unwrap()
                            .push(msg_value.clone());
                    }

                    // Add to specific subscribers
                    if let Some(clients) = self.symbol_to_clients.get(&subscription_key) {
                        for client_id in clients {
                            client_messages.entry(*client_id)
                                .or_insert_with(Vec::new)
                                .push(msg_value.clone());
                        }
                    }
                } else {
                    // Message doesn't have sym/ev fields - send to wildcard clients only
                    for client_id in &self.wildcard_clients {
                        client_messages.get_mut(client_id)
                            .unwrap()
                            .push(msg_value.clone());
                    }
                }
            }

            // Serialize each client's filtered array
            for (client_id, msgs) in client_messages {
                if !msgs.is_empty() {
                    if let Ok(serialized) = serde_json::to_string(&msgs) {
                        result.insert(client_id, serialized);
                    }
                }
            }
        } else {
            // Not a JSON array - send to wildcard clients only
            for client_id in &self.wildcard_clients {
                result.insert(*client_id, message.to_string());
            }
        }

        result
    }
    
    // Get subscriptions for Firehose (trades, quotes, but NOT bars)
    pub fn get_firehose_subscription(&self) -> String {
        if !self.wildcard_clients.is_empty() {
            // Wildcard for firehose: only non-bar types
            // T = Trades, Q = Quotes, LULD, FMV
            // Note: ALL bars (A.*, AM.*, *Ms.*) go to ms-aggregator
            "T.*,Q.*,LULD.*,FMV.*".to_string()
        } else {
            // Build subscription string from non-bar symbols
            // Includes: T.*, Q.*, LULD.*, FMV.* but NOT A.*, AM.*, or *Ms.*
            self.symbol_to_clients.keys()
                .filter(|s| !is_bar_subscription(s))
                .cloned()
                .collect::<Vec<_>>()
                .join(",")
        }
    }

    // Get subscriptions for Ms-Aggregator (all bar types: A.*, AM.*, and *Ms.*)
    pub fn get_ms_aggregator_subscription(&self) -> String {
        if !self.wildcard_clients.is_empty() {
            // Wildcard for ms-aggregator: all native bars
            // A.* = Second bars, AM.* = Minute bars
            // NOTE: Wildcard does NOT include millisecond bars (*Ms.*)
            // Clients must explicitly subscribe to millisecond bars (e.g., "500Ms.TSLA")
            "A.*,AM.*".to_string()
        } else {
            // Build subscription string from all bar symbols
            // Includes: A.*, AM.*, 100Ms.*, 250Ms.*, 500Ms.*, etc.
            self.symbol_to_clients.keys()
                .filter(|s| is_bar_subscription(s))
                .cloned()
                .collect::<Vec<_>>()
                .join(",")
        }
    }
    
    pub fn cleanup_pending_unsubs(&mut self) -> Vec<String> {
        let now = Instant::now();
        let mut to_unsub = Vec::new();
        
        self.pending_unsubs.retain(|symbol, time| {
            if now.duration_since(*time) > Duration::from_secs(30) {
                to_unsub.push(symbol.clone());
                false // Remove from pending
            } else {
                true // Keep in pending
            }
        });
        
        to_unsub
    }
    
    #[allow(dead_code)]
    pub fn has_clients(&self) -> bool {
        !self.client_subs.is_empty()
    }

    // Check if there's a subscriber for a specific subscription key (e.g., "T.AAPL")
    pub fn has_subscription(&self, subscription_key: &str) -> bool {
        // Wildcard clients get everything
        if !self.wildcard_clients.is_empty() {
            return true;
        }

        // Check if anyone is subscribed to this specific key
        self.symbol_to_clients
            .get(subscription_key)
            .map(|clients| !clients.is_empty())
            .unwrap_or(false)
    }

    pub fn remove_client(&mut self, client_id: ClientId) {
        // Get all their subscriptions
        if let Some(subs) = self.client_subs.remove(&client_id) {
            for symbol in subs {
                if symbol == "*" {
                    self.wildcard_clients.remove(&client_id);
                } else {
                    if let Some(clients) = self.symbol_to_clients.get_mut(&symbol) {
                        clients.remove(&client_id);
                        if clients.is_empty() && self.wildcard_clients.is_empty() {
                            self.pending_unsubs.insert(symbol, Instant::now());
                        }
                    }
                }
            }
        }
        info!("Removed all subscriptions for client {}", client_id);
    }
    
    fn parse_symbols(&self, params: &str) -> Vec<String> {
        // Parse "T.AAPL,Q.AAPL,T.*" format
        // Keep the full TYPE.SYMBOL format to track per-message-type subscriptions
        let mut symbols = HashSet::new();

        for item in params.split(',') {
            let item = item.trim();
            if item.is_empty() {
                continue;
            }

            // Check for wildcard (like T.* or just *)
            if item.contains("*") {
                symbols.insert("*".to_string());
            } else {
                // Keep the full TYPE.SYMBOL format (e.g., "T.AAPL", "Q.MSFT")
                symbols.insert(item.to_string());
            }
        }

        symbols.into_iter().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    #[test]
    fn test_firehose_subscription_no_clients() {
        let mgr = SubscriptionManager::new();
        assert_eq!(mgr.get_firehose_subscription(), "");
    }

    #[test]
    fn test_ms_aggregator_subscription_no_clients() {
        let mgr = SubscriptionManager::new();
        assert_eq!(mgr.get_ms_aggregator_subscription(), "");
    }

    #[test]
    fn test_firehose_subscription_wildcard() {
        let mut mgr = SubscriptionManager::new();
        let client_id = Uuid::new_v4();

        mgr.add_subscription(client_id, "*");

        // Firehose wildcard should NOT include bars
        let firehose_sub = mgr.get_firehose_subscription();
        assert!(firehose_sub.contains("T.*"));
        assert!(firehose_sub.contains("Q.*"));
        assert!(firehose_sub.contains("LULD.*"));
        assert!(firehose_sub.contains("FMV.*"));
        assert!(!firehose_sub.contains("A.*") || firehose_sub == "T.*,Q.*,LULD.*,FMV.*");
    }

    #[test]
    fn test_ms_aggregator_subscription_wildcard() {
        let mut mgr = SubscriptionManager::new();
        let client_id = Uuid::new_v4();

        mgr.add_subscription(client_id, "*");

        // Ms-Aggregator wildcard should only include bars
        let ms_agg_sub = mgr.get_ms_aggregator_subscription();
        assert!(ms_agg_sub.contains("A.*"));
        assert!(ms_agg_sub.contains("AM.*"));
        assert!(!ms_agg_sub.contains("T.*"));
        assert!(!ms_agg_sub.contains("Q.*"));
    }

    #[test]
    fn test_split_subscriptions_by_type() {
        let mut mgr = SubscriptionManager::new();
        let client_id = Uuid::new_v4();

        // Subscribe to mix of bars and non-bars
        mgr.add_subscription(client_id, "T.AAPL,Q.AAPL,A.AAPL,AM.AAPL,100Ms.SPY");

        let firehose_sub = mgr.get_firehose_subscription();
        let ms_agg_sub = mgr.get_ms_aggregator_subscription();

        // Firehose should only have T and Q
        assert!(firehose_sub.contains("T.AAPL"));
        assert!(firehose_sub.contains("Q.AAPL"));
        assert!(!firehose_sub.contains("A.AAPL"));
        assert!(!firehose_sub.contains("AM.AAPL"));
        assert!(!firehose_sub.contains("100Ms.SPY"));

        // Ms-Aggregator should only have bars
        assert!(ms_agg_sub.contains("A.AAPL"));
        assert!(ms_agg_sub.contains("AM.AAPL"));
        assert!(ms_agg_sub.contains("100Ms.SPY"));
        assert!(!ms_agg_sub.contains("T.AAPL"));
        assert!(!ms_agg_sub.contains("Q.AAPL"));
    }

    #[test]
    fn test_only_bar_subscriptions() {
        let mut mgr = SubscriptionManager::new();
        let client_id = Uuid::new_v4();

        mgr.add_subscription(client_id, "A.AAPL,AM.TSLA,250Ms.NVDA");

        let firehose_sub = mgr.get_firehose_subscription();
        let ms_agg_sub = mgr.get_ms_aggregator_subscription();

        // Firehose should be empty
        assert_eq!(firehose_sub, "");

        // Ms-Aggregator should have all bars
        assert!(ms_agg_sub.contains("A.AAPL"));
        assert!(ms_agg_sub.contains("AM.TSLA"));
        assert!(ms_agg_sub.contains("250Ms.NVDA"));
    }

    #[test]
    fn test_only_non_bar_subscriptions() {
        let mut mgr = SubscriptionManager::new();
        let client_id = Uuid::new_v4();

        mgr.add_subscription(client_id, "T.AAPL,Q.TSLA,LULD.NVDA");

        let firehose_sub = mgr.get_firehose_subscription();
        let ms_agg_sub = mgr.get_ms_aggregator_subscription();

        // Firehose should have all
        assert!(firehose_sub.contains("T.AAPL"));
        assert!(firehose_sub.contains("Q.TSLA"));
        assert!(firehose_sub.contains("LULD.NVDA"));

        // Ms-Aggregator should be empty
        assert_eq!(ms_agg_sub, "");
    }

    #[test]
    fn test_multiple_clients_different_types() {
        let mut mgr = SubscriptionManager::new();
        let client1 = Uuid::new_v4();
        let client2 = Uuid::new_v4();

        // Client 1: only trades
        mgr.add_subscription(client1, "T.AAPL");

        // Client 2: only bars
        mgr.add_subscription(client2, "A.AAPL");

        let firehose_sub = mgr.get_firehose_subscription();
        let ms_agg_sub = mgr.get_ms_aggregator_subscription();

        // Both should have their respective subscriptions
        assert!(firehose_sub.contains("T.AAPL"));
        assert!(ms_agg_sub.contains("A.AAPL"));
    }
}