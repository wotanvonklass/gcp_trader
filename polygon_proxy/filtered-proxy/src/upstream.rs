use crate::types::Cluster;
use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use tokio::sync::mpsc;
use tokio::time::{interval, Duration};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{debug, error, info, warn};

pub struct UpstreamConnection {
    cluster: Cluster,
    firehose_url: String,
    api_key: String,
    tx: mpsc::Sender<String>,
    rx_cmd: mpsc::Receiver<String>,
}

impl UpstreamConnection {
    pub fn new(
        cluster: Cluster,
        firehose_url: String,
        api_key: String,
        tx: mpsc::Sender<String>,
        rx_cmd: mpsc::Receiver<String>,
    ) -> Self {
        Self {
            cluster,
            firehose_url,
            api_key,
            tx,
            rx_cmd,
        }
    }

    pub async fn run(mut self) {
        loop {
            if let Err(e) = self.connect_and_forward().await {
                error!("{} upstream connection error: {}", self.cluster, e);
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        }
    }

    async fn connect_and_forward(&mut self) -> Result<()> {
        // Connect to upstream (firehose or ms-aggregator)
        info!("Connecting to upstream at {}", self.firehose_url);

        let (ws_stream, _) = connect_async(&self.firehose_url).await?;
        let (mut write, mut read) = ws_stream.split();

        info!("{} connected to upstream", self.cluster);

        // Authenticate with upstream
        let auth_msg = serde_json::json!({
            "action": "auth",
            "params": self.api_key
        });
        write.send(Message::Text(auth_msg.to_string())).await?;
        debug!("{} sent auth to upstream", self.cluster);

        // Simple ping every 30 seconds to keep connection alive
        let mut ping_interval = interval(Duration::from_secs(30));

        loop {
            tokio::select! {
                // Forward messages from firehose to router
                Some(msg) = read.next() => {
                    match msg? {
                        Message::Text(text) => {
                            debug!("{} received: {}", self.cluster, text);

                            // Forward all messages from firehose to router (router will filter per-client)
                            let _ = self.tx.send(text).await;
                        }
                        Message::Close(_) => {
                            warn!("{} firehose connection closed", self.cluster);
                            break;
                        }
                        Message::Ping(data) => {
                            // Respond to ping with pong
                            write.send(Message::Pong(data)).await?;
                        }
                        _ => {} // Ignore binary, pong
                    }
                }

                // Handle commands from router (client subscriptions)
                Some(cmd) = self.rx_cmd.recv() => {
                    // For ms-aggregator, forward subscription messages so it knows what to generate
                    // For firehose, we still forward (though firehose is subscribed to *)
                    debug!("{} forwarding subscription to upstream: {}", self.cluster, cmd);
                    if let Err(e) = write.send(Message::Text(cmd)).await {
                        warn!("{} failed to send subscription to upstream: {}", self.cluster, e);
                        break;
                    }
                }

                // Send ping to keep alive
                _ = ping_interval.tick() => {
                    if write.send(Message::Ping(vec![])).await.is_err() {
                        warn!("{} failed to send ping", self.cluster);
                        break;
                    }
                    debug!("{} sent ping", self.cluster);
                }
            }
        }

        Ok(())
    }
}