/**
 * News View - Unified news feed with date filtering.
 * Uses polling to fetch news from API (no SSE).
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTorbiStore } from '../store'
import { getNews, getNewsEvents, getSummaryStats, getActiveStrategies } from '../api'
import { formatRelativeTime, formatCurrency } from '../utils'
import { NewsCard, FilterBar, SkipReasonsPanel, computeSkipReasons } from './shared'
import type { StatusFilter } from './shared'
import type { NewsEvent, PipelineStep } from '../types'

const POLL_INTERVAL = 10000 // 10 seconds

// Date filter options
type DateFilter = 'today' | 'yesterday' | 'week' | 'all'

// Helper to convert pipeline events to steps
function buildPipelineSteps(events: Array<{ type: string; timestamp: string; data: Record<string, unknown> }>): PipelineStep[] {
  const steps: PipelineStep[] = []

  for (const event of events) {
    if (event.type === 'news_received') {
      const data = event.data as { news_age_ms?: number }
      steps.push({
        label: data.news_age_ms != null
          ? `News received (${data.news_age_ms}ms old)`
          : 'News received',
        status: 'complete',
        timestamp: event.timestamp,
      })
    } else if (event.type === 'news_decision') {
      const data = event.data as { decision: string; skip_reason?: string; volume_found?: number }
      if (data.decision === 'trade') {
        steps.push({
          label: 'Decision: TRADE',
          status: 'complete',
          detail: data.volume_found
            ? `Volume: ${data.volume_found.toFixed(0)} shares`
            : undefined,
          timestamp: event.timestamp,
        })
      } else {
        steps.push({
          label: `SKIP: ${data.skip_reason || 'unknown'}`,
          status: 'skipped',
          timestamp: event.timestamp,
        })
      }
    } else if (event.type === 'strategy_spawned') {
      const data = event.data as { strategy_id: string; ticker: string; position_size_usd: number; entry_price: number }
      steps.push({
        label: `Strategy ${data.strategy_id.split('_')[0]}_${data.ticker} spawned`,
        status: 'complete',
        detail: `$${data.position_size_usd.toFixed(0)} @ $${data.entry_price.toFixed(2)}`,
        timestamp: event.timestamp,
      })
    } else if (event.type === 'order_placed') {
      const data = event.data as { order_role: string; side: string; qty: number; limit_price?: number }
      const action = data.order_role === 'entry' ? 'Entry' : 'Exit'
      const side = data.side.toUpperCase()
      steps.push({
        label: `${action} order placed: ${side} ${data.qty} @ $${data.limit_price?.toFixed(2) || 'MKT'}`,
        status: 'complete',
        timestamp: event.timestamp,
      })
    } else if (event.type === 'order_filled') {
      const data = event.data as { order_role: string; qty: number; fill_price: number; slippage?: number }
      const action = data.order_role === 'entry' ? 'Entry' : 'Exit'
      const slippageStr = data.slippage ? ` (slippage: $${data.slippage.toFixed(2)})` : ''
      steps.push({
        label: `${action} filled: ${data.qty} @ $${data.fill_price.toFixed(2)}${slippageStr}`,
        status: data.order_role === 'entry' ? 'active' : 'complete',
        timestamp: event.timestamp,
      })
    } else if (event.type === 'strategy_stopped') {
      const data = event.data as { reason: string; pnl?: number; pnl_percent?: number }
      const pnlStr = data.pnl
        ? ` P&L: $${data.pnl.toFixed(2)} (${data.pnl_percent?.toFixed(2)}%)`
        : ''
      steps.push({
        label: `Strategy stopped: ${data.reason}${pnlStr}`,
        status: 'complete',
        timestamp: event.timestamp,
      })
    }
  }

  return steps
}

// Get date string for API
function getDateString(filter: DateFilter): string | undefined {
  if (filter === 'all') return undefined

  const now = new Date()
  if (filter === 'today') {
    return 'today'
  } else if (filter === 'yesterday') {
    const yesterday = new Date(now)
    yesterday.setDate(yesterday.getDate() - 1)
    return yesterday.toISOString().split('T')[0]
  } else if (filter === 'week') {
    const weekAgo = new Date(now)
    weekAgo.setDate(weekAgo.getDate() - 7)
    return weekAgo.toISOString().split('T')[0]
  }
  return undefined
}

export function NewsView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { summaryStats, setSummaryStats, setActiveStrategies } = useTorbiStore()

  // News state
  const [news, setNews] = useState<NewsEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  // Pipeline expansion state
  const [expandedPipelines, setExpandedPipelines] = useState<Map<string, PipelineStep[]>>(new Map())
  const [loadingPipelines, setLoadingPipelines] = useState<Set<string>>(new Set())

  // Polling state
  const [isPaused, setIsPaused] = useState(false)
  const pollIntervalRef = useRef<number | null>(null)

  // Read filters from URL
  const dateFilter = (searchParams.get('date') as DateFilter) || 'today'
  const statusFilter = (searchParams.get('filter') as StatusFilter) || 'all'
  const symbolFilter = searchParams.get('symbol') || ''
  const hideNoTickers = searchParams.get('hideNoTickers') !== 'false' // default true

  // Is this a live view (today)?
  const isLiveView = dateFilter === 'today'

  // Update URL when filters change
  const setDateFilter = (newFilter: DateFilter) => {
    const params = new URLSearchParams(searchParams)
    if (newFilter === 'today') {
      params.delete('date')
    } else {
      params.set('date', newFilter)
    }
    setSearchParams(params)
  }

  const setStatusFilter = (newFilter: StatusFilter) => {
    const params = new URLSearchParams(searchParams)
    if (newFilter === 'all') {
      params.delete('filter')
    } else {
      params.set('filter', newFilter)
    }
    setSearchParams(params)
  }

  const setSymbolFilter = (symbol: string) => {
    const params = new URLSearchParams(searchParams)
    if (symbol.trim()) {
      params.set('symbol', symbol.trim().toUpperCase())
    } else {
      params.delete('symbol')
    }
    setSearchParams(params)
  }

  const setHideNoTickers = (hide: boolean) => {
    const params = new URLSearchParams(searchParams)
    if (hide) {
      params.delete('hideNoTickers') // default is true
    } else {
      params.set('hideNoTickers', 'false')
    }
    setSearchParams(params)
  }

  // Fetch news from API
  const fetchNews = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    setError(null)
    try {
      const fromDate = getDateString(dateFilter)
      const toDate = dateFilter === 'yesterday' ? fromDate : undefined

      const data = await getNews({
        limit: 200,
        from_date: fromDate,
        to_date: toDate,
        triggered_only: statusFilter === 'triggered',
        symbol: symbolFilter || undefined,
      })

      // Apply client-side filter for skipped
      let filteredData = data
      if (statusFilter === 'skipped') {
        filteredData = data.filter((n) => n.decision?.startsWith('skip'))
      }

      setNews(filteredData)
      setLastRefresh(new Date())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch news')
    }
    if (showLoading) setLoading(false)
  }, [dateFilter, statusFilter, symbolFilter])

  // Initial fetch and polling setup
  useEffect(() => {
    // Initial fetch
    fetchNews(true)

    // Setup polling for "today" view only
    if (isLiveView && !isPaused) {
      pollIntervalRef.current = window.setInterval(() => {
        fetchNews(false) // Don't show loading on poll
      }, POLL_INTERVAL)
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
  }, [fetchNews, isLiveView, isPaused])

  // Fetch summary stats and active strategies periodically
  useEffect(() => {
    const fetchStats = async () => {
      try {
        const [stats, strategiesData] = await Promise.all([
          getSummaryStats(1),
          getActiveStrategies(),
        ])
        setSummaryStats(stats)
        setActiveStrategies(strategiesData.strategies)
      } catch (err) {
        console.error('Failed to fetch stats:', err)
      }
    }

    fetchStats()
    const interval = setInterval(fetchStats, 30000)
    return () => clearInterval(interval)
  }, [setSummaryStats, setActiveStrategies])

  // Lazy load pipeline for a historical news item
  const handlePipelineExpand = useCallback(async (newsId: string) => {
    if (expandedPipelines.has(newsId) || loadingPipelines.has(newsId)) {
      return
    }

    setLoadingPipelines((prev) => new Set(prev).add(newsId))

    try {
      const { events } = await getNewsEvents(newsId)
      const steps = buildPipelineSteps(events)
      setExpandedPipelines((prev) => new Map(prev).set(newsId, steps))
    } catch (err) {
      console.error('Failed to load pipeline:', err)
      setExpandedPipelines((prev) => new Map(prev).set(newsId, []))
    }

    setLoadingPipelines((prev) => {
      const newSet = new Set(prev)
      newSet.delete(newsId)
      return newSet
    })
  }, [expandedPipelines, loadingPipelines])

  // Filter news items
  const filteredNews = hideNoTickers
    ? news.filter((n) => n.tickers && n.tickers.length > 0)
    : news

  // Compute stats
  const totalCount = filteredNews.length
  const triggeredCount = filteredNews.filter((n) => n.decision === 'trade').length
  const skippedCount = filteredNews.filter((n) => n.decision?.startsWith('skip')).length

  // Compute skip reasons
  const skipReasons = computeSkipReasons(filteredNews)

  // Update relative times
  const [, setTick] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  // Determine status for historical items
  const getNewsStatus = (item: NewsEvent): 'processing' | 'triggered' | 'skipped' => {
    if (item.decision === 'trade') return 'triggered'
    if (item.decision?.startsWith('skip')) return 'skipped'
    return 'processing'
  }

  return (
    <div className="space-y-4">
      {/* Header with date filter and controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          {/* Date filter pills */}
          <div className="flex rounded-md bg-slate-800 p-1">
            {(['today', 'yesterday', 'week', 'all'] as DateFilter[]).map((filter) => (
              <button
                key={filter}
                onClick={() => setDateFilter(filter)}
                className={`px-3 py-1 text-sm rounded transition-colors ${
                  dateFilter === filter
                    ? 'bg-slate-700 text-white'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                {filter === 'today' ? 'Today' : filter === 'yesterday' ? 'Yesterday' : filter === 'week' ? 'Week' : 'All'}
              </button>
            ))}
          </div>

          {/* Polling indicator (only when on Today) */}
          {isLiveView && (
            <span className="flex items-center gap-1.5 text-green-400">
              <span className={`h-2 w-2 rounded-full ${isPaused ? 'bg-yellow-500' : 'bg-green-500'}`}></span>
              {isPaused ? 'PAUSED' : 'AUTO'}
            </span>
          )}

          {/* Last refresh time */}
          <span className="text-sm text-gray-500">
            Last: {formatRelativeTime(lastRefresh?.toISOString() || null)}
          </span>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          {isLiveView && (
            <button
              onClick={() => setIsPaused(!isPaused)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                isPaused
                  ? 'bg-yellow-600 text-white'
                  : 'bg-slate-700 hover:bg-slate-600'
              }`}
            >
              {isPaused ? 'Resume' : 'Pause'}
            </button>
          )}
          <button
            onClick={() => fetchNews(true)}
            className="rounded-md bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <FilterBar
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        symbolFilter={symbolFilter}
        onSymbolChange={setSymbolFilter}
        totalCount={totalCount}
        triggeredCount={triggeredCount}
        skippedCount={skippedCount}
        hideNoTickers={hideNoTickers}
        onHideNoTickersChange={setHideNoTickers}
      />

      {/* Skip reasons panel */}
      {statusFilter !== 'triggered' && Object.keys(skipReasons).length > 0 && (
        <SkipReasonsPanel skipReasons={skipReasons} />
      )}

      {/* Loading/Error */}
      {loading && (
        <div className="text-center text-gray-400 py-8">Loading...</div>
      )}
      {error && (
        <div className="text-center text-red-400 py-8">{error}</div>
      )}

      {/* News Items */}
      <div className="space-y-3">
        {!loading && !error && (
          filteredNews.length === 0 ? (
            <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center">
              <p className="text-gray-400">
                {news.length === 0 ? 'No news found for this period' : 'No items match filters'}
              </p>
            </div>
          ) : (
            filteredNews.slice(0, 100).map((item) => {
              const newsStatus = getNewsStatus(item)
              const skipReason = item.skip_reason ||
                (item.decision?.startsWith('skip_')
                  ? item.decision.replace('skip_', '').replace(/_/g, ' ')
                  : undefined)

              return (
                <NewsCard
                  key={item.id}
                  newsId={item.id}
                  headline={item.headline}
                  tickers={item.tickers}
                  source={item.source}
                  pubTime={item.pub_time}
                  newsAgeMs={item.news_age_ms}
                  status={newsStatus}
                  skipReason={skipReason}
                  showRelativeTime={isLiveView}
                  expandable={true}
                  defaultExpanded={isLiveView}
                  pipelineSteps={expandedPipelines.get(item.id)}
                  pipelineLoading={loadingPipelines.has(item.id)}
                  onToggleExpand={() => handlePipelineExpand(item.id)}
                  linkTo={`/news/${item.id}`}
                />
              )
            })
          )
        )}
      </div>

      {/* Quick Stats */}
      {summaryStats && (
        <div className="mt-6 rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h3 className="mb-2 text-sm font-medium text-gray-400">
            Today's Summary
          </h3>
          <div className="flex flex-wrap gap-6 text-sm">
            <span>
              News: <strong className="text-white">{summaryStats.news.total}</strong>
            </span>
            <span>
              Triggered:{' '}
              <strong className="text-green-400">
                {summaryStats.news.triggered} ({summaryStats.news.triggered_percent.toFixed(0)}%)
              </strong>
            </span>
            <span>
              Active:{' '}
              <strong className="text-red-400">{summaryStats.strategies.active}</strong>
            </span>
            <span>
              P&L:{' '}
              <strong
                className={
                  summaryStats.pnl.total >= 0 ? 'text-green-400' : 'text-red-400'
                }
              >
                {formatCurrency(summaryStats.pnl.total, true)}
              </strong>
            </span>
            <span>
              Win:{' '}
              <strong className="text-white">
                {summaryStats.pnl.win_rate.toFixed(0)}%
              </strong>
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
