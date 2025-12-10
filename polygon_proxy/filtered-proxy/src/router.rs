use crate::subscription_manager::SubscriptionManager;
use crate::types::ClientId;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, Mutex};
use tracing::{debug, trace};

pub struct Router {
    subscriptions: Arc<Mutex<SubscriptionManager>>,
    clients: Arc<Mutex<HashMap<ClientId, mpsc::Sender<String>>>>,
}

impl Router {
    pub fn new(
        subscriptions: Arc<Mutex<SubscriptionManager>>,
        clients: Arc<Mutex<HashMap<ClientId, mpsc::Sender<String>>>>,
    ) -> Self {
        Self {
            subscriptions,
            clients,
        }
    }

    pub async fn route_message(&self, message: String) {
        // Get per-client filtered messages
        let client_messages = {
            let subs = self.subscriptions.lock().await;
            subs.get_filtered_messages_per_client(&message)
        };

        if client_messages.is_empty() {
            trace!("No clients subscribed for message");
            return;
        }

        debug!("Routing message to {} clients", client_messages.len());

        // Send filtered message to each client
        let clients = self.clients.lock().await;
        for (client_id, filtered_msg) in client_messages {
            if let Some(tx) = clients.get(&client_id) {
                // Non-blocking send
                let _ = tx.try_send(filtered_msg);
            }
        }
    }
}