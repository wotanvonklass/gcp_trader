/**
 * Client-side indicator calculations for strategy analysis.
 * These mirror the calculations done in the Python strategies.
 */

import type { OHLCVBar } from './types'

// ==============================================================================
// EMA Calculation
// ==============================================================================

/**
 * Calculate Exponential Moving Average for an array of prices.
 * Returns an array of EMA values (same length as input).
 */
export function calculateEMA(prices: number[], period: number): number[] {
  if (prices.length === 0) return []
  if (period <= 0) return prices.map(() => 0)

  const multiplier = 2 / (period + 1)
  const ema: number[] = []

  // First EMA value is just the first price (or SMA of first `period` values)
  ema[0] = prices[0]

  for (let i = 1; i < prices.length; i++) {
    ema[i] = (prices[i] - ema[i - 1]) * multiplier + ema[i - 1]
  }

  return ema
}

/**
 * Calculate multiple EMAs from bar data.
 * Returns an object with arrays for each EMA period.
 */
export function calculateEMAs(
  bars: OHLCVBar[],
  periods: number[] = [8, 21, 55]
): Record<number, number[]> {
  const closes = bars.map((b) => b.c)
  const result: Record<number, number[]> = {}

  for (const period of periods) {
    result[period] = calculateEMA(closes, period)
  }

  return result
}

// ==============================================================================
// Trend Strength Calculation
// ==============================================================================

/**
 * Calculate trend strength (0-100) based on EMA alignment and slope.
 * Matches the calculation in NewsTrendStrategy.
 */
export function calculateTrendStrength(
  ema8: number[],
  ema21: number[],
  ema55: number[],
  index: number
): number {
  if (index < 0 || index >= ema8.length) return 0

  // EMA alignment score (0-100)
  let alignment = 0
  if (ema8[index] > ema21[index]) alignment += 50
  if (ema21[index] > ema55[index]) alignment += 50

  // EMA slope strength (0-100)
  let slopeScore = 50
  if (index >= 5) {
    const slope8 = ((ema8[index] - ema8[index - 5]) / ema8[index - 5]) * 100
    const slope21 = ((ema21[index] - ema21[index - 5]) / ema21[index - 5]) * 100
    slopeScore = Math.min(100, Math.max(0, (slope8 + slope21) * 10 + 50))
  }

  // Final trend strength (60% alignment + 40% slope)
  return 0.6 * alignment + 0.4 * slopeScore
}

/**
 * Calculate trend strength for all bars.
 */
export function calculateTrendStrengthSeries(
  bars: OHLCVBar[],
  ema8: number[],
  ema21: number[],
  ema55: number[]
): number[] {
  return bars.map((_, i) => calculateTrendStrength(ema8, ema21, ema55, i))
}

// ==============================================================================
// VWAP Calculation
// ==============================================================================

/**
 * Calculate Volume Weighted Average Price from bars.
 */
export function calculateVWAP(bars: OHLCVBar[]): number {
  if (bars.length === 0) return 0

  let totalVolume = 0
  let volumePrice = 0

  for (const bar of bars) {
    // Use typical price (H+L+C)/3 weighted by volume
    const typicalPrice = (bar.h + bar.l + bar.c) / 3
    volumePrice += typicalPrice * bar.v
    totalVolume += bar.v
  }

  return totalVolume > 0 ? volumePrice / totalVolume : bars[bars.length - 1].c
}

/**
 * Calculate cumulative VWAP series (running VWAP at each bar).
 */
export function calculateVWAPSeries(bars: OHLCVBar[]): number[] {
  if (bars.length === 0) return []

  const vwap: number[] = []
  let totalVolume = 0
  let volumePrice = 0

  for (const bar of bars) {
    const typicalPrice = (bar.h + bar.l + bar.c) / 3
    volumePrice += typicalPrice * bar.v
    totalVolume += bar.v
    vwap.push(totalVolume > 0 ? volumePrice / totalVolume : bar.c)
  }

  return vwap
}

// ==============================================================================
// Summary Indicators
// ==============================================================================

export interface IndicatorSummary {
  // At specific point (e.g., news time, entry time)
  price: number
  ema8: number
  ema21: number
  ema55: number
  trendStrength: number
  vwap: number
  totalVolume: number
  barCount: number
}

/**
 * Calculate all indicators at a specific bar index.
 */
export function getIndicatorsAtIndex(
  bars: OHLCVBar[],
  emas: Record<number, number[]>,
  index: number
): IndicatorSummary {
  if (index < 0 || index >= bars.length) {
    return {
      price: 0,
      ema8: 0,
      ema21: 0,
      ema55: 0,
      trendStrength: 0,
      vwap: 0,
      totalVolume: 0,
      barCount: 0,
    }
  }

  const barsUpToIndex = bars.slice(0, index + 1)
  const trendStrength = calculateTrendStrength(
    emas[8],
    emas[21],
    emas[55],
    index
  )

  return {
    price: bars[index].c,
    ema8: emas[8][index],
    ema21: emas[21][index],
    ema55: emas[55][index],
    trendStrength,
    vwap: calculateVWAP(barsUpToIndex),
    totalVolume: barsUpToIndex.reduce((sum, b) => sum + b.v, 0),
    barCount: barsUpToIndex.length,
  }
}

/**
 * Find the bar index closest to a given timestamp.
 */
export function findBarIndexByTime(bars: OHLCVBar[], timestampMs: number): number {
  if (bars.length === 0) return -1

  const targetSec = Math.floor(timestampMs / 1000)

  // Binary search for closest bar
  let left = 0
  let right = bars.length - 1

  while (left < right) {
    const mid = Math.floor((left + right) / 2)
    const midSec = Math.floor(bars[mid].t / 1000)

    if (midSec < targetSec) {
      left = mid + 1
    } else {
      right = mid
    }
  }

  return left
}

/**
 * Get indicators at a specific timestamp.
 */
export function getIndicatorsAtTime(
  bars: OHLCVBar[],
  emas: Record<number, number[]>,
  timestampMs: number
): IndicatorSummary {
  const index = findBarIndexByTime(bars, timestampMs)
  return getIndicatorsAtIndex(bars, emas, index)
}

// ==============================================================================
// Chart Data Formatting
// ==============================================================================

export interface EMALineData {
  time: number // seconds
  value: number
}

/**
 * Format EMA data for lightweight-charts LineSeries.
 * Uses decimal timestamps for sub-second bar support.
 */
export function formatEMAForChart(
  bars: OHLCVBar[],
  emaValues: number[]
): EMALineData[] {
  return bars.map((bar, i) => ({
    time: bar.t / 1000,  // Decimal seconds for ms precision
    value: emaValues[i],
  }))
}
