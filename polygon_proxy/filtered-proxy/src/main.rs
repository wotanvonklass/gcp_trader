mod client_handler;
mod config;
mod fake_data_generator;
mod router;
mod subscription_manager;
mod types;
mod upstream;

use anyhow::Result;
use client_handler::ClientHandler;
use config::Config;
use fake_data_generator::FakeDataGenerator;
use router::Router;
use std::sync::Arc;
use subscription_manager::SubscriptionManager;
use tokio::sync::{mpsc, Mutex};
use tracing::info;
use types::Cluster;
use upstream::UpstreamConnection;

#[tokio::main]
async fn main() -> Result<()> {
    // Load configuration
    let config = Config::from_env()?;

    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(format!("polygon_proxy={}", config.log_level))
        .init();

    info!("Starting Polygon Filtered WebSocket Proxy");
    info!("Firehose URL: {}", config.firehose_url);
    info!("API Key: {}...", &config.polygon_api_key[..8]);

    // Start stocks proxy
    start_cluster_proxy(Cluster::Stocks, config).await
}

async fn start_cluster_proxy(cluster: Cluster, config: Config) -> Result<()> {
    info!("Starting {} proxy on port {}", cluster, cluster.port(&config));
    info!("Firehose URL: {}", config.firehose_url);
    info!("Ms-Aggregator URL: {}", config.ms_aggregator_url);

    // Create shared subscription manager
    let subscriptions = Arc::new(Mutex::new(SubscriptionManager::new()));

    // Create channels for upstream communication
    // Firehose: for trades, quotes, etc. (non-bar data)
    let (firehose_tx, mut firehose_rx) = mpsc::channel(100);
    let (firehose_cmd_tx, firehose_cmd_rx) = mpsc::channel(100);

    // Ms-Aggregator: for all bar data (A.*, AM.*, *Ms.*)
    let (ms_agg_tx, mut ms_agg_rx) = mpsc::channel(100);
    let (ms_agg_cmd_tx, ms_agg_cmd_rx) = mpsc::channel(100);

    // Start client handler (with both upstream command channels)
    let client_handler = ClientHandler::new(
        cluster,
        cluster.port(&config),
        subscriptions.clone(),
        firehose_cmd_tx.clone(),
        ms_agg_cmd_tx.clone(),
    );

    let clients = client_handler.get_clients();

    tokio::spawn(async move {
        if let Err(e) = client_handler.run().await {
            tracing::error!("{} client handler error: {}", cluster, e);
        }
    });

    // Start upstream connection to firehose (non-bar data)
    let firehose_upstream = UpstreamConnection::new(
        cluster,
        config.firehose_url.clone(),
        config.polygon_api_key.clone(),
        firehose_tx.clone(),
        firehose_cmd_rx,
    );

    tokio::spawn(async move {
        firehose_upstream.run().await;
    });

    // Start upstream connection to ms-aggregator (bar data)
    let ms_agg_upstream = UpstreamConnection::new(
        cluster,
        config.ms_aggregator_url.clone(),
        config.polygon_api_key.clone(),
        ms_agg_tx.clone(),
        ms_agg_cmd_rx,
    );

    tokio::spawn(async move {
        ms_agg_upstream.run().await;
    });

    // Start fake data generator (sends to same channels as real upstreams)
    let fake_generator = FakeDataGenerator::new(
        firehose_tx.clone(),
        ms_agg_tx.clone(),
        subscriptions.clone(),
    );

    tokio::spawn(async move {
        fake_generator.start().await;
    });

    info!("Fake data generator started (subscribe to T.FAKETICKER, Q.FAKETICKER, A.FAKETICKER, or AM.FAKETICKER)");

    // Start router
    let router = Router::new(subscriptions.clone(), clients);

    // Route messages from BOTH upstreams to clients
    loop {
        tokio::select! {
            Some(message) = firehose_rx.recv() => {
                router.route_message(message).await;
            }
            Some(message) = ms_agg_rx.recv() => {
                router.route_message(message).await;
            }
            else => break,
        }
    }

    Ok(())
}
