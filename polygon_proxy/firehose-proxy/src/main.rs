mod broadcaster;
mod client_handler;
mod config;
mod types;
mod upstream;

use anyhow::Result;
use broadcaster::Broadcaster;
use client_handler::ClientHandler;
use config::Config;
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::info;
use upstream::PolygonConnection;

#[tokio::main]
async fn main() -> Result<()> {
    // Load configuration
    let config = Config::from_env()?;

    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(format!("firehose_proxy={}", config.log_level))
        .init();

    info!("Starting Polygon Firehose Proxy");
    info!("Configured data types: {:?}", config.subscribe_data_types);
    info!("Proxy port: {}", config.proxy_port);

    // Create broadcaster
    let broadcaster = Arc::new(Broadcaster::new());

    // Create channel for upstream messages
    // Large buffer to handle high-frequency market data bursts
    let (broadcast_tx, mut broadcast_rx) = mpsc::channel::<String>(100000);

    // Start upstream Polygon connection
    let polygon_conn = PolygonConnection::new(config.clone(), broadcast_tx);
    tokio::spawn(async move {
        polygon_conn.run().await;
    });

    // Start client handler
    let auth_token = "firehose-token-12345".to_string(); // Simple token for demo
    let client_handler = ClientHandler::new(config.proxy_port, broadcaster.clone(), auth_token);
    tokio::spawn(async move {
        if let Err(e) = client_handler.run().await {
            tracing::error!("Client handler error: {}", e);
        }
    });

    // Broadcast loop: forward all upstream messages to all clients
    info!("Broadcast loop started");
    let mut msg_count = 0;
    while let Some(message) = broadcast_rx.recv().await {
        msg_count += 1;
        if msg_count % 1000 == 0 {
            info!("Broadcast loop received {} messages so far", msg_count);
        }
        broadcaster.broadcast(message).await;
    }

    Ok(())
}
