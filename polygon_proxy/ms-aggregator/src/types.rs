use serde::{Deserialize, Serialize};

/// Polygon trade message
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PolygonTrade {
    #[serde(rename = "sym")]
    pub symbol: String,
    #[serde(rename = "p")]
    pub price: f64,
    #[serde(rename = "s")]
    pub size: u64,
    #[serde(rename = "t")]
    pub timestamp: u64,
    // Optional fields - ignore extra Polygon fields
    #[serde(flatten)]
    pub extra: serde_json::Value,
}

/// Polygon aggregate (1-second bar)
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PolygonAggregate {
    #[serde(rename = "sym")]
    pub symbol: String,
    #[serde(rename = "o")]
    pub open: f64,
    #[serde(rename = "h")]
    pub high: f64,
    #[serde(rename = "l")]
    pub low: f64,
    #[serde(rename = "c")]
    pub close: f64,
    #[serde(rename = "v")]
    pub volume: u64,
    #[serde(rename = "s")]
    pub start_timestamp: u64,
    #[serde(rename = "e")]
    pub end_timestamp: u64,
}

/// Polygon minute aggregate
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PolygonMinuteAggregate {
    #[serde(rename = "sym")]
    pub symbol: String,
    #[serde(rename = "o")]
    pub open: f64,
    #[serde(rename = "h")]
    pub high: f64,
    #[serde(rename = "l")]
    pub low: f64,
    #[serde(rename = "c")]
    pub close: f64,
    #[serde(rename = "v")]
    pub volume: u64,
    #[serde(rename = "s")]
    pub start_timestamp: u64,
    #[serde(rename = "e")]
    pub end_timestamp: u64,
}

/// Generated millisecond bar
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MsBar {
    #[serde(rename = "ev")]
    pub event_type: String, // "MB" for millisecond bar
    #[serde(rename = "sym")]
    pub symbol: String,
    #[serde(rename = "interval")]
    pub interval_ms: u64,
    #[serde(rename = "o")]
    pub open: f64,
    #[serde(rename = "h")]
    pub high: f64,
    #[serde(rename = "l")]
    pub low: f64,
    #[serde(rename = "c")]
    pub close: f64,
    #[serde(rename = "v")]
    pub volume: u64,
    #[serde(rename = "s")]
    pub start_timestamp: u64,
    #[serde(rename = "e")]
    pub end_timestamp: u64,
    #[serde(rename = "n")]
    pub num_trades: u32,
}

/// Client subscription message
#[derive(Debug, Deserialize)]
pub struct SubscriptionMessage {
    pub action: String,
    pub params: String,
}

/// Authentication message
#[derive(Debug, Deserialize)]
pub struct AuthMessage {
    pub action: String,
    pub params: String,
}

/// Bar subscription key
#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub struct BarKey {
    pub symbol: String,
    pub interval_ms: u64,
}

/// Client subscription details
#[derive(Debug, Clone)]
pub struct BarSubscription {
    pub interval_ms: u64,
    pub symbol: String,
}

/// Parse millisecond bar subscription
/// Format: "100Ms.AAPL" or "1000Ms.*"
pub fn parse_ms_subscription(sub: &str) -> Option<BarSubscription> {
    let parts: Vec<&str> = sub.split('.').collect();
    if parts.len() != 2 {
        return None;
    }

    let interval_str = parts[0];
    let symbol = parts[1].to_string();

    // Parse interval (e.g., "100Ms", "5000Ms")
    if !interval_str.ends_with("Ms") {
        return None;
    }

    let interval_ms = interval_str
        .trim_end_matches("Ms")
        .parse::<u64>()
        .ok()?;

    // Validate interval range (1ms to 60000ms)
    if interval_ms < 1 || interval_ms > 60000 {
        return None;
    }

    Some(BarSubscription {
        interval_ms,
        symbol,
    })
}

/// Polygon message types
#[derive(Debug, Deserialize)]
#[serde(tag = "ev")]
pub enum PolygonMessage {
    #[serde(rename = "T")]
    Trade(PolygonTrade),
    #[serde(rename = "A")]
    Aggregate(PolygonAggregate),
    #[serde(rename = "AM")]
    MinuteAggregate(PolygonMinuteAggregate),
    #[serde(other)]
    Other,
}

/// Status message from upstream
#[derive(Debug, Deserialize)]
pub struct StatusMessage {
    pub status: String,
    pub message: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_ms_subscription() {
        assert!(parse_ms_subscription("100Ms.AAPL").is_some());
        assert!(parse_ms_subscription("1Ms.SPY").is_some());
        assert!(parse_ms_subscription("60000Ms.TSLA").is_some());
        assert!(parse_ms_subscription("100Ms.*").is_some());

        // Invalid cases
        assert!(parse_ms_subscription("0Ms.AAPL").is_none()); // < 1
        assert!(parse_ms_subscription("60001Ms.AAPL").is_none()); // > 60000
        assert!(parse_ms_subscription("100S.AAPL").is_none()); // Wrong unit
        assert!(parse_ms_subscription("AAPL").is_none()); // Missing interval
        assert!(parse_ms_subscription("100Ms").is_none()); // Missing symbol
    }

    #[test]
    fn test_parse_ms_subscription_values() {
        let sub = parse_ms_subscription("250Ms.AAPL").unwrap();
        assert_eq!(sub.interval_ms, 250);
        assert_eq!(sub.symbol, "AAPL");

        let sub = parse_ms_subscription("5000Ms.*").unwrap();
        assert_eq!(sub.interval_ms, 5000);
        assert_eq!(sub.symbol, "*");
    }
}
