use serde::{Deserialize, Serialize};

// Polygon authentication message
#[derive(Debug, Serialize)]
pub struct PolygonAuth {
    pub action: String,
    pub params: String,
}

// Polygon subscription message
#[derive(Debug, Serialize)]
pub struct PolygonSubscribe {
    pub action: String,
    pub params: String,
}

// Client messages (simplified - only auth and subscribe to *)
#[derive(Debug, Deserialize)]
#[serde(tag = "action")]
pub enum ClientMessage {
    #[serde(rename = "auth")]
    Auth { token: String },
    #[serde(rename = "subscribe")]
    Subscribe,
}

// Status message to clients
#[derive(Debug, Serialize)]
pub struct StatusMessage {
    pub status: String,
    pub message: String,
}
