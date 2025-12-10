use crate::broadcaster::Broadcaster;
use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc;
use tokio_tungstenite::{accept_async, tungstenite::Message};
use tracing::{debug, error, info, warn};
use uuid::Uuid;

pub struct ClientHandler {
    port: u16,
    broadcaster: Arc<Broadcaster>,
    auth_token: String,
}

impl ClientHandler {
    pub fn new(port: u16, broadcaster: Arc<Broadcaster>, auth_token: String) -> Self {
        Self {
            port,
            broadcaster,
            auth_token,
        }
    }

    pub async fn run(self) -> Result<()> {
        let addr = format!("0.0.0.0:{}", self.port);
        let listener = TcpListener::bind(&addr).await?;
        info!("Firehose proxy listening on {}", addr);

        let handler = Arc::new(self);

        while let Ok((stream, addr)) = listener.accept().await {
            let handler = handler.clone();
            tokio::spawn(async move {
                if let Err(e) = handler.handle_client(stream, addr).await {
                    error!("Client handler error: {}", e);
                }
            });
        }

        Ok(())
    }

    async fn handle_client(&self, stream: TcpStream, addr: SocketAddr) -> Result<()> {
        let client_id = Uuid::new_v4();
        info!("Client {} connected from {}", client_id, addr);

        let ws_stream = accept_async(stream).await?;
        let (mut ws_tx, mut ws_rx) = ws_stream.split();

        // Create channel for broadcasting to this client
        // Large buffer to handle bursts of market data
        let (tx, mut rx) = mpsc::channel::<String>(100000);

        // Immediately add client to broadcast list (no auth required)
        self.broadcaster.add_client(client_id, tx.clone()).await;
        info!("Client {} added to broadcast list", client_id);

        // Combined task: forward broadcast messages and handle incoming messages
        loop {
            tokio::select! {
                // Forward broadcast messages to client
                Some(msg) = rx.recv() => {
                    if ws_tx.send(Message::Text(msg)).await.is_err() {
                        debug!("Client {} disconnected during send", client_id);
                        break;
                    }
                }

                // Handle incoming messages from client
                Some(msg) = ws_rx.next() => {
                    match msg {
                        Ok(Message::Close(_)) => {
                            info!("Client {} closed connection", client_id);
                            break;
                        }
                        Ok(Message::Ping(data)) => {
                            if ws_tx.send(Message::Pong(data)).await.is_err() {
                                debug!("Client {} disconnected during pong", client_id);
                                break;
                            }
                        }
                        Err(e) => {
                            warn!("WebSocket error for client {}: {}", client_id, e);
                            break;
                        }
                        _ => {
                            // Ignore all other messages (text, pong, binary)
                        }
                    }
                }
            }
        }

        // Cleanup
        self.broadcaster.remove_client(client_id).await;
        info!("Client {} handler terminated", client_id);

        Ok(())
    }
}
