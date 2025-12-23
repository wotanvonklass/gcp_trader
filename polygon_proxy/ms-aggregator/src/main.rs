mod bar_aggregator;
mod config;
mod subscription_manager;
mod trade_buffer;
mod types;
mod upstream;

use anyhow::{Context, Result};
use config::Config;
use dashmap::DashMap;
use std::sync::Arc;
use subscription_manager::{ClientId, SubscriptionManager};
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tracing::{error, info};
use tracing_subscriber::{fmt, EnvFilter};
use types::{MsBar, PolygonTrade};

type ClientSenders = Arc<DashMap<ClientId, mpsc::Sender<MsBar>>>;

#[tokio::main]
async fn main() -> Result<()> {
    // Load configuration
    let config = Config::from_env().context("Failed to load configuration")?;
    config.validate().context("Invalid configuration")?;

    // Initialize logging
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(&config.log_level));

    fmt()
        .with_env_filter(filter)
        .with_target(false)
        .with_thread_ids(false)
        .init();

    info!("Starting Polygon Millisecond Bar Aggregator");
    info!("Firehose URL: {}", config.firehose_url);
    info!("Aggregator Port: {}", config.aggregator_port);
    info!(
        "Interval Range: {}ms - {}ms",
        config.min_interval_ms, config.max_interval_ms
    );
    info!("Timer Interval: {}ms", config.timer_interval_ms);
    info!("Bar Delay: {}ms", config.bar_delay_ms);

    // Create subscription manager
    let subscription_manager = Arc::new(SubscriptionManager::new(
        config.min_interval_ms,
        config.max_interval_ms,
        config.bar_delay_ms,
    ));

    // Create client senders map
    let client_senders: ClientSenders = Arc::new(DashMap::new());

    // Create channels with larger buffer to handle bursts
    // Note: Most trades will be filtered out by early-exit in process_trade()
    let (trade_tx, mut trade_rx) = mpsc::channel::<PolygonTrade>(100000);

    // Start upstream connection to firehose (or fake data generator for testing)
    let upstream_handle = if config.enable_fake_data {
        info!("🧪 FAKE DATA MODE: Generating test trades for FAKETICKER");
        let trade_tx_clone = trade_tx.clone();
        tokio::spawn(async move {
            use std::time::{SystemTime, UNIX_EPOCH};
            let mut interval = tokio::time::interval(tokio::time::Duration::from_millis(50));
            let mut price = 100.0_f64;

            loop {
                interval.tick().await;

                // Random walk price
                let change = (rand::random::<f64>() - 0.5) * 0.5;
                price = (price + change).max(90.0).min(110.0);

                let now_ms = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_millis() as u64;

                let trade = PolygonTrade {
                    symbol: "FAKETICKER".to_string(),
                    price,
                    size: 100,
                    timestamp: now_ms,
                    extra: serde_json::Value::Null,
                };

                if trade_tx_clone.send(trade).await.is_err() {
                    break;
                }
            }
        })
    } else {
        let upstream = upstream::UpstreamConnection::new(config.clone(), trade_tx);
        tokio::spawn(async move {
            if let Err(e) = upstream.run().await {
                error!("Upstream connection failed: {}", e);
            }
        })
    };

    // Start trade processor task
    let subscription_manager_clone = subscription_manager.clone();
    let trade_processor_handle = tokio::spawn(async move {
        while let Some(trade) = trade_rx.recv().await {
            subscription_manager_clone.process_trade(&trade);
        }
    });

    // Start timer task to check and emit bars
    let subscription_manager_clone = subscription_manager.clone();
    let client_senders_clone = client_senders.clone();
    let timer_interval_ms = config.timer_interval_ms;
    let timer_handle = tokio::spawn(async move {
        let mut interval = tokio::time::interval(tokio::time::Duration::from_millis(
            timer_interval_ms,
        ));
        let mut tick_count: u64 = 0;
        // Prune every 10 seconds (10000ms / timer_interval_ms ticks)
        let prune_interval = 10000 / timer_interval_ms;

        loop {
            interval.tick().await;
            tick_count += 1;

            // Check all aggregators and emit ready bars
            let bars = subscription_manager_clone.check_and_emit_bars();

            for (client_id, bar) in bars {
                if let Some(sender) = client_senders_clone.get(&client_id) {
                    if sender.send(bar).await.is_err() {
                        // Client disconnected, remove sender
                        client_senders_clone.remove(&client_id);
                    }
                }
            }

            // Periodically prune old trades from buffer and log stats (every 10 seconds)
            if tick_count % prune_interval == 0 {
                subscription_manager_clone.prune_buffer();

                let stats = subscription_manager_clone.stats();
                info!(
                    "Stats: {} aggregators, {} clients, buffer: {} symbols, {} trades",
                    stats.num_aggregators, stats.num_clients,
                    stats.buffer_symbols, stats.buffer_trades
                );
            }
        }
    });

    // Start client WebSocket server
    let listener = TcpListener::bind(format!("0.0.0.0:{}", config.aggregator_port))
        .await
        .context("Failed to bind to port")?;

    info!(
        "WebSocket server listening on port {}",
        config.aggregator_port
    );

    // Start accepting client connections
    let client_handle = tokio::spawn(async move {
        loop {
            match listener.accept().await {
                Ok((stream, addr)) => {
                    info!("New client connection from {}", addr);
                    let subscription_manager = subscription_manager.clone();
                    let client_senders = client_senders.clone();

                    tokio::spawn(async move {
                        if let Err(e) = handle_client_connection(
                            stream,
                            addr,
                            subscription_manager,
                            client_senders,
                        )
                        .await
                        {
                            error!("Client handler error: {}", e);
                        }
                    });
                }
                Err(e) => {
                    error!("Failed to accept client: {}", e);
                }
            }
        }
    });

    // Wait for all tasks
    tokio::select! {
        _ = upstream_handle => error!("Upstream task exited"),
        _ = trade_processor_handle => error!("Trade processor task exited"),
        _ = timer_handle => error!("Timer task exited"),
        _ = client_handle => error!("Client handler task exited"),
    }

    Ok(())
}

async fn handle_client_connection(
    stream: tokio::net::TcpStream,
    addr: std::net::SocketAddr,
    subscription_manager: Arc<SubscriptionManager>,
    client_senders: ClientSenders,
) -> Result<()> {
    use crate::types::{AuthMessage, SubscriptionMessage};
    use futures_util::{SinkExt, StreamExt};
    use tokio::sync::mpsc;
    use tokio_tungstenite::tungstenite::Message;
    use tracing::{debug, error, info, warn};
    use uuid::Uuid;

    let ws_stream = tokio_tungstenite::accept_async(stream)
        .await
        .context("WebSocket handshake failed")?;

    let client_id = Uuid::new_v4();
    info!("Client {} ({}) connected", client_id, addr);

    let (mut write, mut read) = ws_stream.split();

    // Create channel for sending bars to this client
    let (bar_tx, mut bar_rx) = mpsc::channel::<MsBar>(1000);

    // Register client sender
    client_senders.insert(client_id, bar_tx);

    let mut authenticated = false;

    // Spawn task to send bars to client
    let client_id_for_sender = client_id;
    let mut write_handle = tokio::spawn(async move {
        while let Some(bar) = bar_rx.recv().await {
            let msg = serde_json::to_string(&vec![bar]).unwrap();
            if write.send(Message::Text(msg)).await.is_err() {
                warn!("Failed to send bar to client {}", client_id_for_sender);
                break;
            }
        }
    });

    // Process client messages
    loop {
        tokio::select! {
            Some(msg) = read.next() => {
                let msg = match msg {
                    Ok(m) => m,
                    Err(e) => {
                        error!("WebSocket error: {}", e);
                        break;
                    }
                };

                match msg {
                    Message::Text(text) => {
                        debug!("Client {} sent: {}", client_id, text);

                        // Try to parse as auth message
                        if !authenticated {
                            if let Ok(auth) = serde_json::from_str::<AuthMessage>(&text) {
                                if auth.action == "auth" {
                                    // For now, accept any auth
                                    // In production, validate the API key
                                    authenticated = true;

                                    info!("Client {} authenticated", client_id);
                                    continue;
                                }
                            }

                            warn!("Client {} not authenticated", client_id);
                            continue;
                        }

                        // Try to parse as subscription message
                        if let Ok(sub) = serde_json::from_str::<SubscriptionMessage>(&text) {
                            match sub.action.as_str() {
                                "subscribe" => {
                                    match subscription_manager.subscribe(client_id, &sub.params) {
                                        Ok(subscribed) => {
                                            info!(
                                                "Client {} subscribed to: {}{}",
                                                client_id,
                                                subscribed.join(", "),
                                                sub.since.map(|s| format!(" (since={})", s)).unwrap_or_default()
                                            );

                                            // If 'since' provided, replay buffered bars
                                            if let Some(since_ms) = sub.since {
                                                if let Some(sender) = client_senders.get(&client_id) {
                                                    for sub_str in &subscribed {
                                                        if let Some(bar_sub) = types::parse_ms_subscription(sub_str) {
                                                            let bars = subscription_manager.generate_bars_since(
                                                                &bar_sub.symbol,
                                                                bar_sub.interval_ms,
                                                                since_ms,
                                                            );
                                                            if !bars.is_empty() {
                                                                info!(
                                                                    "Replaying {} buffered bars for {}.{}Ms",
                                                                    bars.len(), bar_sub.symbol, bar_sub.interval_ms
                                                                );
                                                                // Send each bar to the client
                                                                for bar in bars {
                                                                    let _ = sender.send(bar).await;
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        Err(e) => {
                                            warn!("Client {} subscription error: {}", client_id, e);
                                        }
                                    }
                                }
                                "unsubscribe" => {
                                    if let Err(e) = subscription_manager.unsubscribe(client_id, &sub.params) {
                                        warn!("Client {} unsubscribe error: {}", client_id, e);
                                    } else {
                                        info!("Client {} unsubscribed from: {}", client_id, sub.params);
                                    }
                                }
                                _ => {
                                    warn!("Unknown action from client {}: {}", client_id, sub.action);
                                }
                            }
                        }
                    }
                    Message::Close(_) => {
                        info!("Client {} disconnected", client_id);
                        break;
                    }
                    Message::Ping(_) => {
                        // Ping/pong is handled automatically by tokio-tungstenite
                    }
                    _ => {}
                }
            }
            _ = &mut write_handle => {
                info!("Client {} write task ended", client_id);
                break;
            }
        }
    }

    // Clean up
    client_senders.remove(&client_id);
    subscription_manager.remove_client(client_id);
    info!("Client {} cleaned up", client_id);

    Ok(())
}
