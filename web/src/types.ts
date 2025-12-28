/**
 * Type definitions for Torbi Web dashboard.
 * These mirror the backend API models.
 */

// ==============================================================================
// Pipeline Events
// ==============================================================================

export type PipelineEventType =
  | 'news_received'
  | 'news_decision'
  | 'strategy_spawned'
  | 'order_placed'
  | 'order_filled'
  | 'order_cancelled'
  | 'strategy_stopped'
  | 'manual_exit_requested'
  | 'timer_extend_requested'
  | 'cancel_order_requested'

export interface PipelineEvent {
  id: string
  type: PipelineEventType
  timestamp: string
  news_id: string
  data: Record<string, unknown>
}

// ==============================================================================
// News Events
// ==============================================================================

export interface NewsReceivedData {
  headline: string
  tickers: string[]
  source: string
  pub_time: string
  news_age_ms: number
}

export interface NewsDecisionData {
  decision: 'trade' | 'skip'
  skip_reason?: string
  volume_check_ms?: number
  volume_found?: number
  volume_threshold?: number
}

// ==============================================================================
// Strategy Events
// ==============================================================================

export interface StrategySpawnedData {
  strategy_id: string
  strategy_type: string
  ticker: string
  side: 'long' | 'short'
  position_size_usd: number
  entry_price: number
  exit_delay_seconds: number
  headline?: string
}

export interface StrategyStoppedData {
  strategy_id: string
  reason: string
  pnl?: number
  pnl_percent?: number
  duration_ms?: number
}

// ==============================================================================
// Order Events
// ==============================================================================

export interface OrderPlacedData {
  strategy_id: string
  order_id: string
  alpaca_order_id?: string
  order_role: 'entry' | 'exit'
  side: 'buy' | 'sell'
  order_type: 'market' | 'limit'
  qty: number
  limit_price?: number
}

export interface OrderFilledData {
  strategy_id: string
  order_id: string
  order_role: 'entry' | 'exit'
  fill_price: number
  qty: number
  slippage?: number
}

export interface OrderCancelledData {
  strategy_id: string
  order_id: string
  reason: string
}

// ==============================================================================
// Active Strategy (computed state)
// ==============================================================================

export type StrategyStatus =
  | 'pending_entry'
  | 'in_position'
  | 'pending_exit'
  | 'pending_close'

export interface ActiveStrategy {
  id: string
  news_id: string
  ticker: string
  strategy_type?: string
  side: 'long' | 'short'
  position_size_usd?: number
  status: StrategyStatus
  entry_limit_price?: number
  entry_fill_price?: number
  qty?: number
  current_price?: number
  unrealized_pnl?: number
  unrealized_pnl_percent?: number
  exit_countdown_seconds?: number
  exit_delay_seconds?: number
  spawned_at: string
  entry_filled_at?: string
  headline: string
}

// ==============================================================================
// News Item (aggregated view)
// ==============================================================================

export type FeedItemStatus = 'processing' | 'triggered' | 'skipped'

export interface FeedItem {
  news_id: string
  headline: string
  tickers: string[]
  source: string
  pub_time: string
  news_age_ms: number
  received_at: string
  status: FeedItemStatus
  decision?: 'trade' | 'skip'
  skip_reason?: string
  volume_found?: number
  strategies: FeedItemStrategy[]
}

export interface FeedItemStrategy {
  strategy_id: string
  strategy_type: string
  ticker: string
  status: StrategyStatus | 'completed' | 'cancelled'
  position_size_usd: number
  entry_price: number
  entry_fill_price?: number
  exit_fill_price?: number
  qty?: number
  pnl?: number
  exit_delay_seconds: number
}

export interface PipelineStep {
  label: string
  status: 'pending' | 'complete' | 'active' | 'skipped' | 'error'
  detail?: string
  timestamp?: string
}

// ==============================================================================
// API Response Types
// ==============================================================================

export interface NewsEvent {
  id: string
  headline: string
  tickers: string[]
  pub_time?: string
  decision?: string
  skip_reason?: string
  strategies_spawned: number
  source?: string
  news_age_ms?: number
}

export interface StrategyExecution {
  id: string
  ticker: string
  strategy_type?: string
  strategy_name?: string
  position_size_usd?: number
  entry_price?: number
  exit_price?: number
  qty?: number
  pnl?: number
  status: string
  started_at?: string
  stopped_at?: string
  stop_reason?: string
}

export interface CompletedTrade {
  id: string
  news_id?: string
  ticker: string
  strategy_type?: string
  strategy_name?: string
  position_size_usd?: number
  entry_price: number
  exit_price: number
  entry_time?: string
  exit_time?: string
  qty: number
  pnl: number
  pnl_percent?: number
  started_at?: string
  stopped_at?: string
  stop_reason?: string
  headline?: string
  pub_time?: string
  source?: string
}

export interface HealthResponse {
  status: string
}

export interface DetailedHealthResponse {
  status: string
  uptime_seconds: number
  sse_clients: number
  events_in_buffer: number
  active_strategies: number
  event_counts: Record<string, number>
  components: Record<string, ComponentHealth>
}

export interface ComponentHealth {
  status: string
  uptime?: number
  buffer_size?: number
  max_size?: number
}

export interface LatencyStats {
  avg: number
  p50: number
  p99: number
  max: number
  sample_count: number
}

export interface LatencyResponse {
  news_to_decision: LatencyStats
  decision_to_order: LatencyStats
  order_to_fill: LatencyStats
  total_news_to_fill: LatencyStats
}

export interface SkipAnalysis {
  period: string
  total: number
  triggered: number
  skipped: number
  by_reason: { reason: string; count: number; percentage: number }[]
  near_misses: unknown[]
}

export interface PerformanceStats {
  period: string
  total_trades: number
  total_pnl: number
  win_rate: number
  avg_pnl: number
  by_hour: { hour: number; trades: number; pnl: number; win_rate: number }[]
  by_strategy: { strategy: string; trades: number; pnl: number; win_rate: number }[]
}

export interface SummaryStats {
  period: string
  news: {
    total: number
    triggered: number
    triggered_percent: number
    skipped: number
    pending: number
    skip_reasons?: Record<string, number>
  }
  strategies: {
    total_spawned: number
    total: number
    active: number
    closed: number
  }
  pnl: {
    total: number
    trade_count: number
    win_rate: number
    open_trades: number
    gross_profit: number
    gross_loss: number
    winners: number
    losers: number
  }
}

// Health status response
export interface HealthStatus {
  status: string
  uptime: number
  started_at: string
  news_count?: number
  event_count?: number
  active_strategies?: number
  trading_active?: boolean
  sse_subscribers?: number
  environment?: string
}

// ==============================================================================
// SSE Message Types
// ==============================================================================

export interface SSEConnectedMessage {
  status: 'connected'
  timestamp: string
}

export interface SSEInitialStateMessage {
  events: PipelineEvent[]
}

export interface SSEActiveStrategiesMessage {
  strategies: ActiveStrategy[]
}

export interface SSEHeartbeatMessage {
  timestamp: string
}

// ==============================================================================
// Trade Detail & Chart Types
// ==============================================================================

export interface OHLCVBar {
  t: number // timestamp (ms)
  o: number // open
  h: number // high
  l: number // low
  c: number // close
  v: number // volume
  vw?: number // volume-weighted avg price
  n?: number // number of trades
}

export interface MarketBarsResponse {
  ticker: string
  status: string
  resultsCount: number
  results: OHLCVBar[]
}

export interface StrategyDetail {
  id: string
  news_id: string
  ticker: string
  strategy_type?: string
  strategy_name?: string
  position_size_usd?: number
  limit_entry_price?: number
  entry_price?: number
  exit_price?: number
  entry_time?: string
  exit_time?: string
  qty?: number
  pnl?: number
  pnl_percent?: number
  status: string
  started_at?: string
  stopped_at?: string
  stop_reason?: string
  headline?: string
  pub_time?: string
  source?: string
}
