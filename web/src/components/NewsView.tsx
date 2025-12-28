/**
 * News View - Unified news feed with date filtering.
 * Combines live SSE stream for "today" with historical data from API.
 */

import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePakoStore } from '../store'
import { getNews, getNewsEvents, getSummaryStats } from '../api'
import { formatRelativeTime, formatCurrency } from '../utils'
import { NewsCard, FilterBar, SkipReasonsPanel, computeSkipReasons } from './shared'
import type { StatusFilter } from './shared'
import type { NewsEvent, PipelineStep } from '../types'

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
  const {
    connected,
    lastEventTime,
    paused,
    soundEnabled,
    setPaused,
    setSoundEnabled,
    clearEvents,
    getFeedItemsArray,
    getPipelineSteps,
    summaryStats,
    setSummaryStats,
  } = usePakoStore()

  // Historical news state
  const [historicalNews, setHistoricalNews] = useState<NewsEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Pipeline expansion state (for historical items)
  const [expandedPipelines, setExpandedPipelines] = useState<Map<string, PipelineStep[]>>(new Map())
  const [loadingPipelines, setLoadingPipelines] = useState<Set<string>>(new Set())

  // Read filters from URL
  const dateFilter = (searchParams.get('date') as DateFilter) || 'today'
  const statusFilter = (searchParams.get('filter') as StatusFilter) || 'all'
  const symbolFilter = searchParams.get('symbol') || ''

  // Check if using live data (today filter)
  const useLiveData = dateFilter === 'today'
  const feedItems = getFeedItemsArray()

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

  // Fetch historical news when not using live data
  useEffect(() => {
    if (useLiveData) {
      setHistoricalNews([])
      return
    }

    const fetchNews = async () => {
      setLoading(true)
      setError(null)
      try {
        const fromDate = getDateString(dateFilter)
        const toDate = dateFilter === 'yesterday' ? fromDate : undefined

        const data = await getNews({
          limit: 200,
          from_date: fromDate,
          to_date: toDate,
          traded_only: statusFilter === 'traded',
          symbol: symbolFilter || undefined,
        })

        // Apply client-side filter for skipped
        let filteredData = data
        if (statusFilter === 'skipped') {
          filteredData = data.filter((n) => n.decision?.startsWith('skip'))
        }

        setHistoricalNews(filteredData)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch news')
      }
      setLoading(false)
    }

    fetchNews()
  }, [dateFilter, statusFilter, symbolFilter, useLiveData])

  // Fetch summary stats periodically (for live mode)
  useEffect(() => {
    if (!useLiveData) return

    const fetchStats = async () => {
      try {
        const stats = await getSummaryStats(1)
        setSummaryStats(stats)
      } catch (err) {
        console.error('Failed to fetch stats:', err)
      }
    }

    fetchStats()
    const interval = setInterval(fetchStats, 30000)
    return () => clearInterval(interval)
  }, [useLiveData, setSummaryStats])

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

  // Filter live feed items
  const filteredLiveItems = feedItems.filter((item) => {
    if (statusFilter === 'traded' && item.status !== 'traded') return false
    if (statusFilter === 'skipped' && item.status !== 'skipped') return false
    if (symbolFilter && !item.tickers.some((t) => t.toUpperCase().includes(symbolFilter.toUpperCase()))) {
      return false
    }
    return true
  })

  // Compute stats
  const items = useLiveData ? filteredLiveItems : historicalNews
  const totalCount = items.length
  const tradedCount = useLiveData
    ? filteredLiveItems.filter((item) => item.status === 'traded').length
    : historicalNews.filter((n) => n.decision === 'trade').length
  const skippedCount = useLiveData
    ? filteredLiveItems.filter((item) => item.status === 'skipped').length
    : historicalNews.filter((n) => n.decision?.startsWith('skip')).length

  // Compute skip reasons
  const skipReasons = useLiveData
    ? computeSkipReasons(feedItems.map((item) => ({
        decision: item.decision === 'skip' ? 'skip' : item.decision,
        skip_reason: item.skip_reason,
      })))
    : computeSkipReasons(historicalNews)

  // Update relative times
  const [, setTick] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  // Determine status for historical items
  const getNewsStatus = (item: NewsEvent): 'processing' | 'traded' | 'skipped' => {
    if (item.decision === 'trade') return 'traded'
    if (item.decision?.startsWith('skip')) return 'skipped'
    return 'processing'
  }

  return (
    <div className="space-y-4">
      {/* Header with date filter and live controls */}
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

          {/* Live indicator (only when on Today) */}
          {useLiveData && (
            <span
              className={`flex items-center gap-1.5 ${
                connected ? 'text-red-400' : 'text-gray-500'
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  connected ? 'animate-pulse bg-red-500' : 'bg-gray-500'
                }`}
              ></span>
              {connected ? 'LIVE' : 'OFFLINE'}
            </span>
          )}

          {useLiveData && (
            <span className="text-sm text-gray-500">
              Last: {formatRelativeTime(lastEventTime)}
            </span>
          )}
        </div>

        {/* Live controls (only when on Today) */}
        {useLiveData && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPaused(!paused)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                paused
                  ? 'bg-yellow-600 text-white'
                  : 'bg-slate-700 hover:bg-slate-600'
              }`}
            >
              {paused ? 'Resume' : 'Pause'}
            </button>
            <button
              onClick={clearEvents}
              className="rounded-md bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600"
            >
              Clear
            </button>
            <button
              onClick={() => setSoundEnabled(!soundEnabled)}
              className="rounded-md bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600"
              title={soundEnabled ? 'Sound enabled' : 'Sound disabled'}
            >
              {soundEnabled ? '🔊' : '🔇'}
            </button>
          </div>
        )}
      </div>

      {/* Filter bar */}
      <FilterBar
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        symbolFilter={symbolFilter}
        onSymbolChange={setSymbolFilter}
        totalCount={totalCount}
        tradedCount={tradedCount}
        skippedCount={skippedCount}
      />

      {/* Skip reasons panel */}
      {statusFilter !== 'traded' && Object.keys(skipReasons).length > 0 && (
        <SkipReasonsPanel skipReasons={skipReasons} />
      )}

      {/* Loading/Error for historical */}
      {!useLiveData && loading && (
        <div className="text-center text-gray-400 py-8">Loading...</div>
      )}
      {!useLiveData && error && (
        <div className="text-center text-red-400 py-8">{error}</div>
      )}

      {/* News Items */}
      <div className="space-y-3">
        {useLiveData ? (
          // Live feed items
          filteredLiveItems.length === 0 ? (
            <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center">
              <p className="text-gray-400">
                {connected
                  ? feedItems.length === 0
                    ? 'Waiting for news events...'
                    : 'No items match filters'
                  : 'Connecting to stream...'}
              </p>
            </div>
          ) : (
            filteredLiveItems.slice(0, 50).map((item) => (
              <NewsCard
                key={item.news_id}
                newsId={item.news_id}
                headline={item.headline}
                tickers={item.tickers}
                source={item.source}
                pubTime={item.pub_time}
                newsAgeMs={item.news_age_ms}
                receivedAt={item.received_at}
                status={item.status}
                decision={item.decision}
                skipReason={item.skip_reason}
                showRelativeTime={true}
                expandable={true}
                defaultExpanded={true}
                pipelineSteps={getPipelineSteps(item.news_id)}
                strategies={item.strategies}
                linkTo={`/news/${item.news_id}`}
              />
            ))
          )
        ) : (
          // Historical items
          !loading && !error && (
            historicalNews.length === 0 ? (
              <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center">
                <p className="text-gray-400">No news found for this period</p>
              </div>
            ) : (
              historicalNews.slice(0, 100).map((item) => {
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
                    showRelativeTime={false}
                    expandable={true}
                    defaultExpanded={false}
                    pipelineSteps={expandedPipelines.get(item.id)}
                    pipelineLoading={loadingPipelines.has(item.id)}
                    onToggleExpand={() => handlePipelineExpand(item.id)}
                    linkTo={`/news/${item.id}`}
                  />
                )
              })
            )
          )
        )}
      </div>

      {/* Quick Stats (live mode only) */}
      {useLiveData && summaryStats && (
        <div className="mt-6 rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h3 className="mb-2 text-sm font-medium text-gray-400">
            Today's Summary
          </h3>
          <div className="flex flex-wrap gap-6 text-sm">
            <span>
              News: <strong className="text-white">{summaryStats.news.total}</strong>
            </span>
            <span>
              Traded:{' '}
              <strong className="text-green-400">
                {summaryStats.news.traded} ({summaryStats.news.traded_percent.toFixed(0)}%)
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
