/**
 * Live Feed View - Real-time news event stream with pipeline visualization.
 */

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePakoStore } from '../store'
import { formatRelativeTime, formatCurrency } from '../utils'
import { getSummaryStats } from '../api'
import { NewsCard, FilterBar, SkipReasonsPanel, computeSkipReasons } from './shared'
import type { StatusFilter } from './shared'

export function LiveFeedView() {
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

  const feedItems = getFeedItemsArray()

  // Read filters from URL
  const statusFilter = (searchParams.get('filter') as StatusFilter) || 'all'
  const symbolFilter = searchParams.get('symbol') || ''

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

  // Filter feed items
  const filteredItems = feedItems.filter((item) => {
    // Status filter
    if (statusFilter === 'traded' && item.status !== 'traded') return false
    if (statusFilter === 'skipped' && item.status !== 'skipped') return false

    // Symbol filter
    if (
      symbolFilter &&
      !item.tickers.some((t) =>
        t.toUpperCase().includes(symbolFilter.toUpperCase())
      )
    ) {
      return false
    }

    return true
  })

  // Compute stats from filtered items
  const totalCount = filteredItems.length
  const tradedCount = filteredItems.filter((item) => item.status === 'traded').length
  const skippedCount = filteredItems.filter((item) => item.status === 'skipped').length

  // Compute skip reasons from all items (not filtered, to show full picture)
  const skipReasons = computeSkipReasons(
    feedItems.map((item) => ({
      decision: item.decision === 'skip' ? 'skip' : item.decision,
      skip_reason: item.skip_reason,
    }))
  )

  // Fetch summary stats periodically
  useEffect(() => {
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
  }, [setSummaryStats])

  // Update relative times
  const [, setTick] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="space-y-4">
      {/* Live controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
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
            {connected ? 'LIVE' : 'DISCONNECTED'}
          </span>
          <span className="text-sm text-gray-500">
            Last event: {formatRelativeTime(lastEventTime)}
          </span>
        </div>
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
          >
            Sound: {soundEnabled ? 'ON' : 'OFF'}
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
        tradedCount={tradedCount}
        skippedCount={skippedCount}
      />

      {/* Skip reasons panel */}
      {statusFilter !== 'traded' && Object.keys(skipReasons).length > 0 && (
        <SkipReasonsPanel skipReasons={skipReasons} />
      )}

      {/* Feed Items */}
      <div className="space-y-3">
        {filteredItems.length === 0 ? (
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
          filteredItems.slice(0, 50).map((item) => (
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
            />
          ))
        )}
      </div>

      {/* Quick Stats */}
      {summaryStats && (
        <div className="mt-6 rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h3 className="mb-2 text-sm font-medium text-gray-400">
            Quick Stats (Today)
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
