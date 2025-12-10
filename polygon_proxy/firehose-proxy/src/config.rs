use anyhow::Result;
use std::env;

#[derive(Debug, Clone)]
pub struct Config {
    pub polygon_api_key: String,
    pub polygon_ws_url: String,
    pub proxy_port: u16,
    pub subscribe_data_types: Vec<String>,
    pub log_level: String,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        dotenv::dotenv().ok();

        let data_types = env::var("SUBSCRIBE_DATA_TYPES")
            .unwrap_or_else(|_| "T,A,AM".to_string()) // Trades, Aggregates per second, per minute
            .split(',')
            .map(|s| s.trim().to_string())
            .collect();

        Ok(Config {
            polygon_api_key: env::var("POLYGON_API_KEY")?,
            polygon_ws_url: env::var("POLYGON_WS_URL")
                .unwrap_or_else(|_| "wss://socket.polygon.io/stocks".to_string()),
            proxy_port: env::var("PROXY_PORT")
                .unwrap_or_else(|_| "8767".to_string())
                .parse()?,
            subscribe_data_types: data_types,
            log_level: env::var("LOG_LEVEL")
                .unwrap_or_else(|_| "info".to_string()),
        })
    }

    pub fn get_subscription_string(&self) -> String {
        // Build Polygon subscription string: "T.*,Q.*,A.*,AM.*"
        self.subscribe_data_types
            .iter()
            .map(|dt| format!("{}.*", dt))
            .collect::<Vec<_>>()
            .join(",")
    }
}
