/**
 * Trades View - Completed trades with entry/exit details and chart.
 */

import { useEffect, useState } from 'react'
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom'
import {
  getNews,
  getNewsStrategies,
  getStrategyById,
  getMarketBars,
} from '../api'
import {
  formatCurrency,
  formatPercent,
  formatDateTime,
  getPnlClass,
  truncate,
} from '../utils'
import type {
  NewsEvent,
  StrategyExecution,
  StrategyDetail,
  OHLCVBar,
} from '../types'
import { TradingChart } from './TradingChart'
import { Breadcrumbs } from './Breadcrumbs'

interface TradeWithNews {
  news: NewsEvent
  strategy: StrategyExecution
}

// Timeframe options
const TIMEFRAMES = [
  { label: '1s', timeframe: '1', timespan: 'second' },
  { label: '5s', timeframe: '5', timespan: 'second' },
  { label: '15s', timeframe: '15', timespan: 'second' },
  { label: '1m', timeframe: '1', timespan: 'minute' },
  { label: '5m', timeframe: '5', timespan: 'minute' },
]

export function TradesView() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()

  // If strategyId is present, show detail view
  if (strategyId) {
    return (
      <TradeDetailView
        strategyId={strategyId}
        searchParams={searchParams}
        setSearchParams={setSearchParams}
      />
    )
  }

  // Otherwise show list view
  return <TradesListView navigate={navigate} />
}

// ==============================================================================
// List View
// ==============================================================================

function TradesListView({
  navigate,
}: {
  navigate: ReturnType<typeof useNavigate>
}) {
  const [trades, setTrades] = useState<TradeWithNews[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'winners' | 'losers'>('all')

  useEffect(() => {
    const fetchTrades = async () => {
      setLoading(true)
      setError(null)
      try {
        const newsEvents = await getNews({ limit: 100, triggered_only: true })
        const tradesWithNews: TradeWithNews[] = []
        for (const news of newsEvents) {
          try {
            const { strategies } = await getNewsStrategies(news.id)
            for (const strategy of strategies) {
              if (strategy.status === 'closed' || strategy.stop_reason) {
                tradesWithNews.push({ news, strategy })
              }
            }
          } catch {
            // Skip news without strategies
          }
        }
        setTrades(tradesWithNews)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch trades')
      }
      setLoading(false)
    }
    fetchTrades()
  }, [])

  const filteredTrades = trades.filter((t) => {
    if (filter === 'winners') return (t.strategy.pnl || 0) > 0
    if (filter === 'losers') return (t.strategy.pnl || 0) < 0
    return true
  })

  const totalPnl = trades.reduce((sum, t) => sum + (t.strategy.pnl || 0), 0)
  const winners = trades.filter((t) => (t.strategy.pnl || 0) > 0).length
  const losers = trades.filter((t) => (t.strategy.pnl || 0) < 0).length
  const winRate = trades.length > 0 ? (winners / trades.length) * 100 : 0

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-400">Loading trades...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-red-400">{error}</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid gap-4 md:grid-cols-4">
        <SummaryCard
          label="Total P&L"
          value={formatCurrency(totalPnl, true)}
          colorClass={getPnlClass(totalPnl)}
        />
        <SummaryCard
          label="Total Trades"
          value={trades.length.toString()}
          colorClass="text-white"
        />
        <SummaryCard
          label="Win Rate"
          value={formatPercent(winRate)}
          colorClass={winRate >= 50 ? 'text-green-400' : 'text-red-400'}
        />
        <SummaryCard
          label="Winners / Losers"
          value={`${winners} / ${losers}`}
          colorClass="text-white"
        />
      </div>

      {/* Filter */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-400">Filter:</span>
        {(['all', 'winners', 'losers'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-md px-3 py-1 text-sm ${
              filter === f
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-gray-300 hover:bg-slate-600'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Trades Table */}
      {filteredTrades.length === 0 ? (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center">
          <p className="text-gray-400">No trades found</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-700">
          <table className="w-full text-sm">
            <thead className="bg-slate-800 text-left text-gray-400">
              <tr>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Ticker</th>
                <th className="px-4 py-3">Strategy</th>
                <th className="px-4 py-3">Entry</th>
                <th className="px-4 py-3">Exit</th>
                <th className="px-4 py-3">Qty</th>
                <th className="px-4 py-3 text-right">P&L</th>
                <th className="px-4 py-3">Headline</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {filteredTrades.map((trade, i) => (
                <TradeRow
                  key={i}
                  trade={trade}
                  onClick={() => navigate(`/trades/${trade.strategy.id}`)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ==============================================================================
// Detail View
// ==============================================================================

function TradeDetailView({
  strategyId,
  searchParams,
  setSearchParams,
}: {
  strategyId: string
  searchParams: URLSearchParams
  setSearchParams: (params: URLSearchParams) => void
}) {
  const [strategy, setStrategy] = useState<StrategyDetail | null>(null)
  const [bars, setBars] = useState<OHLCVBar[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [barsLoading, setBarsLoading] = useState(false)

  // Get timeframe from URL or default to '1s'
  const tfParam = searchParams.get('tf') || '1s'
  const currentTf =
    TIMEFRAMES.find((t) => t.label === tfParam) || TIMEFRAMES[0]

  // Fetch strategy details
  useEffect(() => {
    const fetchStrategy = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getStrategyById(strategyId)
        setStrategy(data)
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Failed to fetch strategy'
        )
      }
      setLoading(false)
    }
    fetchStrategy()
  }, [strategyId])

  // Fetch bars when strategy or timeframe changes
  useEffect(() => {
    if (!strategy?.ticker || !strategy?.pub_time) return

    // Capture values for the async callback
    const ticker = strategy.ticker
    const pubTime = strategy.pub_time
    const stratExitTime = strategy.exit_time

    const fetchBars = async () => {
      setBarsLoading(true)
      try {
        // Calculate time range: 1 min before news -> 1 min after exit (or now)
        const newsTime = new Date(pubTime).getTime()
        const exitTime = stratExitTime
          ? new Date(stratExitTime).getTime()
          : Date.now()

        const fromTs = newsTime - 60 * 1000 // 1 min before news
        const toTs = exitTime + 60 * 1000 // 1 min after exit

        const data = await getMarketBars(
          ticker,
          fromTs,
          toTs,
          currentTf.timeframe,
          currentTf.timespan
        )
        setBars(data.results || [])
      } catch (err) {
        console.error('Failed to fetch bars:', err)
        setBars([])
      }
      setBarsLoading(false)
    }
    fetchBars()
  }, [strategy, currentTf])

  // Change timeframe
  const handleTimeframeChange = (tf: string) => {
    const newParams = new URLSearchParams(searchParams)
    newParams.set('tf', tf)
    setSearchParams(newParams)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-400">Loading trade details...</div>
      </div>
    )
  }

  if (error || !strategy) {
    return (
      <div className="space-y-4">
        <Breadcrumbs
          items={[
            { label: 'Trades', to: '/trades' },
            { label: 'Not Found' },
          ]}
        />
        <div className="flex items-center justify-center py-20">
          <div className="text-red-400">{error || 'Strategy not found'}</div>
        </div>
      </div>
    )
  }

  // Calculate duration
  const duration = strategy.entry_time && strategy.exit_time
    ? formatDuration(
        new Date(strategy.entry_time).getTime(),
        new Date(strategy.exit_time).getTime()
      )
    : '-'

  // Parse timestamps for chart markers
  const newsTime = strategy.pub_time
    ? new Date(strategy.pub_time).getTime()
    : undefined
  const entryTime = strategy.entry_time
    ? new Date(strategy.entry_time).getTime()
    : undefined
  const exitTime = strategy.exit_time
    ? new Date(strategy.exit_time).getTime()
    : undefined

  return (
    <div className="space-y-6">
      {/* Breadcrumbs and actions */}
      <div className="flex items-center justify-between">
        <Breadcrumbs
          items={[
            { label: 'Trades', to: '/trades' },
            { label: `${strategy.ticker} - ${strategy.strategy_name || strategy.strategy_type || 'Trade'}` },
          ]}
        />
        <div className="flex items-center gap-2">
          <Link
            to={`/pipeline/${strategy.news_id}`}
            className="rounded-md bg-slate-700 px-3 py-1.5 text-sm text-gray-300 hover:bg-slate-600 transition-colors"
          >
            View Pipeline
          </Link>
        </div>
      </div>

      {/* Trade info cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-sm text-gray-400">Ticker</div>
          <div className="mt-1 text-2xl font-bold text-blue-400">
            {strategy.ticker}
          </div>
          <div className="text-sm text-gray-500">Long Position</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-sm text-gray-400">P&L</div>
          <div
            className={`mt-1 text-2xl font-bold ${getPnlClass(strategy.pnl || 0)}`}
          >
            {formatCurrency(strategy.pnl || 0, true)}
            {strategy.pnl_percent && (
              <span className="ml-2 text-base">
                ({strategy.pnl_percent > 0 ? '+' : ''}
                {strategy.pnl_percent.toFixed(2)}%)
              </span>
            )}
          </div>
          <div className="text-sm text-gray-500">
            {(strategy.pnl || 0) > 0 ? 'Winner' : 'Loser'}
          </div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="text-sm text-gray-400">Duration</div>
          <div className="mt-1 text-2xl font-bold text-white">{duration}</div>
          <div className="text-sm text-gray-500">
            {strategy.entry_time
              ? formatDateTime(strategy.entry_time)
              : '-'}
          </div>
        </div>
      </div>

      {/* Headline */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <div className="text-sm text-gray-400">Headline</div>
        <div className="mt-1 text-white">{strategy.headline || '-'}</div>
        <div className="mt-2 text-sm text-gray-500">
          Source: {strategy.source || '-'}
          {strategy.pub_time && (
            <span className="ml-4">
              Published: {formatDateTime(strategy.pub_time)}
            </span>
          )}
        </div>
      </div>

      {/* Timeframe selector */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-400">Timeframe:</span>
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf.label}
            onClick={() => handleTimeframeChange(tf.label)}
            className={`rounded-md px-3 py-1 text-sm ${
              currentTf.label === tf.label
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-gray-300 hover:bg-slate-600'
            }`}
          >
            {tf.label}
          </button>
        ))}
        {barsLoading && (
          <span className="ml-2 text-sm text-gray-500">Loading...</span>
        )}
      </div>

      {/* Chart */}
      {bars.length > 0 ? (
        <TradingChart
          bars={bars}
          ticker={strategy.ticker}
          newsTime={newsTime}
          entryTime={entryTime}
          entryPrice={strategy.entry_price}
          exitTime={exitTime}
          exitPrice={strategy.exit_price}
        />
      ) : (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center">
          <p className="text-gray-400">
            {barsLoading ? 'Loading chart data...' : 'No chart data available'}
          </p>
        </div>
      )}

      {/* Entry/Exit details */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="mb-2 text-sm font-medium text-gray-400">
            Entry Details
          </div>
          <div className="space-y-2 text-sm">
            <DetailRow
              label="Limit Price"
              value={
                strategy.limit_entry_price
                  ? `$${strategy.limit_entry_price.toFixed(2)}`
                  : '-'
              }
            />
            <DetailRow
              label="Fill Price"
              value={
                strategy.entry_price
                  ? `$${strategy.entry_price.toFixed(2)}`
                  : '-'
              }
            />
            <DetailRow
              label="Fill Time"
              value={
                strategy.entry_time
                  ? formatDateTime(strategy.entry_time)
                  : '-'
              }
            />
            <DetailRow
              label="Quantity"
              value={strategy.qty ? `${strategy.qty} shares` : '-'}
            />
          </div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <div className="mb-2 text-sm font-medium text-gray-400">
            Exit Details
          </div>
          <div className="space-y-2 text-sm">
            <DetailRow
              label="Fill Price"
              value={
                strategy.exit_price
                  ? `$${strategy.exit_price.toFixed(2)}`
                  : '-'
              }
            />
            <DetailRow
              label="Fill Time"
              value={
                strategy.exit_time ? formatDateTime(strategy.exit_time) : '-'
              }
            />
            <DetailRow
              label="Exit Reason"
              value={strategy.stop_reason || '-'}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

// ==============================================================================
// Helper Components
// ==============================================================================

function SummaryCard({
  label,
  value,
  colorClass,
}: {
  label: string
  value: string
  colorClass: string
}) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <div className="text-sm text-gray-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${colorClass}`}>{value}</div>
    </div>
  )
}

function TradeRow({
  trade,
  onClick,
}: {
  trade: TradeWithNews
  onClick: () => void
}) {
  const { news, strategy } = trade
  const pnlClass = getPnlClass(strategy.pnl || 0)

  return (
    <tr
      className="cursor-pointer bg-slate-800/50 hover:bg-slate-700"
      onClick={onClick}
    >
      <td className="px-4 py-3 text-gray-400">
        {strategy.started_at ? formatDateTime(strategy.started_at) : '-'}
      </td>
      <td className="px-4 py-3">
        <span className="font-medium text-blue-400">{strategy.ticker}</span>
        <span className="ml-1 text-gray-500">&rarr;</span>
      </td>
      <td className="px-4 py-3 text-gray-300">
        {strategy.strategy_name || strategy.strategy_type || '-'}
      </td>
      <td className="px-4 py-3 text-white">
        ${strategy.entry_price?.toFixed(2) || '-'}
      </td>
      <td className="px-4 py-3 text-white">
        ${strategy.exit_price?.toFixed(2) || '-'}
      </td>
      <td className="px-4 py-3 text-white">{strategy.qty || '-'}</td>
      <td className={`px-4 py-3 text-right font-medium ${pnlClass}`}>
        {formatCurrency(strategy.pnl || 0, true)}
      </td>
      <td className="px-4 py-3 text-gray-400">{truncate(news.headline, 40)}</td>
    </tr>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className="text-white">{value}</span>
    </div>
  )
}

function formatDuration(startMs: number, endMs: number): string {
  const diffMs = endMs - startMs
  const seconds = Math.floor(diffMs / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`
  }
  return `${seconds}s`
}
