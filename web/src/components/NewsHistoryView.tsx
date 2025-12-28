/**
 * News History View - Historical news events with filters and pipeline expansion.
 */

import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getNews, getNewsBySymbol, getNewsEvents } from '../api'
import { NewsCard, FilterBar, SkipReasonsPanel, computeSkipReasons } from './shared'
import type { StatusFilter } from './shared'
import type { NewsEvent, PipelineStep } from '../types'

// Helper to convert pipeline events to steps (similar to store.ts buildPipelineSteps)
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

export function NewsHistoryView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [news, setNews] = useState<NewsEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Pipeline expansion state (lazy loaded)
  const [expandedPipelines, setExpandedPipelines] = useState<Map<string, PipelineStep[]>>(new Map())
  const [loadingPipelines, setLoadingPipelines] = useState<Set<string>>(new Set())

  // Read filters from URL
  const statusFilter = (searchParams.get('filter') as StatusFilter) || 'all'
  const symbolFilter = searchParams.get('symbol') || ''
  const limit = parseInt(searchParams.get('limit') || '100', 10)

  // Update URL when filters change
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

  const setLimit = (newLimit: number) => {
    const params = new URLSearchParams(searchParams)
    if (newLimit === 100) {
      params.delete('limit')
    } else {
      params.set('limit', String(newLimit))
    }
    setSearchParams(params)
  }

  // Fetch news data
  useEffect(() => {
    const fetchNews = async () => {
      setLoading(true)
      setError(null)
      try {
        let data: NewsEvent[]
        if (symbolFilter.trim()) {
          data = await getNewsBySymbol(symbolFilter.trim().toUpperCase(), { limit })
        } else {
          data = await getNews({
            limit,
            traded_only: statusFilter === 'traded',
          })
        }

        // Apply client-side filter for skipped
        if (statusFilter === 'skipped') {
          data = data.filter((n) => n.decision?.startsWith('skip'))
        }

        setNews(data)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch news')
      }
      setLoading(false)
    }

    fetchNews()
  }, [statusFilter, symbolFilter, limit])

  // Lazy load pipeline for a news item
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
      // Set empty array to prevent re-fetching
      setExpandedPipelines((prev) => new Map(prev).set(newsId, []))
    }

    setLoadingPipelines((prev) => {
      const newSet = new Set(prev)
      newSet.delete(newsId)
      return newSet
    })
  }, [expandedPipelines, loadingPipelines])

  // Summary stats
  const totalCount = news.length
  const tradedCount = news.filter((n) => n.decision === 'trade').length
  const skippedCount = news.filter((n) => n.decision?.startsWith('skip')).length

  // Skip reasons
  const skipReasons = computeSkipReasons(news)

  // Determine status for each news item
  const getNewsStatus = (item: NewsEvent): 'processing' | 'traded' | 'skipped' => {
    if (item.decision === 'trade') return 'traded'
    if (item.decision?.startsWith('skip')) return 'skipped'
    return 'processing'
  }

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <FilterBar
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        symbolFilter={symbolFilter}
        onSymbolChange={setSymbolFilter}
        limit={limit}
        onLimitChange={setLimit}
        totalCount={totalCount}
        tradedCount={tradedCount}
        skippedCount={skippedCount}
      />

      {/* Skip reasons panel */}
      {statusFilter !== 'traded' && Object.keys(skipReasons).length > 0 && (
        <SkipReasonsPanel skipReasons={skipReasons} />
      )}

      {/* Loading/Error */}
      {loading && (
        <div className="text-center text-gray-400">Loading...</div>
      )}
      {error && (
        <div className="text-center text-red-400">{error}</div>
      )}

      {/* News List */}
      {!loading && !error && (
        <div className="space-y-3">
          {news.length === 0 ? (
            <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center">
              <p className="text-gray-400">No news found</p>
            </div>
          ) : (
            news.map((item) => {
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
                />
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
