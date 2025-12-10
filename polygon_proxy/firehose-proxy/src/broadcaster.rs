use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex};
use tracing::{debug, info};
use uuid::Uuid;

pub type ClientId = Uuid;

/// Simple broadcaster that sends all messages to all connected clients
pub struct Broadcaster {
    clients: Arc<Mutex<HashMap<ClientId, mpsc::Sender<String>>>>,
}

impl Broadcaster {
    pub fn new() -> Self {
        Self {
            clients: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    #[allow(dead_code)]
    pub fn get_clients(&self) -> Arc<Mutex<HashMap<ClientId, mpsc::Sender<String>>>> {
        self.clients.clone()
    }

    pub async fn add_client(&self, client_id: ClientId, tx: mpsc::Sender<String>) {
        let mut clients = self.clients.lock().await;
        clients.insert(client_id, tx);
        info!("Client {} added to broadcast list ({} total)", client_id, clients.len());
    }

    pub async fn remove_client(&self, client_id: ClientId) {
        let mut clients = self.clients.lock().await;
        clients.remove(&client_id);
        info!("Client {} removed from broadcast list ({} remaining)", client_id, clients.len());
    }

    pub async fn broadcast(&self, message: String) {
        let clients = self.clients.lock().await;
        let client_count = clients.len();

        if client_count == 0 {
            return;
        }

        debug!("Broadcasting message to {} clients", client_count);

        // Broadcast to all clients
        // Use try_send for non-blocking, but log warnings for dropped messages
        let mut send_count = 0;
        let mut fail_count = 0;
        for (client_id, tx) in clients.iter() {
            match tx.try_send(message.clone()) {
                Ok(_) => send_count += 1,
                Err(e) => {
                    fail_count += 1;
                    // This will happen if client can't keep up with the data rate
                    // Client should either increase buffer or filter more aggressively
                    debug!("Client {} channel full, dropping message: {}", client_id, e);
                }
            }
        }

        if fail_count > 0 && fail_count % 100 == 0 {
            info!("Broadcaster stats: {} sent, {} dropped", send_count, fail_count);
        }
    }

    #[allow(dead_code)]
    pub async fn client_count(&self) -> usize {
        self.clients.lock().await.len()
    }
}
