/**
 * Stats View - Performance analytics and metrics.
 */

import { useEffect, useState } from 'react'
import { getSummaryStats } from '../api'
import {
  formatCurrency,
  formatPercent,
  formatDateTime,
} from '../utils'
import type { SummaryStats } from '../types'

export function StatsView() {
  const [stats, setStats] = useState<SummaryStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(1)

  useEffect(() => {
    const fetchStats = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getSummaryStats(days)
        setStats(data)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch stats')
      }
      setLoading(false)
    }

    fetchStats()
  }, [days])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-400">Loading stats...</div>
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

  if (!stats) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-400">No stats available</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Time Period Selector */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-400">Period:</span>
        {[1, 7, 30].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`rounded-md px-3 py-1 text-sm ${
              days === d
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-gray-300 hover:bg-slate-600'
            }`}
          >
            {d === 1 ? 'Today' : `${d} Days`}
          </button>
        ))}
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total P&L"
          value={formatCurrency(stats.pnl.total, true)}
          colorClass={stats.pnl.total >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <StatCard
          label="Win Rate"
          value={formatPercent(stats.pnl.win_rate)}
          colorClass={stats.pnl.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}
        />
        <StatCard
          label="Total Trades"
          value={stats.strategies.closed.toString()}
          colorClass="text-white"
        />
        <StatCard
          label="News Processed"
          value={stats.news.total.toString()}
          colorClass="text-white"
        />
      </div>

      {/* P&L Breakdown */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h3 className="mb-4 text-lg font-semibold text-white">P&L Breakdown</h3>
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <div className="text-sm text-gray-400">Gross Profit</div>
            <div className="mt-1 text-xl font-bold text-green-400">
              {formatCurrency(stats.pnl.gross_profit, true)}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Gross Loss</div>
            <div className="mt-1 text-xl font-bold text-red-400">
              {formatCurrency(stats.pnl.gross_loss, true)}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Profit Factor</div>
            <div className="mt-1 text-xl font-bold text-white">
              {stats.pnl.gross_loss !== 0
                ? Math.abs(stats.pnl.gross_profit / stats.pnl.gross_loss).toFixed(2)
                : '∞'}
            </div>
          </div>
        </div>
      </div>

      {/* News Statistics */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h3 className="mb-4 text-lg font-semibold text-white">News Pipeline</h3>
        <div className="grid gap-4 md:grid-cols-4">
          <div>
            <div className="text-sm text-gray-400">Total Received</div>
            <div className="mt-1 text-xl font-bold text-white">
              {stats.news.total}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Traded</div>
            <div className="mt-1 text-xl font-bold text-green-400">
              {stats.news.traded} ({formatPercent(stats.news.traded_percent)})
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Skipped</div>
            <div className="mt-1 text-xl font-bold text-gray-400">
              {stats.news.skipped}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Pending</div>
            <div className="mt-1 text-xl font-bold text-yellow-400">
              {stats.news.pending}
            </div>
          </div>
        </div>
      </div>

      {/* Strategy Statistics */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h3 className="mb-4 text-lg font-semibold text-white">Strategies</h3>
        <div className="grid gap-4 md:grid-cols-4">
          <div>
            <div className="text-sm text-gray-400">Total Spawned</div>
            <div className="mt-1 text-xl font-bold text-white">
              {stats.strategies.total}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Currently Active</div>
            <div className="mt-1 text-xl font-bold text-red-400">
              {stats.strategies.active}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Closed</div>
            <div className="mt-1 text-xl font-bold text-gray-400">
              {stats.strategies.closed}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Entry Fill Rate</div>
            <div className="mt-1 text-xl font-bold text-white">
              {stats.strategies.total > 0
                ? formatPercent(
                    ((stats.strategies.closed + stats.strategies.active) /
                      stats.strategies.total) *
                      100
                  )
                : '0%'}
            </div>
          </div>
        </div>
      </div>

      {/* Win/Loss Distribution */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h3 className="mb-4 text-lg font-semibold text-white">
          Win/Loss Distribution
        </h3>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-400">Winners</span>
              <span className="text-green-400">
                {stats.pnl.winners} trades
              </span>
            </div>
            <div className="mt-2 h-4 overflow-hidden rounded-full bg-slate-700">
              <div
                className="h-full bg-green-500"
                style={{
                  width: `${
                    stats.strategies.closed > 0
                      ? (stats.pnl.winners / stats.strategies.closed) * 100
                      : 0
                  }%`,
                }}
              />
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-400">Losers</span>
              <span className="text-red-400">{stats.pnl.losers} trades</span>
            </div>
            <div className="mt-2 h-4 overflow-hidden rounded-full bg-slate-700">
              <div
                className="h-full bg-red-500"
                style={{
                  width: `${
                    stats.strategies.closed > 0
                      ? (stats.pnl.losers / stats.strategies.closed) * 100
                      : 0
                  }%`,
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Average Trade Stats */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h3 className="mb-4 text-lg font-semibold text-white">
          Average Trade Metrics
        </h3>
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <div className="text-sm text-gray-400">Avg Win</div>
            <div className="mt-1 text-xl font-bold text-green-400">
              {stats.pnl.winners > 0
                ? formatCurrency(stats.pnl.gross_profit / stats.pnl.winners, true)
                : '$0.00'}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Avg Loss</div>
            <div className="mt-1 text-xl font-bold text-red-400">
              {stats.pnl.losers > 0
                ? formatCurrency(stats.pnl.gross_loss / stats.pnl.losers, true)
                : '$0.00'}
            </div>
          </div>
          <div>
            <div className="text-sm text-gray-400">Avg P&L per Trade</div>
            <div
              className={`mt-1 text-xl font-bold ${
                stats.pnl.total >= 0 ? 'text-green-400' : 'text-red-400'
              }`}
            >
              {stats.strategies.closed > 0
                ? formatCurrency(stats.pnl.total / stats.strategies.closed, true)
                : '$0.00'}
            </div>
          </div>
        </div>
      </div>

      {/* Skip Reason Breakdown */}
      {stats.news.skip_reasons && Object.keys(stats.news.skip_reasons).length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
          <h3 className="mb-4 text-lg font-semibold text-white">
            Skip Reason Breakdown
          </h3>
          <div className="space-y-2">
            {Object.entries(stats.news.skip_reasons)
              .sort((a, b) => b[1] - a[1])
              .map(([reason, count]) => (
                <div key={reason} className="flex items-center gap-2">
                  <div className="flex-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-400">
                        {reason.replace('skip_', '')}
                      </span>
                      <span className="text-white">{count}</span>
                    </div>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-700">
                      <div
                        className="h-full bg-slate-500"
                        style={{
                          width: `${
                            stats.news.skipped > 0
                              ? (count / stats.news.skipped) * 100
                              : 0
                          }%`,
                        }}
                      />
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Last Updated */}
      <div className="text-center text-xs text-gray-500">
        Data as of {formatDateTime(new Date().toISOString())}
      </div>
    </div>
  )
}

function StatCard({
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
