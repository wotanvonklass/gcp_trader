use crate::config::Config;
use crate::types::{PolygonMessage, PolygonTrade};
use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use serde_json::json;
use tokio::net::TcpStream;
use tokio::sync::mpsc;
use tokio_tungstenite::{connect_async, tungstenite::Message, MaybeTlsStream, WebSocketStream};
use tracing::{debug, error, info, warn};

type WsStream = WebSocketStream<MaybeTlsStream<TcpStream>>;

pub struct UpstreamConnection {
    config: Config,
    trade_tx: mpsc::Sender<PolygonTrade>,
}

impl UpstreamConnection {
    pub fn new(config: Config, trade_tx: mpsc::Sender<PolygonTrade>) -> Self {
        Self { config, trade_tx }
    }

    pub async fn run(&self) -> Result<()> {
        loop {
            info!("Connecting to firehose at {}", self.config.firehose_url);

            match self.connect_and_run().await {
                Ok(_) => {
                    info!("Upstream connection closed normally");
                }
                Err(e) => {
                    error!("Upstream connection error: {}", e);
                }
            }

            // Reconnect after delay
            info!("Reconnecting to firehose in 5 seconds...");
            tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
        }
    }

    async fn connect_and_run(&self) -> Result<()> {
        let (ws_stream, _) = connect_async(&self.config.firehose_url)
            .await
            .context("Failed to connect to firehose")?;

        info!("Connected to firehose proxy");

        let (mut write, mut read) = ws_stream.split();

        // Note: Firehose proxy doesn't require authentication for internal connections
        // It broadcasts data to all connected clients immediately

        // Subscribe to all trades (T.*)
        let subscribe_msg = json!({
            "action": "subscribe",
            "params": "T.*"
        });

        write
            .send(Message::Text(subscribe_msg.to_string()))
            .await
            .context("Failed to send subscribe message")?;

        info!("Subscribed to T.* from firehose, waiting for data...");

        // Process incoming messages
        info!("Starting message receive loop...");
        let mut msg_count = 0;
        while let Some(msg) = read.next().await {
            let msg = msg.context("WebSocket error")?;

            match msg {
                Message::Text(text) => {
                    msg_count += 1;
                    if msg_count % 1000 == 0 {
                        info!("Received {} messages from firehose so far", msg_count);
                    }
                    debug!("RAW MESSAGE: {}", &text[..text.len().min(100)]);
                    self.handle_message(&text).await;
                }
                Message::Close(_) => {
                    info!("Firehose closed connection");
                    break;
                }
                Message::Ping(data) => {
                    write.send(Message::Pong(data)).await.ok();
                }
                _ => {}
            }
        }

        Ok(())
    }

    async fn handle_message(&self, text: &str) {
        // Try to parse as JSON array
        if let Ok(messages) = serde_json::from_str::<Vec<serde_json::Value>>(text) {
            for msg_value in messages {
                match serde_json::from_value::<PolygonMessage>(msg_value.clone()) {
                    Ok(msg) => {
                        match msg {
                            PolygonMessage::Trade(trade) => {
                                debug!(
                                    "Received trade: {} @ {} (size: {})",
                                    trade.symbol, trade.price, trade.size
                                );

                                if let Err(e) = self.trade_tx.send(trade).await {
                                    warn!("Failed to send trade to aggregator: {}", e);
                                }
                            }
                            PolygonMessage::Aggregate(_) => {
                                // We don't aggregate A.* messages, we forward them
                                // This is handled separately in the client handler
                            }
                            PolygonMessage::MinuteAggregate(_) => {
                                // We don't aggregate AM.* messages, we forward them
                                // This is handled separately in the client handler
                            }
                            PolygonMessage::Other => {
                                // Status messages, etc.
                                debug!("Received non-trade message: {:?}", msg_value);
                            }
                        }
                    }
                    Err(e) => {
                        let json_str = serde_json::to_string(&msg_value).unwrap_or_default();
                        let preview = &json_str[..json_str.len().min(100)];
                        debug!("Failed to parse message: {} - Error: {}", preview, e);
                    }
                }
            }
        } else {
            // Single message or status message
            debug!("Received non-JSON-array message: {}", &text[..text.len().min(200)]);
        }
    }
}
