use crate::config::Config;
use crate::types::{PolygonAuth, PolygonSubscribe};
use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::mpsc;
use tokio::time::{interval, Duration};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{debug, error, info, warn};

pub struct PolygonConnection {
    config: Config,
    broadcast_tx: mpsc::Sender<String>,
}

impl PolygonConnection {
    pub fn new(config: Config, broadcast_tx: mpsc::Sender<String>) -> Self {
        Self {
            config,
            broadcast_tx,
        }
    }

    pub async fn run(mut self) {
        loop {
            if let Err(e) = self.connect_and_stream().await {
                error!("Polygon connection error: {}", e);
                tokio::time::sleep(Duration::from_secs(5)).await;
                info!("Reconnecting to Polygon...");
            }
        }
    }

    async fn connect_and_stream(&mut self) -> Result<()> {
        info!("Connecting to Polygon at {}", self.config.polygon_ws_url);

        let (ws_stream, _) = connect_async(&self.config.polygon_ws_url).await?;
        let (mut write, mut read) = ws_stream.split();

        info!("Connected to Polygon, authenticating...");

        // Send authentication
        let auth = PolygonAuth {
            action: "auth".to_string(),
            params: self.config.polygon_api_key.clone(),
        };
        let auth_msg = serde_json::to_string(&auth)?;
        write.send(Message::Text(auth_msg)).await?;

        // Wait for auth response
        if let Some(Ok(Message::Text(msg))) = read.next().await {
            debug!("Auth response: {}", msg);
            if msg.contains("Connected Successfully") || msg.contains("connected") {
                info!("Successfully authenticated with Polygon");
            } else if msg.contains("auth_failed") || msg.contains("unauthorized") {
                error!("Authentication failed: {}", msg);
                return Err(anyhow::anyhow!("Authentication failed"));
            }
        }

        // Subscribe to configured data types with wildcard
        let subscription = self.config.get_subscription_string();
        info!("Subscribing to: {}", subscription);

        let subscribe = PolygonSubscribe {
            action: "subscribe".to_string(),
            params: subscription,
        };

        let sub_msg = serde_json::to_string(&subscribe)?;
        write.send(Message::Text(sub_msg)).await?;
        info!("Subscription sent");

        // Ping interval to keep connection alive
        let mut ping_interval = interval(Duration::from_secs(30));

        // Stream messages
        loop {
            tokio::select! {
                Some(msg) = read.next() => {
                    match msg? {
                        Message::Text(text) => {
                            info!("Received message from Polygon: {}", &text[..text.len().min(200)]);
                            // Broadcast to all connected clients
                            if let Err(e) = self.broadcast_tx.send(text).await {
                                warn!("Failed to broadcast message: {}", e);
                            }
                        }
                        Message::Close(_) => {
                            warn!("Polygon connection closed");
                            break;
                        }
                        Message::Ping(data) => {
                            write.send(Message::Pong(data)).await?;
                        }
                        _ => {}
                    }
                }
                _ = ping_interval.tick() => {
                    if write.send(Message::Ping(vec![])).await.is_err() {
                        warn!("Failed to send ping");
                        break;
                    }
                    debug!("Sent ping to Polygon");
                }
            }
        }

        Ok(())
    }
}
