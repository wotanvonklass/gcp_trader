/**
 * Journal View - Completed trades with actual fills and P&L.
 */

import { useEffect, useState } from 'react'
import { useSearchParams, useParams } from 'react-router-dom'
import { getTrades, getStrategyById, getMarketBars } from '../api'
import { formatCurrency, formatTime, formatPercent } from '../utils'
import { TradingChart } from './TradingChart'
import { Breadcrumbs } from './Breadcrumbs'
import type { CompletedTrade, StrategyDetail, OHLCVBar } from '../types'

// Date filter options
type DateFilter = 'today' | 'yesterday' | 'week' | 'month' | 'all'

// Get date string for API
function getDateRange(filter: DateFilter): { from_date?: string; to_date?: string } {
  if (filter === 'all') return {}

  const now = new Date()
  if (filter === 'today') {
    return { from_date: 'today' }
  } else if (filter === 'yesterday') {
    const yesterday = new Date(now)
    yesterday.setDate(yesterday.getDate() - 1)
    const dateStr = yesterday.toISOString().split('T')[0]
    return { from_date: dateStr, to_date: dateStr }
  } else if (filter === 'week') {
    const weekAgo = new Date(now)
    weekAgo.setDate(weekAgo.getDate() - 7)
    return { from_date: weekAgo.toISOString().split('T')[0] }
  } else if (filter === 'month') {
    const monthAgo = new Date(now)
    monthAgo.setDate(monthAgo.getDate() - 30)
    return { from_date: monthAgo.toISOString().split('T')[0] }
  }
  return {}
}

// Timeframe options for chart
const TIMEFRAMES = [
  { label: '1s', timeframe: '1', timespan: 'second' },
  { label: '5s', timeframe: '5', timespan: 'second' },
  { label: '15s', timeframe: '15', timespan: 'second' },
  { label: '1m', timeframe: '1', timespan: 'minute' },
]

export function JournalView() {
  const { tradeId } = useParams<{ tradeId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()

  // List state
  const [trades, setTrades] = useState<CompletedTrade[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Detail state
  const [selectedTrade, setSelectedTrade] = useState<StrategyDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [bars, setBars] = useState<OHLCVBar[]>([])
  const [barsLoading, setBarsLoading] = useState(false)

  // Filters
  const dateFilter = (searchParams.get('date') as DateFilter) || 'week'
  const tickerFilter = searchParams.get('ticker') || ''
  const tfParam = searchParams.get('tf') || '5s'
  const currentTf = TIMEFRAMES.find((t) => t.label === tfParam) || TIMEFRAMES[1]

  // Update URL when filters change
  const setDateFilter = (newFilter: DateFilter) => {
    const params = new URLSearchParams(searchParams)
    if (newFilter === 'week') {
      params.delete('date')
    } else {
      params.set('date', newFilter)
    }
    setSearchParams(params)
  }

  const setTickerFilter = (ticker: string) => {
    const params = new URLSearchParams(searchParams)
    if (ticker.trim()) {
      params.set('ticker', ticker.trim().toUpperCase())
    } else {
      params.delete('ticker')
    }
    setSearchParams(params)
  }

  const setTimeframe = (tf: string) => {
    const params = new URLSearchParams(searchParams)
    if (tf === '5s') {
      params.delete('tf')
    } else {
      params.set('tf', tf)
    }
    setSearchParams(params)
  }

  // Fetch trades list
  useEffect(() => {
    const fetchTrades = async () => {
      setLoading(true)
      setError(null)
      try {
        const { from_date, to_date } = getDateRange(dateFilter)
        const data = await getTrades({
          limit: 100,
          from_date,
          to_date,
          ticker: tickerFilter || undefined,
        })
        setTrades(data)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch trades')
      }
      setLoading(false)
    }

    fetchTrades()
  }, [dateFilter, tickerFilter])

  // Fetch trade detail when tradeId changes
  useEffect(() => {
    if (!tradeId) {
      setSelectedTrade(null)
      setBars([])
      return
    }

    const fetchDetail = async () => {
      setDetailLoading(true)
      try {
        const detail = await getStrategyById(tradeId)
        setSelectedTrade(detail)
      } catch (err) {
        console.error('Failed to fetch trade detail:', err)
        setSelectedTrade(null)
      }
      setDetailLoading(false)
    }

    fetchDetail()
  }, [tradeId])

  // Fetch chart data when trade detail or timeframe changes
  useEffect(() => {
    if (!selectedTrade?.ticker || !selectedTrade.entry_time) {
      setBars([])
      return
    }

    const fetchBars = async () => {
      setBarsLoading(true)
      try {
        const entryTime = new Date(selectedTrade.entry_time!).getTime()
        const exitTime = selectedTrade.exit_time
          ? new Date(selectedTrade.exit_time).getTime()
          : Date.now()

        // Add 2 minutes padding on each side
        const fromTs = entryTime - 120000
        const toTs = exitTime + 120000

        const response = await getMarketBars(
          selectedTrade.ticker,
          fromTs,
          toTs,
          currentTf.timeframe,
          currentTf.timespan
        )

        setBars(response.results || [])
      } catch (err) {
        console.error('Failed to fetch bars:', err)
        setBars([])
      }
      setBarsLoading(false)
    }

    fetchBars()
  }, [selectedTrade, currentTf])

  // Calculate summary stats
  const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0)
  const winners = trades.filter((t) => t.pnl > 0).length
  const losers = trades.filter((t) => t.pnl < 0).length
  const winRate = trades.length > 0 ? (winners / trades.length) * 100 : 0

  // If viewing a specific trade
  if (tradeId) {
    return (
      <div className="space-y-4">
        <Breadcrumbs
          items={[
            { label: 'Journal', to: '/journal' },
            { label: selectedTrade?.ticker || tradeId },
          ]}
        />

        {detailLoading && (
          <div className="text-center text-gray-400 py-8">Loading trade...</div>
        )}

        {!detailLoading && selectedTrade && (
          <div className="space-y-4">
            {/* Trade summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
                <div className="text-sm text-gray-400">Ticker</div>
                <div className="text-xl font-bold text-white">{selectedTrade.ticker}</div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
                <div className="text-sm text-gray-400">P&L</div>
                <div className={`text-xl font-bold ${(selectedTrade.pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {formatCurrency(selectedTrade.pnl || 0, true)}
                  {selectedTrade.pnl_percent && (
                    <span className="text-sm ml-1">({formatPercent(selectedTrade.pnl_percent)})</span>
                  )}
                </div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
                <div className="text-sm text-gray-400">Entry</div>
                <div className="text-lg text-white">
                  ${selectedTrade.entry_price?.toFixed(2)}
                  {selectedTrade.entry_time && (
                    <div className="text-xs text-gray-500">{formatTime(selectedTrade.entry_time)}</div>
                  )}
                </div>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
                <div className="text-sm text-gray-400">Exit</div>
                <div className="text-lg text-white">
                  ${selectedTrade.exit_price?.toFixed(2)}
                  {selectedTrade.exit_time && (
                    <div className="text-xs text-gray-500">{formatTime(selectedTrade.exit_time)}</div>
                  )}
                </div>
              </div>
            </div>

            {/* Headline */}
            {selectedTrade.headline && (
              <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
                <div className="text-sm text-gray-400 mb-1">Headline</div>
                <div className="text-white">{selectedTrade.headline}</div>
                {selectedTrade.source && (
                  <div className="text-xs text-gray-500 mt-1">{selectedTrade.source}</div>
                )}
              </div>
            )}

            {/* Timeframe selector */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-400">Chart:</span>
              <div className="flex rounded-md bg-slate-800 p-1">
                {TIMEFRAMES.map((tf) => (
                  <button
                    key={tf.label}
                    onClick={() => setTimeframe(tf.label)}
                    className={`px-3 py-1 text-sm rounded transition-colors ${
                      currentTf.label === tf.label
                        ? 'bg-slate-700 text-white'
                        : 'text-gray-400 hover:text-white'
                    }`}
                  >
                    {tf.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Chart */}
            <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
              {barsLoading ? (
                <div className="h-80 flex items-center justify-center text-gray-400">
                  Loading chart...
                </div>
              ) : bars.length > 0 ? (
                <TradingChart
                  bars={bars}
                  ticker={selectedTrade.ticker}
                  entryPrice={selectedTrade.entry_price}
                  exitPrice={selectedTrade.exit_price}
                  entryTime={selectedTrade.entry_time ? new Date(selectedTrade.entry_time).getTime() : undefined}
                  exitTime={selectedTrade.exit_time ? new Date(selectedTrade.exit_time).getTime() : undefined}
                />
              ) : (
                <div className="h-80 flex items-center justify-center text-gray-400">
                  No chart data available
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    )
  }

  // Trade list view
  return (
    <div className="space-y-4">
      {/* Header with summary stats */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-6">
          {/* Date filter pills */}
          <div className="flex rounded-md bg-slate-800 p-1">
            {(['today', 'yesterday', 'week', 'month', 'all'] as DateFilter[]).map((filter) => (
              <button
                key={filter}
                onClick={() => setDateFilter(filter)}
                className={`px-3 py-1 text-sm rounded transition-colors ${
                  dateFilter === filter
                    ? 'bg-slate-700 text-white'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                {filter.charAt(0).toUpperCase() + filter.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Summary stats */}
        <div className="flex items-center gap-6 text-sm">
          <span>
            Trades: <strong className="text-white">{trades.length}</strong>
          </span>
          <span>
            P&L:{' '}
            <strong className={totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}>
              {formatCurrency(totalPnl, true)}
            </strong>
          </span>
          <span>
            Win Rate:{' '}
            <strong className="text-white">{winRate.toFixed(0)}%</strong>
            <span className="text-gray-500 ml-1">({winners}W / {losers}L)</span>
          </span>
        </div>
      </div>

      {/* Ticker filter */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Filter by ticker..."
          value={tickerFilter}
          onChange={(e) => setTickerFilter(e.target.value)}
          className="rounded-md bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-slate-600"
        />
        {tickerFilter && (
          <button
            onClick={() => setTickerFilter('')}
            className="text-gray-400 hover:text-white"
          >
            Clear
          </button>
        )}
      </div>

      {/* Loading/Error */}
      {loading && (
        <div className="text-center text-gray-400 py-8">Loading trades...</div>
      )}
      {error && (
        <div className="text-center text-red-400 py-8">{error}</div>
      )}

      {/* Trade list */}
      {!loading && !error && (
        <div className="space-y-2">
          {trades.length === 0 ? (
            <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center">
              <p className="text-gray-400">No completed trades found</p>
              <p className="text-sm text-gray-500 mt-1">
                Trades appear here after both entry and exit orders are filled
              </p>
            </div>
          ) : (
            <div className="rounded-lg border border-slate-700 bg-slate-800 overflow-hidden">
              <table className="w-full">
                <thead className="bg-slate-700/50">
                  <tr className="text-left text-sm text-gray-400">
                    <th className="px-4 py-3">Time</th>
                    <th className="px-4 py-3">Ticker</th>
                    <th className="px-4 py-3">Entry</th>
                    <th className="px-4 py-3">Exit</th>
                    <th className="px-4 py-3">Qty</th>
                    <th className="px-4 py-3 text-right">P&L</th>
                    <th className="px-4 py-3">Headline</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700">
                  {trades.map((trade) => (
                    <tr
                      key={trade.id}
                      className="hover:bg-slate-700/30 cursor-pointer"
                      onClick={() => window.location.href = `/journal/${trade.id}`}
                    >
                      <td className="px-4 py-3 text-sm text-gray-400">
                        {trade.stopped_at ? formatTime(trade.stopped_at) : '-'}
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono font-bold text-white">{trade.ticker}</span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-300">
                        ${trade.entry_price.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-300">
                        ${trade.exit_price.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-400">
                        {trade.qty}
                      </td>
                      <td className={`px-4 py-3 text-sm text-right font-medium ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {formatCurrency(trade.pnl, true)}
                        {trade.pnl_percent && (
                          <span className="text-xs ml-1 text-gray-500">
                            ({formatPercent(trade.pnl_percent)})
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-400 max-w-xs truncate">
                        {trade.headline || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
