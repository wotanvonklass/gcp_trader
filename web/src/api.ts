/**
 * API client for Pako News API.
 */

import type {
  NewsEvent,
  StrategyExecution,
  DetailedHealthResponse,
  HealthStatus,
  LatencyResponse,
  SkipAnalysis,
  PerformanceStats,
  SummaryStats,
  ActiveStrategy,
  PipelineEvent,
  StrategyDetail,
  MarketBarsResponse,
} from './types'

// Configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8100'
const API_KEY = import.meta.env.VITE_API_KEY || ''

// ==============================================================================
// HTTP Client
// ==============================================================================

async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
    ...options.headers,
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`API Error ${response.status}: ${error}`)
  }

  return response.json()
}

// ==============================================================================
// Health Endpoints
// ==============================================================================

export async function getHealth(): Promise<HealthStatus> {
  return fetchApi('/health')
}

export async function getDetailedHealth(): Promise<DetailedHealthResponse> {
  return fetchApi('/health/detailed')
}

// ==============================================================================
// News Endpoints
// ==============================================================================

export async function getNews(options?: {
  limit?: number
  traded_only?: boolean
}): Promise<NewsEvent[]> {
  const params = new URLSearchParams()
  if (options?.limit) params.set('limit', String(options.limit))
  if (options?.traded_only) params.set('traded_only', 'true')

  const query = params.toString()
  return fetchApi(`/news${query ? `?${query}` : ''}`)
}

export async function getNewsBySymbol(
  symbol: string,
  limit?: number
): Promise<NewsEvent[]> {
  const params = new URLSearchParams()
  if (limit) params.set('limit', String(limit))

  const query = params.toString()
  return fetchApi(`/news/${symbol}${query ? `?${query}` : ''}`)
}

export async function getNewsDetail(newsId: string): Promise<NewsEvent> {
  return fetchApi(`/news/detail/${newsId}`)
}

export async function getNewsStrategies(
  newsId: string
): Promise<{ strategies: StrategyExecution[] }> {
  return fetchApi(`/news/${newsId}/strategies`)
}

export async function getNewsEvents(
  newsId: string
): Promise<{ events: PipelineEvent[] }> {
  return fetchApi(`/news/${newsId}/events`)
}

// ==============================================================================
// Event Endpoints
// ==============================================================================

export async function getRecentEvents(options?: {
  limit?: number
  event_type?: string
}): Promise<{ events: PipelineEvent[]; count: number }> {
  const params = new URLSearchParams()
  if (options?.limit) params.set('limit', String(options.limit))
  if (options?.event_type) params.set('event_type', options.event_type)

  const query = params.toString()
  return fetchApi(`/events/recent${query ? `?${query}` : ''}`)
}

// ==============================================================================
// Active Strategies Endpoints
// ==============================================================================

export async function getActiveStrategies(): Promise<{
  strategies: ActiveStrategy[]
  count: number
}> {
  return fetchApi('/strategies/active')
}

export async function requestManualExit(strategyId: string): Promise<{
  status: string
  strategy_id: string
}> {
  return fetchApi(`/strategies/${strategyId}/exit`, { method: 'POST' })
}

export async function requestTimerExtend(
  strategyId: string,
  minutes: number
): Promise<{
  status: string
  strategy_id: string
  minutes: number
}> {
  const params = new URLSearchParams({ minutes: String(minutes) })
  return fetchApi(`/strategies/${strategyId}/extend?${params}`, {
    method: 'POST',
  })
}

export async function requestCancelOrder(strategyId: string): Promise<{
  status: string
  strategy_id: string
}> {
  return fetchApi(`/strategies/${strategyId}/cancel`, { method: 'POST' })
}

// ==============================================================================
// Stats Endpoints
// ==============================================================================

export async function getLatencyStats(): Promise<LatencyResponse> {
  return fetchApi('/stats/latency')
}

export async function getSkipAnalysis(days?: number): Promise<SkipAnalysis> {
  const params = new URLSearchParams()
  if (days) params.set('days', String(days))

  const query = params.toString()
  return fetchApi(`/stats/skips${query ? `?${query}` : ''}`)
}

export async function getPerformanceStats(
  days?: number
): Promise<PerformanceStats> {
  const params = new URLSearchParams()
  if (days) params.set('days', String(days))

  const query = params.toString()
  return fetchApi(`/stats/performance${query ? `?${query}` : ''}`)
}

export async function getSummaryStats(days?: number): Promise<SummaryStats> {
  const params = new URLSearchParams()
  if (days) params.set('days', String(days))

  const query = params.toString()
  return fetchApi(`/stats/summary${query ? `?${query}` : ''}`)
}

// ==============================================================================
// Trade Detail & Market Data
// ==============================================================================

export async function getStrategyById(
  strategyId: string
): Promise<StrategyDetail> {
  return fetchApi(`/strategies/${strategyId}`)
}

export async function getMarketBars(
  ticker: string,
  fromTs: number,
  toTs: number,
  timeframe: string = '1',
  timespan: string = 'second'
): Promise<MarketBarsResponse> {
  const params = new URLSearchParams({
    from_ts: String(fromTs),
    to_ts: String(toTs),
    timeframe,
    timespan,
  })
  return fetchApi(`/market/bars/${ticker}?${params}`)
}

// ==============================================================================
// SSE Stream URL
// ==============================================================================

export function getStreamUrl(): string {
  const url = new URL('/stream', API_BASE_URL)
  return url.toString()
}

export function getStreamHeaders(): Record<string, string> {
  return API_KEY ? { 'X-API-Key': API_KEY } : {}
}
