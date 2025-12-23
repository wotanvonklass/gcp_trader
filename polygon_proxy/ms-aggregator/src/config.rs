use anyhow::{Context, Result};
use serde::Deserialize;
use std::env;

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    /// URL of the firehose proxy to connect to
    pub firehose_url: String,

    /// Polygon API key for authentication
    pub polygon_api_key: String,

    /// Port for the ms-aggregator WebSocket server
    pub aggregator_port: u16,

    /// Minimum interval in milliseconds
    pub min_interval_ms: u64,

    /// Maximum interval in milliseconds
    pub max_interval_ms: u64,

    /// Timer check interval in milliseconds
    pub timer_interval_ms: u64,

    /// Bar emission delay in milliseconds
    pub bar_delay_ms: u64,

    /// Log level (trace, debug, info, warn, error)
    pub log_level: String,

    /// Enable fake data generation for testing
    pub enable_fake_data: bool,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        dotenv::dotenv().ok();

        let firehose_url = env::var("FIREHOSE_URL")
            .context("FIREHOSE_URL must be set")?;

        let polygon_api_key = env::var("POLYGON_API_KEY")
            .context("POLYGON_API_KEY must be set")?;

        let aggregator_port = env::var("AGGREGATOR_PORT")
            .unwrap_or_else(|_| "8768".to_string())
            .parse()
            .context("AGGREGATOR_PORT must be a valid port number")?;

        let min_interval_ms = env::var("MIN_INTERVAL_MS")
            .unwrap_or_else(|_| "1".to_string())
            .parse()
            .context("MIN_INTERVAL_MS must be a valid number")?;

        let max_interval_ms = env::var("MAX_INTERVAL_MS")
            .unwrap_or_else(|_| "60000".to_string())
            .parse()
            .context("MAX_INTERVAL_MS must be a valid number")?;

        let timer_interval_ms = env::var("TIMER_INTERVAL_MS")
            .unwrap_or_else(|_| "10".to_string())
            .parse()
            .context("TIMER_INTERVAL_MS must be a valid number")?;

        let bar_delay_ms = env::var("BAR_DELAY_MS")
            .unwrap_or_else(|_| "20".to_string())
            .parse()
            .context("BAR_DELAY_MS must be a valid number")?;

        let log_level = env::var("LOG_LEVEL")
            .unwrap_or_else(|_| "info".to_string());

        let enable_fake_data = env::var("ENABLE_FAKE_DATA")
            .map(|v| v == "true" || v == "1")
            .unwrap_or(false);

        Ok(Config {
            firehose_url,
            polygon_api_key,
            aggregator_port,
            min_interval_ms,
            max_interval_ms,
            timer_interval_ms,
            bar_delay_ms,
            log_level,
            enable_fake_data,
        })
    }

    pub fn validate(&self) -> Result<()> {
        if self.min_interval_ms < 1 {
            anyhow::bail!("min_interval_ms must be at least 1");
        }

        if self.max_interval_ms > 60000 {
            anyhow::bail!("max_interval_ms must not exceed 60000 (60 seconds)");
        }

        if self.min_interval_ms > self.max_interval_ms {
            anyhow::bail!("min_interval_ms must be less than max_interval_ms");
        }

        if self.timer_interval_ms == 0 {
            anyhow::bail!("timer_interval_ms must be greater than 0");
        }

        Ok(())
    }
}
