use crate::subscription_manager::SubscriptionManager;
use serde_json::json;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::{mpsc, Mutex};
use tokio::time::{interval, Duration};
use tracing::debug;

pub struct FakeDataGenerator {
    firehose_tx: mpsc::Sender<String>,
    ms_agg_tx: mpsc::Sender<String>,
    subscriptions: Arc<Mutex<SubscriptionManager>>,
}

impl FakeDataGenerator {
    pub fn new(
        firehose_tx: mpsc::Sender<String>,
        ms_agg_tx: mpsc::Sender<String>,
        subscriptions: Arc<Mutex<SubscriptionManager>>,
    ) -> Self {
        Self {
            firehose_tx,
            ms_agg_tx,
            subscriptions,
        }
    }

    pub async fn start(&self) {
        let mut tick_interval = interval(Duration::from_millis(100));
        let mut price = 100.0;

        debug!("Fake data generator started (100ms interval)");

        loop {
            tick_interval.tick().await;

            // Random walk price
            let change = (rand::random::<f64>() - 0.5) * 2.0;
            price = (price + change).max(50.0).min(150.0); // Keep in reasonable range

            let subs = self.subscriptions.lock().await;

            // Only generate Trade if someone subscribed to T.FAKETICKER
            if subs.has_subscription("T.FAKETICKER") {
                let trade_msg = json!([{
                    "ev": "T",
                    "sym": "FAKETICKER",
                    "p": price,
                    "s": 100,
                    "t": now_millis(),
                    "c": [14, 41], // Sale condition codes
                    "i": "12345",
                    "x": 4,
                    "z": 3
                }]);

                if let Ok(msg_str) = serde_json::to_string(&trade_msg) {
                    let _ = self.firehose_tx.send(msg_str).await;
                }
            }

            // Only generate Quote if someone subscribed to Q.FAKETICKER
            if subs.has_subscription("Q.FAKETICKER") {
                let quote_msg = json!([{
                    "ev": "Q",
                    "sym": "FAKETICKER",
                    "bp": price - 0.01,
                    "ap": price + 0.01,
                    "bs": 100,
                    "as": 100,
                    "t": now_millis(),
                    "x": 4,
                    "z": 3
                }]);

                if let Ok(msg_str) = serde_json::to_string(&quote_msg) {
                    let _ = self.firehose_tx.send(msg_str).await;
                }
            }

            // Only generate Bar if someone subscribed to A.FAKETICKER
            if subs.has_subscription("A.FAKETICKER") {
                let bar_msg = json!([{
                    "ev": "A",
                    "sym": "FAKETICKER",
                    "o": price - 0.5,
                    "h": price + 1.0,
                    "l": price - 1.0,
                    "c": price,
                    "v": 1000,
                    "s": now_seconds(),
                    "vw": price
                }]);

                if let Ok(msg_str) = serde_json::to_string(&bar_msg) {
                    let _ = self.ms_agg_tx.send(msg_str).await;
                }
            }

            // Only generate Minute Bar if someone subscribed to AM.FAKETICKER
            if subs.has_subscription("AM.FAKETICKER") {
                let min_bar_msg = json!([{
                    "ev": "AM",
                    "sym": "FAKETICKER",
                    "o": price - 0.5,
                    "h": price + 1.0,
                    "l": price - 1.0,
                    "c": price,
                    "v": 10000,
                    "s": now_seconds(),
                    "vw": price
                }]);

                if let Ok(msg_str) = serde_json::to_string(&min_bar_msg) {
                    let _ = self.ms_agg_tx.send(msg_str).await;
                }
            }
        }
    }
}

// Helper to get current time in milliseconds
fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64
}

// Helper to get current time in seconds
fn now_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}
