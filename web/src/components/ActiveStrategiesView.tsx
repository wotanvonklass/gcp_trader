/**
 * Active Strategies View - Currently running strategies with live P&L.
 */

import { useState, useEffect } from 'react'
import { useTorbiStore } from '../store'
import {
  formatCurrency,
  formatPercent,
  formatRelativeTime,
  formatCountdown,
  getStatusClass,
  truncate,
} from '../utils'
import {
  requestManualExit,
  requestTimerExtend,
  requestCancelOrder,
} from '../api'
import type { ActiveStrategy } from '../types'

export function ActiveStrategiesView() {
  const { getActiveStrategiesArray } = useTorbiStore()
  const strategies = getActiveStrategiesArray()

  // Update countdown timers
  const [, setTick] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  if (strategies.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-4xl mb-4">💤</div>
        <h2 className="text-xl font-bold text-white">No Active Strategies</h2>
        <p className="mt-2 text-gray-400">
          Strategies will appear here when news triggers a trade
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">
          Active Strategies ({strategies.length})
        </h2>
        <div className="flex items-center gap-4 text-sm">
          <TotalUnrealizedPnL strategies={strategies} />
        </div>
      </div>

      {/* Strategy Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {strategies.map((strategy) => (
          <StrategyCard key={strategy.id} strategy={strategy} />
        ))}
      </div>
    </div>
  )
}

function TotalUnrealizedPnL({ strategies }: { strategies: ActiveStrategy[] }) {
  const total = strategies.reduce(
    (sum, s) => sum + (s.unrealized_pnl || 0),
    0
  )
  const colorClass = total >= 0 ? 'text-green-400' : 'text-red-400'

  return (
    <span>
      Total Unrealized:{' '}
      <strong className={colorClass}>{formatCurrency(total, true)}</strong>
    </span>
  )
}

function StrategyCard({ strategy }: { strategy: ActiveStrategy }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleManualExit = async () => {
    if (!confirm('Are you sure you want to exit this position early?')) return
    setLoading(true)
    setError(null)
    try {
      await requestManualExit(strategy.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to request exit')
    }
    setLoading(false)
  }

  const handleExtendTimer = async () => {
    setLoading(true)
    setError(null)
    try {
      await requestTimerExtend(strategy.id, 2)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to extend timer')
    }
    setLoading(false)
  }

  const handleCancelOrder = async () => {
    if (!confirm('Are you sure you want to cancel this order?')) return
    setLoading(true)
    setError(null)
    try {
      await requestCancelOrder(strategy.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel order')
    }
    setLoading(false)
  }

  const statusClass = getStatusClass(strategy.status)
  const pnlClass =
    (strategy.unrealized_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'

  // Calculate time remaining
  const exitCountdown = calculateExitCountdown(strategy)

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold text-blue-400">
            {strategy.ticker}
          </span>
          <span
            className={`rounded px-2 py-0.5 text-xs font-medium ${statusClass} bg-slate-700`}
          >
            {strategy.status.replace('_', ' ').toUpperCase()}
          </span>
        </div>
        <span className="text-sm text-gray-500">
          {strategy.strategy_type || 'volume'}
        </span>
      </div>

      {/* Headline */}
      <p className="mt-2 text-sm text-gray-400">
        {truncate(strategy.headline, 80)}
      </p>

      {/* Position Details */}
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-gray-500">Side:</span>{' '}
          <span className="text-white">{strategy.side.toUpperCase()}</span>
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
            ${strategy.entry_fill_price?.toFixed(2) ||
              strategy.entry_limit_price?.toFixed(2) ||
              '-'}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Qty:</span>{' '}
          <span className="text-white">{strategy.qty || '-'}</span>
        </div>
      </div>

      {/* P&L */}
      {strategy.status === 'in_position' && (
        <div className="mt-3 border-t border-slate-700 pt-3">
          <div className="flex items-center justify-between">
            <span className="text-gray-500">Unrealized P&L:</span>
            <span className={`font-semibold ${pnlClass}`}>
              {formatCurrency(strategy.unrealized_pnl || 0, true)}{' '}
              ({formatPercent(strategy.unrealized_pnl_percent || 0, true)})
            </span>
          </div>
        </div>
      )}

      {/* Countdown */}
      {exitCountdown !== null && strategy.status === 'in_position' && (
        <div className="mt-3 flex items-center justify-between text-sm">
          <span className="text-gray-500">Exit in:</span>
          <span className="font-mono text-yellow-400">
            {formatCountdown(exitCountdown)}
          </span>
        </div>
      )}

      {/* Actions */}
      <div className="mt-4 flex gap-2">
        {strategy.status === 'pending_entry' && (
          <button
            onClick={handleCancelOrder}
            disabled={loading}
            className="flex-1 rounded bg-red-600/20 px-3 py-1.5 text-sm text-red-400 hover:bg-red-600/30 disabled:opacity-50"
          >
            Cancel
          </button>
        )}
        {strategy.status === 'in_position' && (
          <>
            <button
              onClick={handleExtendTimer}
              disabled={loading}
              className="flex-1 rounded bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600 disabled:opacity-50"
            >
              +2 min
            </button>
            <button
              onClick={handleManualExit}
              disabled={loading}
              className="flex-1 rounded bg-red-600/20 px-3 py-1.5 text-sm text-red-400 hover:bg-red-600/30 disabled:opacity-50"
            >
              Exit Now
            </button>
          </>
        )}
      </div>

      {/* Error */}
      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}

      {/* Meta */}
      <div className="mt-3 text-xs text-gray-600">
        Started {formatRelativeTime(strategy.spawned_at)}
      </div>
    </div>
  )
}

function calculateExitCountdown(strategy: ActiveStrategy): number | null {
  if (!strategy.entry_filled_at || !strategy.exit_delay_seconds) return null

  const entryTime = new Date(strategy.entry_filled_at).getTime()
  const exitTime = entryTime + strategy.exit_delay_seconds * 1000
  const now = Date.now()
  const remaining = Math.max(0, Math.floor((exitTime - now) / 1000))

  return remaining
}
