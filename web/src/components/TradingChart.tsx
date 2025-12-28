/**
 * TradingChart - Candlestick chart with volume, EMA overlays, and markers using lightweight-charts v5.
 */

import { useRef, useEffect, useState, useMemo } from 'react'
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createSeriesMarkers,
} from 'lightweight-charts'
import type { Time, SeriesMarker, ISeriesApi, SeriesType } from 'lightweight-charts'
import type { OHLCVBar } from '../types'
import { calculateEMAs, formatEMAForChart, calculateTrendStrength } from '../indicators'

// Strategy thresholds from news_trend_strategy.py
const TREND_ENTRY_THRESHOLD = 95.0
const TREND_EXIT_THRESHOLD = 64.0

interface TradingChartProps {
  bars: OHLCVBar[]
  newsTime?: number // timestamp in ms - when news was published
  receivedTime?: number // timestamp in ms - when we received the news
  entryTime?: number // timestamp in ms - when entry was filled
  entryPrice?: number
  exitTime?: number // timestamp in ms - when exit was filled
  exitPrice?: number
  ticker: string
  showEMAs?: boolean // whether to show EMA overlays
}

interface HoveredData {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  change: number
  changePercent: number
  trendStrength?: number
}

// Format milliseconds timestamp to HH:MM:SS.mmm
function formatMsTime(timestampMs: number): string {
  const date = new Date(timestampMs)
  const hours = date.getUTCHours().toString().padStart(2, '0')
  const mins = date.getUTCMinutes().toString().padStart(2, '0')
  const secs = date.getUTCSeconds().toString().padStart(2, '0')
  const ms = date.getUTCMilliseconds().toString().padStart(3, '0')
  return `${hours}:${mins}:${secs}.${ms}`
}

export function TradingChart({
  bars,
  newsTime,
  receivedTime,
  entryTime,
  entryPrice,
  exitTime,
  exitPrice,
  ticker,
  showEMAs = true,
}: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoveredData, setHoveredData] = useState<HoveredData | null>(null)
  const [emasVisible, setEmasVisible] = useState(showEMAs)
  const [trendVisible, setTrendVisible] = useState(true)

  // Calculate EMAs from bars
  const emaData = useMemo(() => {
    if (bars.length < 10) return null
    const emas = calculateEMAs(bars, [8, 21, 55])
    return {
      ema8: formatEMAForChart(bars, emas[8]),
      ema21: formatEMAForChart(bars, emas[21]),
      ema55: formatEMAForChart(bars, emas[55]),
      raw: emas, // Keep raw arrays for trend calculation
    }
  }, [bars])

  // Calculate trend strength series
  const trendData = useMemo(() => {
    if (!emaData || bars.length < 10) return null
    const { raw } = emaData
    return bars.map((bar, i) => ({
      time: bar.t / 1000, // Decimal seconds for ms precision
      value: calculateTrendStrength(raw[8], raw[21], raw[55], i),
    }))
  }, [bars, emaData])

  useEffect(() => {
    if (!containerRef.current || bars.length === 0) return

    // Create a lookup map for volume data (key is decimal timestamp in seconds)
    const volumeMap = new Map<number, number>()
    bars.forEach((bar) => {
      volumeMap.set(bar.t / 1000, bar.v)
    })

    // Create a lookup map for trend strength data
    const trendMap = new Map<number, number>()
    if (trendData) {
      trendData.forEach((point) => {
        trendMap.set(point.time, point.value)
      })
    }

    // Time formatter for tooltips (with ms)
    const msTimeFormatter = (time: number) => formatMsTime(time * 1000)

    // Simple seconds formatter for x-axis labels
    const secondsFormatter = (time: number) => {
      const date = new Date(time * 1000)
      const h = date.getUTCHours().toString().padStart(2, '0')
      const m = date.getUTCMinutes().toString().padStart(2, '0')
      const s = date.getUTCSeconds().toString().padStart(2, '0')
      return `${h}:${m}:${s}`
    }

    // Create chart with dark theme and custom time formatters
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#1e293b' },
        textColor: '#cbd5e1',
      },
      grid: {
        vertLines: { color: '#334155' },
        horzLines: { color: '#334155' },
      },
      localization: {
        timeFormatter: msTimeFormatter,
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: true,
        tickMarkFormatter: secondsFormatter,
      },
    })

    // Add candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      borderVisible: false,
    })

    // Convert bars to chart format (time as decimal seconds for ms precision)
    const candleData = bars.map((bar) => ({
      time: (bar.t / 1000) as Time,
      open: bar.o,
      high: bar.h,
      low: bar.l,
      close: bar.c,
    }))
    candleSeries.setData(candleData)

    // Add volume series as overlay (bottom 30%)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '', // overlay
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.65, bottom: 0.2 },
    })

    const volumeData = bars.map((bar) => ({
      time: (bar.t / 1000) as Time,
      value: bar.v,
      color: bar.c >= bar.o ? '#22c55e40' : '#ef444440',
    }))
    volumeSeries.setData(volumeData)

    // Add EMA line series if enabled and data available
    if (emasVisible && emaData) {
      // EMA8 - fast (yellow)
      const ema8Series = chart.addSeries(LineSeries, {
        color: '#fbbf24',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      ema8Series.setData(
        emaData.ema8.map((d) => ({ time: d.time as Time, value: d.value }))
      )

      // EMA21 - medium (cyan)
      const ema21Series = chart.addSeries(LineSeries, {
        color: '#22d3ee',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      ema21Series.setData(
        emaData.ema21.map((d) => ({ time: d.time as Time, value: d.value }))
      )

      // EMA55 - slow (magenta)
      const ema55Series = chart.addSeries(LineSeries, {
        color: '#e879f9',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      ema55Series.setData(
        emaData.ema55.map((d) => ({ time: d.time as Time, value: d.value }))
      )
    }

    // Add trend strength indicator if enabled (bottom 20%, left scale)
    if (trendVisible && trendData && trendData.length > 0) {
      // Trend strength line (blue)
      const trendSeries = chart.addSeries(LineSeries, {
        color: '#3b82f6', // blue
        lineWidth: 2,
        priceScaleId: 'trend',
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: true,
      })
      trendSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
      })
      trendSeries.setData(
        trendData.map((d) => ({ time: d.time as Time, value: d.value }))
      )

      // Entry threshold line (green dashed at 95)
      const entryThresholdSeries = chart.addSeries(LineSeries, {
        color: '#22c55e',
        lineWidth: 1,
        lineStyle: 2, // dashed
        priceScaleId: 'trend',
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      entryThresholdSeries.setData([
        { time: trendData[0].time as Time, value: TREND_ENTRY_THRESHOLD },
        { time: trendData[trendData.length - 1].time as Time, value: TREND_ENTRY_THRESHOLD },
      ])

      // Exit threshold line (red dashed at 64)
      const exitThresholdSeries = chart.addSeries(LineSeries, {
        color: '#ef4444',
        lineWidth: 1,
        lineStyle: 2, // dashed
        priceScaleId: 'trend',
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      exitThresholdSeries.setData([
        { time: trendData[0].time as Time, value: TREND_EXIT_THRESHOLD },
        { time: trendData[trendData.length - 1].time as Time, value: TREND_EXIT_THRESHOLD },
      ])
    }

    // Add news/entry/exit markers
    const markers: SeriesMarker<Time>[] = []

    // News event marker (orange circle)
    if (newsTime) {
      markers.push({
        time: Math.floor(newsTime / 1000) as Time,
        position: 'aboveBar',
        color: '#f97316', // orange
        shape: 'circle',
        text: 'NEWS',
      })
    }

    // Received marker (cyan square) - when we received the news
    if (receivedTime) {
      markers.push({
        time: Math.floor(receivedTime / 1000) as Time,
        position: 'belowBar',
        color: '#06b6d4', // cyan
        shape: 'square',
        text: 'RECEIVED',
      })
    }

    // Buy marker (green arrow up)
    if (entryTime && entryPrice) {
      markers.push({
        time: Math.floor(entryTime / 1000) as Time,
        position: 'belowBar',
        color: '#22c55e', // green
        shape: 'arrowUp',
        text: `BUY $${entryPrice.toFixed(2)}`,
      })
    }

    // Sell marker (red arrow down)
    if (exitTime && exitPrice) {
      markers.push({
        time: Math.floor(exitTime / 1000) as Time,
        position: 'aboveBar',
        color: '#ef4444', // red
        shape: 'arrowDown',
        text: `SELL $${exitPrice.toFixed(2)}`,
      })
    }

    if (markers.length > 0) {
      createSeriesMarkers(candleSeries, markers)
    }

    // Subscribe to crosshair move for OHLC display
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) {
        setHoveredData(null)
        return
      }

      const candleData = param.seriesData.get(candleSeries as ISeriesApi<SeriesType>)
      if (candleData && 'open' in candleData) {
        const timeSeconds = param.time as number
        const volume = volumeMap.get(timeSeconds) || 0
        const trend = trendMap.get(timeSeconds)
        const change = candleData.close - candleData.open
        const changePercent = (change / candleData.open) * 100

        // Format time with milliseconds
        const timeStr = formatMsTime(timeSeconds * 1000)

        setHoveredData({
          time: timeStr,
          open: candleData.open,
          high: candleData.high,
          low: candleData.low,
          close: candleData.close,
          volume,
          change,
          changePercent,
          trendStrength: trend,
        })
      } else {
        setHoveredData(null)
      }
    })

    // Fit content to view
    chart.timeScale().fitContent()

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({
        width: containerRef.current?.clientWidth || 800,
      })
    })
    resizeObserver.observe(containerRef.current)

    // Cleanup
    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [bars, newsTime, receivedTime, entryTime, entryPrice, exitTime, exitPrice, emasVisible, emaData, trendData, trendVisible])

  // Format number for display
  const formatPrice = (price: number) => {
    return price >= 100 ? price.toFixed(2) : price.toFixed(4)
  }

  const formatVolume = (vol: number) => {
    if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(2)}M`
    if (vol >= 1_000) return `${(vol / 1_000).toFixed(1)}K`
    return vol.toString()
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-2">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-gray-400">{ticker}</span>
          {emaData && (
            <button
              onClick={() => setEmasVisible(!emasVisible)}
              className={`flex items-center gap-2 rounded px-2 py-0.5 text-xs transition-colors ${
                emasVisible
                  ? 'bg-slate-600 text-white'
                  : 'bg-slate-700 text-gray-500 hover:text-gray-300'
              }`}
            >
              <span>EMAs</span>
              {emasVisible && (
                <span className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-yellow-400" title="EMA8" />
                  <span className="h-2 w-2 rounded-full bg-cyan-400" title="EMA21" />
                  <span className="h-2 w-2 rounded-full bg-fuchsia-400" title="EMA55" />
                </span>
              )}
            </button>
          )}
          {trendData && (
            <button
              onClick={() => setTrendVisible(!trendVisible)}
              className={`flex items-center gap-2 rounded px-2 py-0.5 text-xs transition-colors ${
                trendVisible
                  ? 'bg-slate-600 text-white'
                  : 'bg-slate-700 text-gray-500 hover:text-gray-300'
              }`}
            >
              <span>Trend</span>
              {trendVisible && (
                <span className="flex items-center gap-1 text-[10px]">
                  <span className="text-green-400">↑{TREND_ENTRY_THRESHOLD}</span>
                  <span className="text-red-400">↓{TREND_EXIT_THRESHOLD}</span>
                </span>
              )}
            </button>
          )}
        </div>
        <span className="text-xs text-gray-500">
          Powered by TradingView Lightweight Charts
        </span>
      </div>
      <div className="relative">
        {/* OHLC Legend overlay */}
        <div className="absolute left-2 top-2 z-10 flex items-center gap-4 text-xs font-mono">
          {hoveredData ? (
            <>
              <span className="text-gray-400">{hoveredData.time}</span>
              <span className="text-gray-500">
                O <span className="text-white">{formatPrice(hoveredData.open)}</span>
              </span>
              <span className="text-gray-500">
                H <span className="text-white">{formatPrice(hoveredData.high)}</span>
              </span>
              <span className="text-gray-500">
                L <span className="text-white">{formatPrice(hoveredData.low)}</span>
              </span>
              <span className="text-gray-500">
                C <span className="text-white">{formatPrice(hoveredData.close)}</span>
              </span>
              <span className={hoveredData.change >= 0 ? 'text-green-400' : 'text-red-400'}>
                {hoveredData.change >= 0 ? '+' : ''}{formatPrice(hoveredData.change)} ({hoveredData.changePercent >= 0 ? '+' : ''}{hoveredData.changePercent.toFixed(2)}%)
              </span>
              <span className="text-gray-500">
                Vol <span className="text-white">{formatVolume(hoveredData.volume)}</span>
              </span>
              {hoveredData.trendStrength !== undefined && (
                <span className="text-gray-500">
                  Trend{' '}
                  <span
                    className={
                      hoveredData.trendStrength >= TREND_ENTRY_THRESHOLD
                        ? 'text-green-400'
                        : hoveredData.trendStrength < TREND_EXIT_THRESHOLD
                          ? 'text-red-400'
                          : 'text-blue-400'
                    }
                  >
                    {hoveredData.trendStrength.toFixed(1)}
                  </span>
                </span>
              )}
            </>
          ) : (
            <span className="text-gray-500">Hover over chart to see OHLCV data</span>
          )}
        </div>
        <div ref={containerRef} style={{ height: '400px' }} />
      </div>
    </div>
  )
}
