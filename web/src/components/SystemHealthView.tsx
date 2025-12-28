/**
 * System Health View - Component status and connection health monitoring.
 */

import { useEffect, useState } from 'react'
import { getHealth } from '../api'
import { formatRelativeTime, formatDateTime } from '../utils'
import type { HealthStatus } from '../types'

export function SystemHealthView() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastCheck, setLastCheck] = useState<string | null>(null)

  const fetchHealth = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getHealth()
      setHealth(data)
      setLastCheck(new Date().toISOString())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch health')
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchHealth()
    // Refresh every 30 seconds
    const interval = setInterval(fetchHealth, 30000)
    return () => clearInterval(interval)
  }, [])

  // Update timestamps
  const [, setTick] = useState(0)
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="space-y-6">
      {/* Overall Status */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">System Health</h2>
        <button
          onClick={fetchHealth}
          disabled={loading}
          className="rounded-md bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600 disabled:opacity-50"
        >
          {loading ? 'Checking...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-700 bg-red-900/20 p-4 text-red-400">
          {error}
        </div>
      )}

      {/* Component Status Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* News API */}
        <ComponentCard
          name="News API"
          status={health ? 'healthy' : error ? 'error' : 'unknown'}
          details={
            health
              ? [
                  `Uptime: ${formatUptime(health.uptime)}`,
                  `News stored: ${health.news_count}`,
                  `Events stored: ${health.event_count}`,
                ]
              : []
          }
        />

        {/* Polling Status */}
        <ComponentCard
          name="Dashboard"
          status="healthy"
          details={[
            `Mode: Polling (10s interval)`,
            `Last check: ${formatRelativeTime(lastCheck)}`,
          ]}
        />

        {/* Trading System */}
        <ComponentCard
          name="Trading System"
          status={health?.trading_active ? 'healthy' : 'warning'}
          details={[
            `Active: ${health?.trading_active ? 'Yes' : 'No'}`,
            `Active strategies: ${health?.active_strategies || 0}`,
          ]}
        />
      </div>

      {/* Detailed Health Info */}
      {health && (
        <>
          {/* Server Info */}
          <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
            <h3 className="mb-4 text-sm font-medium text-gray-400">
              Server Information
            </h3>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <InfoItem label="Status" value={health.status} />
              <InfoItem
                label="Started At"
                value={formatDateTime(health.started_at)}
              />
              <InfoItem label="Uptime" value={formatUptime(health.uptime)} />
              <InfoItem
                label="Environment"
                value={health.environment || 'production'}
              />
            </div>
          </div>

          {/* Data Counts */}
          <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
            <h3 className="mb-4 text-sm font-medium text-gray-400">
              Data Statistics
            </h3>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <InfoItem
                label="News Events"
                value={health.news_count?.toString() || '0'}
              />
              <InfoItem
                label="Pipeline Events"
                value={health.event_count?.toString() || '0'}
              />
              <InfoItem
                label="Active Strategies"
                value={health.active_strategies?.toString() || '0'}
              />
              <InfoItem
                label="SSE Subscribers"
                value={health.sse_subscribers?.toString() || '0'}
              />
            </div>
          </div>
        </>
      )}

      {/* Connection Checklist */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h3 className="mb-4 text-sm font-medium text-gray-400">
          Connection Checklist
        </h3>
        <div className="space-y-2">
          <ChecklistItem
            label="News API reachable"
            checked={health !== null}
            error={error !== null}
          />
          <ChecklistItem
            label="Dashboard polling active"
            checked={true}
          />
          <ChecklistItem
            label="Trading system active"
            checked={health?.trading_active === true}
            warning={health?.trading_active === false}
          />
        </div>
      </div>

      {/* Troubleshooting Tips */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <h3 className="mb-4 text-sm font-medium text-gray-400">
          Troubleshooting
        </h3>
        <div className="space-y-3 text-sm text-gray-400">
          {error && (
            <TroubleshootItem
              issue="API health check failed"
              suggestion="Verify News API is running at the configured URL. Check for network issues or CORS configuration."
            />
          )}
          {health && !health.trading_active && (
            <TroubleshootItem
              issue="Trading system inactive"
              suggestion="The news trader process may not be running. Check the server logs for errors."
            />
          )}
          {!error && health && (
            <div className="text-green-400">All systems operational.</div>
          )}
        </div>
      </div>

      {/* Last Check */}
      {lastCheck && (
        <div className="text-center text-xs text-gray-500">
          Last health check: {formatRelativeTime(lastCheck)}
        </div>
      )}
    </div>
  )
}

function ComponentCard({
  name,
  status,
  details,
}: {
  name: string
  status: 'healthy' | 'warning' | 'error' | 'unknown'
  details: string[]
}) {
  const statusConfig = {
    healthy: {
      color: 'text-green-400',
      bg: 'bg-green-500/10',
      border: 'border-green-500/30',
      icon: '\u2713',
      label: 'Healthy',
    },
    warning: {
      color: 'text-yellow-400',
      bg: 'bg-yellow-500/10',
      border: 'border-yellow-500/30',
      icon: '\u26A0',
      label: 'Warning',
    },
    error: {
      color: 'text-red-400',
      bg: 'bg-red-500/10',
      border: 'border-red-500/30',
      icon: '\u2717',
      label: 'Error',
    },
    unknown: {
      color: 'text-gray-400',
      bg: 'bg-slate-700',
      border: 'border-slate-600',
      icon: '?',
      label: 'Unknown',
    },
  }

  const config = statusConfig[status]

  return (
    <div className={`rounded-lg border ${config.border} ${config.bg} p-4`}>
      <div className="flex items-center justify-between">
        <span className="font-medium text-white">{name}</span>
        <span className={`flex items-center gap-1 text-sm ${config.color}`}>
          <span>{config.icon}</span>
          {config.label}
        </span>
      </div>
      {details.length > 0 && (
        <div className="mt-3 space-y-1 text-sm text-gray-400">
          {details.map((detail, i) => (
            <div key={i}>{detail}</div>
          ))}
        </div>
      )}
    </div>
  )
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-0.5 text-sm text-white">{value}</div>
    </div>
  )
}

function ChecklistItem({
  label,
  checked,
  error,
  warning,
}: {
  label: string
  checked: boolean
  error?: boolean
  warning?: boolean
}) {
  const icon = checked ? '\u2713' : error ? '\u2717' : warning ? '\u26A0' : '\u2022'
  const colorClass = checked
    ? 'text-green-400'
    : error
    ? 'text-red-400'
    : warning
    ? 'text-yellow-400'
    : 'text-gray-500'

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={colorClass}>{icon}</span>
      <span className="text-gray-300">{label}</span>
    </div>
  )
}

function TroubleshootItem({
  issue,
  suggestion,
}: {
  issue: string
  suggestion: string
}) {
  return (
    <div className="rounded-md bg-slate-700/50 p-3">
      <div className="font-medium text-yellow-400">{issue}</div>
      <div className="mt-1 text-gray-400">{suggestion}</div>
    </div>
  )
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours < 24) return `${hours}h ${minutes}m`
  const days = Math.floor(hours / 24)
  return `${days}d ${hours % 24}h`
}
