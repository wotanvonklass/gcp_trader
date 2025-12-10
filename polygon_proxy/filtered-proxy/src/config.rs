use anyhow::Result;
use std::env;

#[derive(Debug, Clone)]
pub struct Config {
    pub firehose_url: String,
    pub ms_aggregator_url: String,
    pub polygon_api_key: String,
    pub stocks_port: u16,
    pub log_level: String,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        dotenv::dotenv().ok();

        Ok(Config {
            firehose_url: env::var("FIREHOSE_URL")
                .unwrap_or_else(|_| "ws://localhost:8767".to_string()),
            ms_aggregator_url: env::var("MS_AGGREGATOR_URL")
                .unwrap_or_else(|_| "ws://localhost:8768".to_string()),
            polygon_api_key: env::var("POLYGON_API_KEY")
                .unwrap_or_else(|_| "EdwfnNM3E6Jql9NOo8TN8NAbaIHpc6ha".to_string()),
            stocks_port: env::var("FILTERED_PROXY_PORT")
                .unwrap_or_else(|_| "8765".to_string())
                .parse()?,
            log_level: env::var("LOG_LEVEL")
                .unwrap_or_else(|_| "info".to_string()),
        })
    }
}