/**
 * Utility functions for Torbi Web dashboard.
 */

/**
 * Format a timestamp as relative time (e.g., "2s ago", "5m ago").
 */
export function formatRelativeTime(timestamp: string | null): string {
  if (!timestamp) return 'never'

  const now = Date.now()
  const then = new Date(timestamp).getTime()
  const diffMs = now - then

  if (diffMs < 0) return 'just now'

  const seconds = Math.floor(diffMs / 1000)
  if (seconds < 60) return `${seconds}s ago`

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`

  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

/**
 * Format milliseconds as a human-readable duration.
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`

  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`

  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60

  if (minutes < 60) {
    return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`
  }

  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60

  return `${hours}h ${remainingMinutes}m`
}

/**
 * Format a countdown in seconds as MM:SS.
 */
export function formatCountdown(seconds: number): string {
  if (seconds <= 0) return '0:00'

  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60

  return `${mins}:${secs.toString().padStart(2, '0')}`
}

/**
 * Format a number as currency.
 */
export function formatCurrency(value: number, showSign = false): string {
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value))

  if (showSign && value !== 0) {
    return value > 0 ? `+${formatted}` : `-${formatted}`
  }

  return value < 0 ? `-${formatted}` : formatted
}

/**
 * Format a percentage.
 */
export function formatPercent(value: number, showSign = false): string {
  const formatted = `${Math.abs(value).toFixed(2)}%`

  if (showSign && value !== 0) {
    return value > 0 ? `+${formatted}` : `-${formatted}`
  }

  return value < 0 ? `-${formatted}` : formatted
}

/**
 * Format a number with commas.
 */
export function formatNumber(value: number, decimals = 0): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

/**
 * Format a timestamp as local time.
 */
export function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

/**
 * Format a timestamp as date and time with seconds.
 */
export function formatDateTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

/**
 * Get CSS class for P&L value.
 */
export function getPnlClass(value: number): string {
  if (value > 0) return 'text-green-400'
  if (value < 0) return 'text-red-400'
  return 'text-gray-400'
}

/**
 * Get CSS class for status.
 */
export function getStatusClass(status: string): string {
  switch (status) {
    case 'processing':
    case 'pending_entry':
      return 'text-yellow-400'
    case 'triggered':
    case 'in_position':
    case 'active':
      return 'text-green-400'
    case 'skipped':
    case 'cancelled':
      return 'text-gray-500'
    case 'pending_exit':
    case 'pending_close':
      return 'text-orange-400'
    case 'completed':
      return 'text-blue-400'
    default:
      return 'text-gray-400'
  }
}

/**
 * Get border class for feed item status.
 */
export function getFeedItemBorderClass(status: string): string {
  switch (status) {
    case 'processing':
      return 'border-yellow-500/50'
    case 'triggered':
      return 'border-green-500/50'
    case 'skipped':
      return 'border-slate-600'
    default:
      return 'border-slate-600'
  }
}

/**
 * Get status icon.
 */
export function getStatusIcon(status: string): string {
  switch (status) {
    case 'processing':
    case 'pending':
      return '\u26A1' // lightning bolt
    case 'triggered':
    case 'complete':
    case 'completed':
      return '\u2705' // checkmark
    case 'active':
    case 'in_position':
      return '\u{1F7E2}' // green circle
    case 'skipped':
      return '\u26AA' // white circle
    case 'pending_exit':
    case 'pending_close':
      return '\u23F3' // hourglass
    case 'error':
      return '\u274C' // red X
    default:
      return '\u2022' // bullet
  }
}

/**
 * Truncate text with ellipsis.
 */
export function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength - 3) + '...'
}

/**
 * Generate a unique ID.
 */
export function generateId(): string {
  return Math.random().toString(36).substring(2, 9)
}
