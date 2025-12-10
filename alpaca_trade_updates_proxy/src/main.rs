use std::collections::HashMap;
use std::env;
use std::sync::Arc;
use tokio::net::TcpListener;
use tokio::sync::Mutex;
use tokio::time::{sleep, Duration};
use tokio_tungstenite::{accept_hdr_async, connect_async, tungstenite::Message, WebSocketStream};
use tokio_tungstenite::tungstenite::handshake::server::{Request, Response};
use futures_util::{SinkExt, StreamExt, stream::SplitSink};
use serde_json::{json, Value};
use uuid::Uuid;
use tokio::net::TcpStream;
use tokio_tungstenite::MaybeTlsStream;

type ClientId = Uuid;
type ClientSender = tokio::sync::mpsc::UnboundedSender<String>;

#[derive(Debug, Clone)]
enum FeedType {
    Paper,
    Live,
}

impl FeedType {
    fn ws_url(&self) -> &str {
        match self {
            FeedType::Paper => "wss://paper-api.alpaca.markets/stream",
            FeedType::Live => "wss://api.alpaca.markets/stream",
        }
    }

    fn name(&self) -> &str {
        match self {
            FeedType::Paper => "PAPER",
            FeedType::Live => "LIVE",
        }
    }

    fn from_path(path: &str) -> Option<Self> {
        match path {
            "/trade-updates-paper" | "/paper" => Some(FeedType::Paper),
            "/trade-updates-live" | "/live" => Some(FeedType::Live),
            _ => None,
        }
    }
}

struct Config {
    alpaca_api_key: String,
    alpaca_secret_key: String,
    alpaca_live_api_key: Option<String>,
    alpaca_live_secret_key: Option<String>,
    proxy_port: u16,
}

impl Config {
    fn from_env() -> Result<Self, String> {
        let alpaca_api_key = env::var("ALPACA_API_KEY")
            .map_err(|_| "ALPACA_API_KEY not set")?;
        let alpaca_secret_key = env::var("ALPACA_SECRET_KEY")
            .map_err(|_| "ALPACA_SECRET_KEY not set")?;
        let alpaca_live_api_key = env::var("ALPACA_LIVE_API_KEY").ok();
        let alpaca_live_secret_key = env::var("ALPACA_LIVE_SECRET_KEY").ok();
        let proxy_port = env::var("PROXY_PORT")
            .unwrap_or_else(|_| "8099".to_string())
            .parse()
            .unwrap_or(8099);

        Ok(Config {
            alpaca_api_key,
            alpaca_secret_key,
            alpaca_live_api_key,
            alpaca_live_secret_key,
            proxy_port,
        })
    }
}

struct UpstreamConnection {
    feed_type: FeedType,
    api_key: String,
    secret_key: String,
    clients: Arc<Mutex<HashMap<ClientId, ClientSender>>>,
}

impl UpstreamConnection {
    fn new(feed_type: FeedType, api_key: String, secret_key: String) -> Self {
        Self {
            feed_type,
            api_key,
            secret_key,
            clients: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    async fn run(&self) {
        let mut backoff = 1;
        loop {
            println!("[{}] Connecting to Alpaca...", self.feed_type.name());

            match self.connect_and_stream().await {
                Ok(_) => {
                    println!("[{}] Connection closed normally", self.feed_type.name());
                    backoff = 1;
                }
                Err(e) => {
                    eprintln!("[{}] Error: {}. Reconnecting in {}s...",
                             self.feed_type.name(), e, backoff);
                    sleep(Duration::from_secs(backoff)).await;
                    backoff = (backoff * 2).min(60);
                }
            }
        }
    }

    async fn connect_and_stream(&self) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let (ws_stream, _) = connect_async(self.feed_type.ws_url()).await?;
        let (mut write, mut read) = ws_stream.split();

        // Authenticate
        let auth_msg = json!({
            "action": "auth",
            "key": self.api_key,
            "secret": self.secret_key
        });
        write.send(Message::Text(auth_msg.to_string())).await?;

        // Wait for auth response
        if let Some(msg) = read.next().await {
            let msg = msg?;
            let text = match msg {
                Message::Text(t) => t,
                Message::Binary(b) => String::from_utf8_lossy(&b).to_string(),
                _ => return Err("Unexpected message type".into()),
            };

            let response: Value = serde_json::from_str(&text)?;

            if response.get("stream") == Some(&json!("authorization")) {
                if let Some(data) = response.get("data") {
                    if data.get("status") == Some(&json!("authorized")) {
                        println!("[{}] Authenticated successfully", self.feed_type.name());

                        // Subscribe to trade_updates stream
                        let listen_msg = json!({
                            "action": "listen",
                            "data": {
                                "streams": ["trade_updates"]
                            }
                        });
                        write.send(Message::Text(listen_msg.to_string())).await?;

                        // Wait for subscription confirmation
                        if let Some(sub_msg) = read.next().await {
                            let sub_msg = sub_msg?;
                            let sub_text = match sub_msg {
                                Message::Text(t) => t,
                                Message::Binary(b) => String::from_utf8_lossy(&b).to_string(),
                                _ => String::new(),
                            };
                            println!("[{}] Subscription response: {}", self.feed_type.name(), sub_text);
                        }
                    } else {
                        return Err("Authentication failed".into());
                    }
                }
            }
        }

        println!("[{}] Connected and subscribed to trade_updates", self.feed_type.name());

        // Wrap write in Arc<Mutex> for sharing with ping task
        let write = Arc::new(Mutex::new(write));
        let write_clone = write.clone();
        let feed_name = self.feed_type.name().to_string();
        let feed_name_clone = feed_name.clone();

        // Spawn ping task - sends ping every 30s to detect dead connections
        let ping_task = tokio::spawn(async move {
            let mut ping_count: u32 = 0;
            loop {
                sleep(Duration::from_secs(30)).await;
                ping_count += 1;
                let mut w = write_clone.lock().await;
                match w.send(Message::Ping(ping_count.to_be_bytes().to_vec())).await {
                    Ok(_) => {
                        println!("[{}] Ping #{} sent", feed_name_clone, ping_count);
                    }
                    Err(e) => {
                        eprintln!("[{}] Ping failed: {} - connection dead", feed_name_clone, e);
                        break;
                    }
                }
            }
        });

        // Stream messages to all clients
        while let Some(msg) = read.next().await {
            match msg {
                Ok(Message::Text(text)) => {
                    self.broadcast_to_clients(&text).await;
                }
                Ok(Message::Binary(bytes)) => {
                    let text = String::from_utf8_lossy(&bytes).to_string();
                    self.broadcast_to_clients(&text).await;
                }
                Ok(Message::Close(_)) => {
                    println!("[{}] Received close message", feed_name);
                    break;
                }
                Ok(Message::Ping(data)) => {
                    let mut w = write.lock().await;
                    let _ = w.send(Message::Pong(data)).await;
                }
                Ok(Message::Pong(data)) => {
                    let ping_id = if data.len() >= 4 {
                        u32::from_be_bytes([data[0], data[1], data[2], data[3]])
                    } else {
                        0
                    };
                    println!("[{}] Pong #{} received - connection alive", feed_name, ping_id);
                }
                Ok(_) => {}
                Err(e) => {
                    eprintln!("[{}] WebSocket error: {}", feed_name, e);
                    ping_task.abort();
                    return Err(e.into());
                }
            }
        }

        ping_task.abort();
        Ok(())
    }

    async fn broadcast_to_clients(&self, message: &str) {
        let clients = self.clients.lock().await;
        let client_count = clients.len();

        // Log the message being broadcast (truncate for readability)
        let preview = if message.len() > 200 {
            format!("{}...", &message[..200])
        } else {
            message.to_string()
        };
        println!("[{}] Broadcasting to {} clients: {}", self.feed_type.name(), client_count, preview);

        let mut disconnected = Vec::new();

        for (client_id, sender) in clients.iter() {
            if sender.send(message.to_string()).is_err() {
                disconnected.push(*client_id);
            }
        }

        drop(clients);

        // Clean up disconnected clients
        if !disconnected.is_empty() {
            let mut clients = self.clients.lock().await;
            for client_id in disconnected {
                clients.remove(&client_id);
                println!("[{}] Removed disconnected client {}", self.feed_type.name(), client_id);
            }
        }
    }

    async fn add_client(&self, client_id: ClientId, sender: ClientSender) {
        let mut clients = self.clients.lock().await;
        clients.insert(client_id, sender);
        println!("[{}] Added client {} (total: {})",
                 self.feed_type.name(), client_id, clients.len());
    }

    async fn remove_client(&self, client_id: ClientId) {
        let mut clients = self.clients.lock().await;
        clients.remove(&client_id);
        println!("[{}] Removed client {} (total: {})",
                 self.feed_type.name(), client_id, clients.len());
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Load .env if present
    dotenv::dotenv().ok();

    let config = Config::from_env()?;

    println!("╔════════════════════════════════════════════════════╗");
    println!("║  Alpaca Trading Updates Proxy                     ║");
    println!("╚════════════════════════════════════════════════════╝");
    println!();
    println!("Listening on: ws://localhost:{}", config.proxy_port);
    println!();
    println!("Available endpoints:");
    println!("  • ws://localhost:{}/trade-updates-paper", config.proxy_port);
    if config.alpaca_live_api_key.is_some() {
        println!("  • ws://localhost:{}/trade-updates-live", config.proxy_port);
    }
    println!();

    // Start upstream connection for paper trading
    let paper_upstream = Arc::new(UpstreamConnection::new(
        FeedType::Paper,
        config.alpaca_api_key.clone(),
        config.alpaca_secret_key.clone(),
    ));
    let paper_upstream_clone = paper_upstream.clone();
    tokio::spawn(async move {
        paper_upstream_clone.run().await;
    });

    // Start upstream connection for live trading (if credentials provided)
    let live_upstream = if let (Some(live_key), Some(live_secret)) =
        (config.alpaca_live_api_key, config.alpaca_live_secret_key) {
        let upstream = Arc::new(UpstreamConnection::new(
            FeedType::Live,
            live_key,
            live_secret,
        ));
        let upstream_clone = upstream.clone();
        tokio::spawn(async move {
            upstream_clone.run().await;
        });
        Some(upstream)
    } else {
        None
    };

    // Start TCP listener
    let listener = TcpListener::bind(format!("0.0.0.0:{}", config.proxy_port)).await?;
    println!("Proxy started successfully!\n");

    while let Ok((stream, addr)) = listener.accept().await {
        println!("New connection from {}", addr);

        let paper = paper_upstream.clone();
        let live = live_upstream.clone();

        tokio::spawn(async move {
            let path = Arc::new(Mutex::new(String::new()));
            let path_clone = path.clone();

            let callback = move |req: &Request, response: Response| {
                let mut p = path_clone.blocking_lock();
                *p = req.uri().path().to_string();
                Ok(response)
            };

            let ws_stream = match accept_hdr_async(stream, callback).await {
                Ok(ws) => ws,
                Err(e) => {
                    eprintln!("WebSocket upgrade failed: {}", e);
                    return;
                }
            };

            let request_path = path.lock().await.clone();
            let client_id = Uuid::new_v4();

            // Determine feed type from path
            let (feed_type, upstream) = match FeedType::from_path(&request_path) {
                Some(FeedType::Paper) => {
                    println!("[PAPER] New client connection: {}", client_id);
                    (FeedType::Paper, paper)
                }
                Some(FeedType::Live) => {
                    if let Some(live) = live {
                        println!("[LIVE] New client connection: {}", client_id);
                        (FeedType::Live, live)
                    } else {
                        eprintln!("Live trading endpoint requested but no live credentials configured");
                        return;
                    }
                }
                None => {
                    eprintln!("Invalid path: {}. Use /trade-updates-paper or /trade-updates-live", request_path);
                    return;
                }
            };

            let (mut client_write, mut client_read) = ws_stream.split();
            let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

            // Wait for auth message from client
            if let Some(msg) = client_read.next().await {
                match msg {
                    Ok(Message::Text(text)) => {
                        if let Ok(value) = serde_json::from_str::<Value>(&text) {
                            if value.get("action") == Some(&json!("auth")) {
                                // Send success response (we accept any credentials)
                                let success = json!([{"T": "success", "msg": "authenticated"}]);
                                if let Err(e) = client_write.send(Message::Text(success.to_string())).await {
                                    eprintln!("[{}] Failed to send auth response: {}", feed_type.name(), e);
                                    return;
                                }
                                println!("[{}] Client {} authenticated", feed_type.name(), client_id);
                            }
                        }
                    }
                    _ => {
                        eprintln!("[{}] Client {} sent invalid auth message", feed_type.name(), client_id);
                        return;
                    }
                }
            }

            // Add client to upstream's client list
            upstream.add_client(client_id, tx).await;

            // Spawn task to receive messages from upstream and send to client
            let client_id_clone = client_id;
            let feed_name = feed_type.name().to_string();
            tokio::spawn(async move {
                while let Some(message) = rx.recv().await {
                    if let Err(e) = client_write.send(Message::Text(message)).await {
                        eprintln!("[{}] Failed to send to client {}: {}", feed_name, client_id_clone, e);
                        break;
                    }
                }
            });

            // Listen for client messages (mostly just keep-alive)
            while let Some(msg) = client_read.next().await {
                match msg {
                    Ok(Message::Close(_)) => {
                        println!("[{}] Client {} closed connection", feed_type.name(), client_id);
                        break;
                    }
                    Ok(Message::Ping(_data)) => {
                        // Echo is handled automatically by tungstenite
                    }
                    Err(e) => {
                        eprintln!("[{}] Client {} error: {}", feed_type.name(), client_id, e);
                        break;
                    }
                    _ => {}
                }
            }

            upstream.remove_client(client_id).await;
            println!("[{}] Client {} disconnected", feed_type.name(), client_id);
        });
    }

    Ok(())
}
