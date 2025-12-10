use crate::subscription_manager::SubscriptionManager;
use crate::types::{ClientId, ClientMessage, Cluster, StatusMessage};
use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::{accept_async, tungstenite::Message};
use tracing::{debug, error, info, warn};
use uuid::Uuid;

pub struct ClientHandler {
    cluster: Cluster,
    port: u16,
    subscriptions: Arc<Mutex<SubscriptionManager>>,
    clients: Arc<Mutex<HashMap<ClientId, mpsc::Sender<String>>>>,
    firehose_tx: mpsc::Sender<String>,
    ms_agg_tx: mpsc::Sender<String>,
}

impl ClientHandler {
    pub fn new(
        cluster: Cluster,
        port: u16,
        subscriptions: Arc<Mutex<SubscriptionManager>>,
        firehose_tx: mpsc::Sender<String>,
        ms_agg_tx: mpsc::Sender<String>,
    ) -> Self {
        Self {
            cluster,
            port,
            subscriptions,
            clients: Arc::new(Mutex::new(HashMap::new())),
            firehose_tx,
            ms_agg_tx,
        }
    }

    pub async fn run(self) -> Result<()> {
        let addr = format!("0.0.0.0:{}", self.port);
        let listener = TcpListener::bind(&addr).await?;
        info!("{} proxy listening on {}", self.cluster, addr);

        while let Ok((stream, addr)) = listener.accept().await {
            tokio::spawn(self.clone().handle_client(stream, addr));
        }

        Ok(())
    }

    async fn handle_client(self, stream: TcpStream, addr: SocketAddr) {
        let client_id = Uuid::new_v4();
        info!("{} client {} connected from {}", self.cluster, client_id, addr);

        let ws_stream = match accept_async(stream).await {
            Ok(ws) => ws,
            Err(e) => {
                error!("Failed to accept websocket: {}", e);
                return;
            }
        };

        let (mut ws_tx, mut ws_rx) = ws_stream.split();
        let (tx, mut rx) = mpsc::channel(100);

        // Register client
        {
            let mut clients = self.clients.lock().await;
            clients.insert(client_id, tx);
        }

        // Task to forward messages from router to client
        let clients_clone = self.clients.clone();
        let forward_task = tokio::spawn(async move {
            while let Some(msg) = rx.recv().await {
                if ws_tx.send(Message::Text(msg)).await.is_err() {
                    break;
                }
            }
            // Clean up on disconnect
            let mut clients = clients_clone.lock().await;
            clients.remove(&client_id);
        });

        // Handle messages from client
        // Authentication is optional - proxy is local/trusted
        let mut authenticated = false;

        while let Some(Ok(msg)) = ws_rx.next().await {
            match msg {
                Message::Text(text) => {
                    match serde_json::from_str::<ClientMessage>(&text) {
                        Ok(ClientMessage::Auth { params: _ }) => {
                            // Optional auth - accept any key for proxy
                            authenticated = true;
                            let response = vec![StatusMessage {
                                status: "auth_success".to_string(),
                                message: "authenticated".to_string(),
                            }];

                            let response_text = serde_json::to_string(&response).unwrap();
                            if let Some(tx) = self.clients.lock().await.get(&client_id) {
                                let _ = tx.send(response_text).await;
                            }

                            info!("{} client {} authenticated", self.cluster, client_id);
                        }
                        Ok(ClientMessage::Subscribe { params }) => {
                            // Auto-authenticate on first subscribe if not already authenticated
                            if !authenticated {
                                authenticated = true;
                                info!("{} client {} auto-authenticated", self.cluster, client_id);
                            }
                            // Update subscriptions
                            {
                                let mut subs = self.subscriptions.lock().await;
                                subs.add_subscription(client_id, &params);

                                // Send updated subscriptions to BOTH upstreams
                                // Firehose: non-bar data (T.*, Q.*, LULD.*, FMV.*)
                                let firehose_sub = subs.get_firehose_subscription();
                                if !firehose_sub.is_empty() {
                                    let sub_msg = serde_json::to_string(&ClientMessage::Subscribe {
                                        params: firehose_sub,
                                    }).unwrap();
                                    let _ = self.firehose_tx.send(sub_msg).await;
                                }

                                // Ms-Aggregator: bar data (A.*, AM.*, *Ms.*)
                                let ms_agg_sub = subs.get_ms_aggregator_subscription();
                                if !ms_agg_sub.is_empty() {
                                    let sub_msg = serde_json::to_string(&ClientMessage::Subscribe {
                                        params: ms_agg_sub,
                                    }).unwrap();
                                    let _ = self.ms_agg_tx.send(sub_msg).await;
                                }
                            }
                            
                            // Send confirmation
                            let response = vec![StatusMessage {
                                status: "success".to_string(),
                                message: format!("subscribed to {}", params),
                            }];
                            
                            let response_text = serde_json::to_string(&response).unwrap();
                            if let Some(tx) = self.clients.lock().await.get(&client_id) {
                                let _ = tx.send(response_text).await;
                            }
                            
                            debug!("{} client {} subscribed to {}", self.cluster, client_id, params);
                        }
                        Ok(ClientMessage::Unsubscribe { params }) => {
                            // Update subscriptions
                            {
                                let mut subs = self.subscriptions.lock().await;
                                subs.remove_subscription(client_id, &params);

                                // Check for pending unsubscribes
                                let to_unsub = subs.cleanup_pending_unsubs();
                                if !to_unsub.is_empty() {
                                    // Separate bar and non-bar unsubscribes
                                    let firehose_unsubs: Vec<_> = to_unsub.iter()
                                        .filter(|s| !crate::types::is_bar_subscription(s))
                                        .cloned()
                                        .collect();
                                    let ms_agg_unsubs: Vec<_> = to_unsub.iter()
                                        .filter(|s| crate::types::is_bar_subscription(s))
                                        .cloned()
                                        .collect();

                                    // Send to firehose
                                    if !firehose_unsubs.is_empty() {
                                        let unsub_msg = serde_json::to_string(&ClientMessage::Unsubscribe {
                                            params: firehose_unsubs.join(","),
                                        }).unwrap();
                                        let _ = self.firehose_tx.send(unsub_msg).await;
                                    }

                                    // Send to ms-aggregator
                                    if !ms_agg_unsubs.is_empty() {
                                        let unsub_msg = serde_json::to_string(&ClientMessage::Unsubscribe {
                                            params: ms_agg_unsubs.join(","),
                                        }).unwrap();
                                        let _ = self.ms_agg_tx.send(unsub_msg).await;
                                    }
                                }
                            }

                            // Send confirmation
                            let response = vec![StatusMessage {
                                status: "success".to_string(),
                                message: format!("unsubscribed from {}", params),
                            }];

                            let response_text = serde_json::to_string(&response).unwrap();
                            if let Some(tx) = self.clients.lock().await.get(&client_id) {
                                let _ = tx.send(response_text).await;
                            }

                            debug!("{} client {} unsubscribed from {}", self.cluster, client_id, params);
                        }
                        _ => {
                            warn!("{} client {} sent invalid message", self.cluster, client_id);
                        }
                    }
                }
                Message::Close(_) => break,
                Message::Ping(data) => {
                    if let Some(tx) = self.clients.lock().await.get(&client_id) {
                        // Forward ping as text message containing pong
                        let _ = tx.send(format!("pong:{:?}", data)).await;
                    }
                }
                _ => {}
            }
        }

        // Clean up
        forward_task.abort();
        {
            let mut clients = self.clients.lock().await;
            clients.remove(&client_id);
        }
        {
            let mut subs = self.subscriptions.lock().await;
            subs.remove_client(client_id);
        }
        
        info!("{} client {} disconnected", self.cluster, client_id);
    }

    pub fn get_clients(&self) -> Arc<Mutex<HashMap<ClientId, mpsc::Sender<String>>>> {
        self.clients.clone()
    }
}

impl Clone for ClientHandler {
    fn clone(&self) -> Self {
        Self {
            cluster: self.cluster,
            port: self.port,
            subscriptions: self.subscriptions.clone(),
            clients: self.clients.clone(),
            firehose_tx: self.firehose_tx.clone(),
            ms_agg_tx: self.ms_agg_tx.clone(),
        }
    }
}