/**
 * Pipeline View - Detailed view of a single news event's journey.
 * Shows chart with price action and indicators for any news event.
 */

import { useEffect, useState, useMemo } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { usePakoStore } from '../store'
import { getNewsEvents, getNewsStrategies, getNewsDetail, getMarketBars } from '../api'
import {
  formatTime,
  formatCurrency,
  getStatusIcon,
  getPnlClass,
  truncate,
} from '../utils'
import type { PipelineEvent, StrategyExecution, OHLCVBar } from '../types'
import { Breadcrumbs } from './Breadcrumbs'
import { TradingChart } from './TradingChart'
import {
  calculateEMAs,
  calculateTrendStrength,
  calculateVWAP,
  findBarIndexByTime,
} from '../indicators'

// Timeframe options
const TIMEFRAMES = [
  { label: '1s', timeframe: '1', timespan: 'second' },
  { label: '5s', timeframe: '5', timespan: 'second' },
  { label: '15s', timeframe: '15', timespan: 'second' },
  { label: '1m', timeframe: '1', timespan: 'minute' },
]

// News item for display (can come from store or API)
interface NewsItemDisplay {
  news_id: string
  headline: string
  tickers: string[]
  source?: string
  news_age_ms?: number
  status: string
  pub_time?: string
  skip_reason?: string
}

export function PipelineView() {
  const { newsId } = useParams<{ newsId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const { setSelectedNewsId, getFeedItemsArray } = usePakoStore()
  const feedItems = getFeedItemsArray()

  const [events, setEvents] = useState<PipelineEvent[]>([])
  const [strategies, setStrategies] = useState<StrategyExecution[]>([])
  const [newsDetail, setNewsDetail] = useState<NewsItemDisplay | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Chart state
  const [bars, setBars] = useState<OHLCVBar[]>([])
  const [barsLoading, setBarsLoading] = useState(false)

  // Get timeframe from URL or default to '1s'
  const tfParam = searchParams.get('tf') || '1s'
  const currentTf = TIMEFRAMES.find((t) => t.label === tfParam) || TIMEFRAMES[0]

  // Sync URL param with store
  useEffect(() => {
    if (newsId) {
      setSelectedNewsId(newsId)
    }
  }, [newsId, setSelectedNewsId])

  // Fetch detailed events and strategies when news is selected
  useEffect(() => {
    if (!newsId) {
      setEvents([])
      setStrategies([])
      setNewsDetail(null)
      return
    }

    let cancelled = false

    const fetchData = async () => {
      setLoading(true)
      setError(null)
      try {
        // Always fetch from API for consistent data
        try {
          const detail = await getNewsDetail(newsId)
          if (!cancelled) {
            // Get skip reason from decision field if it starts with "skip_"
            const skipReason = detail.skip_reason ||
              (detail.decision && detail.decision.startsWith('skip_') ? detail.decision : undefined)
            setNewsDetail({
              news_id: detail.id,
              headline: detail.headline,
              tickers: detail.tickers,
              source: detail.source,
              news_age_ms: detail.news_age_ms,
              status: detail.decision === 'trade' ? 'traded' : 'skipped',
              pub_time: detail.pub_time,
              skip_reason: skipReason,
            })
          }
        } catch {
          // News not found in API - try store as fallback
          const storeItem = feedItems.find((item) => item.news_id === newsId)
          if (!cancelled && storeItem) {
            setNewsDetail({
              news_id: storeItem.news_id,
              headline: storeItem.headline,
              tickers: storeItem.tickers,
              source: storeItem.source,
              news_age_ms: storeItem.news_age_ms,
              status: storeItem.status,
              pub_time: storeItem.pub_time,
              skip_reason: storeItem.skip_reason,
            })
          }
        }

        const [eventsRes, strategiesRes] = await Promise.all([
          getNewsEvents(newsId),
          getNewsStrategies(newsId),
        ])
        if (!cancelled) {
          setEvents(eventsRes.events)
          setStrategies(strategiesRes.strategies)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to fetch data')
        }
      }
      if (!cancelled) {
        setLoading(false)
      }
    }

    fetchData()

    return () => {
      cancelled = true
    }
  }, [newsId]) // Only depend on newsId, not feedItems

  // Fetch bars when newsDetail or timeframe changes
  useEffect(() => {
    // Need at least one ticker and a pub_time
    if (!newsDetail?.tickers?.length || !newsDetail?.pub_time) {
      setBars([])
      return
    }

    const ticker = newsDetail.tickers[0] // Use first ticker
    const pubTime = newsDetail.pub_time

    const fetchBars = async () => {
      setBarsLoading(true)
      try {
        const newsTime = new Date(pubTime).getTime()
        // Calculate time range: 2 min before news -> 10 min after news
        const fromTs = newsTime - 2 * 60 * 1000
        const toTs = newsTime + 10 * 60 * 1000

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
  }, [newsDetail, currentTf])

  // Calculate indicators from bars
  const indicators = useMemo(() => {
    if (bars.length < 10 || !newsDetail?.pub_time) return null

    const emas = calculateEMAs(bars, [8, 21, 55])
    const newsTime = new Date(newsDetail.pub_time).getTime()
    const newsBarIndex = findBarIndexByTime(bars, newsTime)

    // Get values at news time
    const atNewsTime = newsBarIndex >= 0 && newsBarIndex < bars.length ? {
      price: bars[newsBarIndex].c,
      ema8: emas[8][newsBarIndex],
      ema21: emas[21][newsBarIndex],
      ema55: emas[55][newsBarIndex],
      trendStrength: calculateTrendStrength(emas[8], emas[21], emas[55], newsBarIndex),
      vwap: calculateVWAP(bars.slice(0, newsBarIndex + 1)),
      volume: bars.slice(0, newsBarIndex + 1).reduce((sum, b) => sum + b.v, 0),
    } : null

    // Get current (latest) values
    const lastIdx = bars.length - 1
    const current = {
      price: bars[lastIdx].c,
      ema8: emas[8][lastIdx],
      ema21: emas[21][lastIdx],
      ema55: emas[55][lastIdx],
      trendStrength: calculateTrendStrength(emas[8], emas[21], emas[55], lastIdx),
      vwap: calculateVWAP(bars),
      volume: bars.reduce((sum, b) => sum + b.v, 0),
    }

    return { atNewsTime, current }
  }, [bars, newsDetail])

  // Change timeframe
  const handleTimeframeChange = (tf: string) => {
    const newParams = new URLSearchParams(searchParams)
    newParams.set('tf', tf)
    setSearchParams(newParams)
  }

  // Use fetched news detail
  const selectedItem = newsDetail

  if (!newsId) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-white">Select a News Event</h2>
        <p className="text-gray-400">
          Click on a news item in the Live Feed to see its detailed pipeline.
        </p>

        {/* Recent events list for quick selection */}
        <div className="mt-6">
          <h3 className="mb-3 text-sm font-medium text-gray-400">
            Recent News Events
          </h3>
          <div className="space-y-2">
            {feedItems.slice(0, 10).map((item) => (
              <Link
                key={item.news_id}
                to={`/pipeline/${item.news_id}`}
                className="block w-full rounded-lg border border-slate-700 bg-slate-800 p-3 text-left hover:border-blue-500/50"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-white">
                    {item.headline.slice(0, 60)}...
                  </span>
                  <span
                    className={`text-xs ${
                      item.status === 'traded'
                        ? 'text-green-400'
                        : item.status === 'processing'
                        ? 'text-yellow-400'
                        : 'text-gray-500'
                    }`}
                  >
                    {item.status}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                  {item.tickers.map((t) => (
                    <span key={t} className="text-blue-400">
                      {t}
                    </span>
                  ))}
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Check if any strategies are closed (have trades)
  const closedStrategies = strategies.filter(
    (s) => s.status === 'closed' || s.stop_reason
  )

  return (
    <div className="space-y-6">
      {/* Breadcrumbs and actions */}
      <div className="flex items-center justify-between">
        <Breadcrumbs
          items={[
            { label: 'Pipeline', to: '/pipeline' },
            { label: selectedItem ? truncate(selectedItem.headline, 40) : newsId || 'Event' },
          ]}
        />
        {closedStrategies.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">
              {closedStrategies.length} completed trade{closedStrategies.length > 1 ? 's' : ''}
            </span>
          </div>
        )}
      </div>

      {/* News Header */}
      {selectedItem && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h2 className="text-lg font-semibold text-white">
            {selectedItem.headline}
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-gray-400">
            {selectedItem.tickers.map((t) => (
              <span
                key={t}
                className="rounded bg-slate-700 px-2 py-0.5 text-blue-400"
              >
                {t}
              </span>
            ))}
            {selectedItem.pub_time && (
              <>
                <span>|</span>
                <span className="text-white">
                  {new Date(selectedItem.pub_time).toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: false,
                    timeZoneName: 'short',
                  })}
                </span>
              </>
            )}
            {selectedItem.source && (
              <>
                <span>|</span>
                <span>{selectedItem.source}</span>
              </>
            )}
            {selectedItem.news_age_ms != null && (
              <>
                <span>|</span>
                <span>Age: {selectedItem.news_age_ms}ms</span>
              </>
            )}
            <span>|</span>
            <span
              className={
                selectedItem.status === 'traded'
                  ? 'text-green-400'
                  : selectedItem.status === 'processing'
                  ? 'text-yellow-400'
                  : 'text-gray-500'
              }
            >
              {selectedItem.status.toUpperCase()}
            </span>
          </div>
        </div>
      )}

      {/* Skip Reason Banner (for skipped news) */}
      {selectedItem?.status === 'skipped' && selectedItem?.skip_reason && (
        <div className="rounded-lg border border-amber-700/50 bg-amber-900/20 p-4">
          <div className="flex items-center gap-2">
            <span className="text-amber-500">Skip Reason:</span>
            <span className="text-amber-200">{selectedItem.skip_reason.replace('skip_', '').replace(/_/g, ' ')}</span>
          </div>
        </div>
      )}

      {/* Chart Section */}
      {selectedItem && selectedItem.tickers && selectedItem.tickers.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-400">
              Price Action - {selectedItem.tickers[0]}
            </h3>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">Timeframe:</span>
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf.label}
                  onClick={() => handleTimeframeChange(tf.label)}
                  className={`rounded-md px-2 py-0.5 text-xs ${
                    currentTf.label === tf.label
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-700 text-gray-300 hover:bg-slate-600'
                  }`}
                >
                  {tf.label}
                </button>
              ))}
              {barsLoading && (
                <span className="ml-2 text-xs text-gray-500">Loading...</span>
              )}
            </div>
          </div>
          {bars.length > 0 ? (
            <TradingChart
              bars={bars}
              ticker={selectedItem.tickers[0]}
              newsTime={selectedItem.pub_time ? new Date(selectedItem.pub_time).getTime() : undefined}
              entryTime={
                strategies.length > 0 && strategies[0].started_at
                  ? new Date(strategies[0].started_at).getTime()
                  : undefined
              }
              entryPrice={strategies.length > 0 ? strategies[0].entry_price : undefined}
              exitTime={
                strategies.length > 0 && strategies[0].stopped_at
                  ? new Date(strategies[0].stopped_at).getTime()
                  : undefined
              }
              exitPrice={strategies.length > 0 ? strategies[0].exit_price : undefined}
            />
          ) : (
            <div className="rounded-lg border border-slate-700 bg-slate-800 p-8 text-center">
              <p className="text-gray-400">
                {barsLoading ? 'Loading chart data...' : 'No chart data available for this time period'}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Indicators Panel */}
      {indicators && (
        <div className="grid gap-4 md:grid-cols-2">
          {/* Indicators at News Time */}
          {indicators.atNewsTime && (
            <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
              <h4 className="mb-3 text-sm font-medium text-gray-400">
                At News Time
              </h4>
              <div className="space-y-2 text-sm">
                <IndicatorRow label="Price" value={`$${indicators.atNewsTime.price.toFixed(4)}`} />
                <IndicatorRow
                  label="EMA8"
                  value={`$${indicators.atNewsTime.ema8.toFixed(4)}`}
                  color="text-yellow-400"
                />
                <IndicatorRow
                  label="EMA21"
                  value={`$${indicators.atNewsTime.ema21.toFixed(4)}`}
                  color="text-cyan-400"
                />
                <IndicatorRow
                  label="EMA55"
                  value={`$${indicators.atNewsTime.ema55.toFixed(4)}`}
                  color="text-fuchsia-400"
                />
                <div className="border-t border-slate-700 pt-2 mt-2">
                  <IndicatorRow
                    label="Trend Strength"
                    value={`${indicators.atNewsTime.trendStrength.toFixed(1)}`}
                    color={indicators.atNewsTime.trendStrength >= 60 ? 'text-green-400' : 'text-gray-400'}
                  />
                  <IndicatorRow label="VWAP" value={`$${indicators.atNewsTime.vwap.toFixed(4)}`} />
                  <IndicatorRow label="Volume" value={formatVolume(indicators.atNewsTime.volume)} />
                </div>
              </div>
            </div>
          )}
          {/* Current/Latest Indicators */}
          <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
            <h4 className="mb-3 text-sm font-medium text-gray-400">
              Latest Values
            </h4>
            <div className="space-y-2 text-sm">
              <IndicatorRow label="Price" value={`$${indicators.current.price.toFixed(4)}`} />
              <IndicatorRow
                label="EMA8"
                value={`$${indicators.current.ema8.toFixed(4)}`}
                color="text-yellow-400"
              />
              <IndicatorRow
                label="EMA21"
                value={`$${indicators.current.ema21.toFixed(4)}`}
                color="text-cyan-400"
              />
              <IndicatorRow
                label="EMA55"
                value={`$${indicators.current.ema55.toFixed(4)}`}
                color="text-fuchsia-400"
              />
              <div className="border-t border-slate-700 pt-2 mt-2">
                <IndicatorRow
                  label="Trend Strength"
                  value={`${indicators.current.trendStrength.toFixed(1)}`}
                  color={indicators.current.trendStrength >= 60 ? 'text-green-400' : 'text-gray-400'}
                />
                <IndicatorRow label="VWAP" value={`$${indicators.current.vwap.toFixed(4)}`} />
                <IndicatorRow label="Volume" value={formatVolume(indicators.current.volume)} />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Loading/Error */}
      {loading && (
        <div className="text-center text-gray-400">Loading...</div>
      )}
      {error && (
        <div className="text-center text-red-400">{error}</div>
      )}

      {/* Event Timeline */}
      {!loading && !error && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-gray-400">Event Timeline</h3>
          <div className="relative border-l-2 border-slate-700 pl-6">
            {events.map((event) => (
              <div key={event.id} className="mb-4 relative">
                <div className="absolute -left-8 top-0 flex h-4 w-4 items-center justify-center rounded-full bg-slate-800 border border-slate-600">
                  <span className="text-xs">{getStatusIcon('complete')}</span>
                </div>
                <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-white">
                      {formatEventType(event.type)}
                    </span>
                    <span className="text-xs text-gray-500">
                      {formatTime(event.timestamp)}
                    </span>
                  </div>
                  <div className="mt-1 text-sm text-gray-400">
                    <EventDataDisplay event={event} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Strategies */}
      {!loading && strategies.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-gray-400">Strategies</h3>
          <div className="grid gap-4 md:grid-cols-2">
            {strategies.map((strategy) => (
              <StrategyCard key={strategy.id} strategy={strategy} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function formatEventType(type: string): string {
  return type
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function EventDataDisplay({ event }: { event: PipelineEvent }) {
  const data = event.data as Record<string, unknown>

  // Render relevant fields based on event type
  const fields: string[] = []

  if (event.type === 'news_received') {
    fields.push(`Tickers: ${(data.tickers as string[])?.join(', ') || '-'}`)
    if (data.news_age_ms != null) fields.push(`Age: ${data.news_age_ms}ms`)
  } else if (event.type === 'news_decision') {
    fields.push(`Decision: ${data.decision}`)
    if (data.skip_reason) fields.push(`Reason: ${data.skip_reason}`)
    if (data.volume_found) fields.push(`Volume: ${data.volume_found}`)
  } else if (event.type === 'strategy_spawned') {
    fields.push(`Strategy: ${data.strategy_id}`)
    fields.push(`Size: ${formatCurrency(data.position_size_usd as number)}`)
    fields.push(`Price: $${(data.entry_price as number)?.toFixed(2)}`)
  } else if (event.type === 'order_placed') {
    fields.push(`${data.order_role}: ${data.side} ${data.qty}`)
    if (data.limit_price) fields.push(`@ $${(data.limit_price as number).toFixed(2)}`)
  } else if (event.type === 'order_filled') {
    fields.push(`${data.order_role}: ${data.qty} @ $${(data.fill_price as number)?.toFixed(2)}`)
    if (data.slippage) fields.push(`Slippage: $${(data.slippage as number).toFixed(2)}`)
  } else if (event.type === 'strategy_stopped') {
    fields.push(`Reason: ${data.reason}`)
    if (data.pnl !== undefined) fields.push(`P&L: ${formatCurrency(data.pnl as number, true)}`)
  }

  return <>{fields.join(' | ')}</>
}

function StrategyCard({ strategy }: { strategy: StrategyExecution }) {
  const pnlClass = getPnlClass(strategy.pnl || 0)
  const isClosed = strategy.status === 'closed' || strategy.stop_reason

  const content = (
    <>
      <div className="flex items-center justify-between">
        <span className="font-medium text-white">
          {strategy.strategy_name || strategy.strategy_type || 'Unknown'}
        </span>
        <span className="text-sm text-gray-500">{strategy.ticker}</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-gray-500">Status:</span>{' '}
          <span className="text-white">{strategy.status}</span>
        </div>
        <div>
          <span className="text-gray-500">Size:</span>{' '}
          <span className="text-white">
            {formatCurrency(strategy.position_size_usd || 0)}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Entry:</span>{' '}
          <span className="text-white">
            ${strategy.entry_price?.toFixed(2) || '-'}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Exit:</span>{' '}
          <span className="text-white">
            ${strategy.exit_price?.toFixed(2) || '-'}
          </span>
        </div>
      </div>
      {strategy.pnl !== undefined && (
        <div className="mt-2 border-t border-slate-700 pt-2 flex items-center justify-between">
          <div>
            <span className="text-gray-500">P&L:</span>{' '}
            <span className={pnlClass}>
              {formatCurrency(strategy.pnl, true)}
            </span>
          </div>
          {isClosed && (
            <span className="text-xs text-blue-400">View Chart &rarr;</span>
          )}
        </div>
      )}
      {!strategy.pnl && isClosed && (
        <div className="mt-2 border-t border-slate-700 pt-2 text-right">
          <span className="text-xs text-blue-400">View Chart &rarr;</span>
        </div>
      )}
    </>
  )

  if (isClosed) {
    return (
      <Link
        to={`/trades/${strategy.id}`}
        className="block rounded-lg border border-slate-700 bg-slate-800 p-4 hover:border-blue-500/50 transition-colors"
      >
        {content}
      </Link>
    )
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      {content}
    </div>
  )
}

function IndicatorRow({
  label,
  value,
  color = 'text-white',
}: {
  label: string
  value: string
  color?: string
}) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className={color}>{value}</span>
    </div>
  )
}

function formatVolume(vol: number): string {
  if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(2)}M`
  if (vol >= 1_000) return `${(vol / 1_000).toFixed(1)}K`
  return vol.toString()
}
