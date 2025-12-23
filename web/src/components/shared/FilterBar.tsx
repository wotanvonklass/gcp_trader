/**
 * Shared FilterBar component - reusable filter controls for news views.
 */

import { useState, useEffect } from 'react'

export type StatusFilter = 'all' | 'traded' | 'skipped'

export interface FilterBarProps {
  // Status filter
  statusFilter: StatusFilter
  onStatusChange: (status: StatusFilter) => void

  // Symbol search
  symbolFilter: string
  onSymbolChange: (symbol: string) => void

  // Optional limit selector (for history view)
  limit?: number
  onLimitChange?: (limit: number) => void
  limitOptions?: number[]

  // Summary stats to display
  totalCount?: number
  tradedCount?: number
  skippedCount?: number
}

export function FilterBar({
  statusFilter,
  onStatusChange,
  symbolFilter,
  onSymbolChange,
  limit,
  onLimitChange,
  limitOptions = [50, 100, 250, 500],
  totalCount,
  tradedCount,
  skippedCount,
}: FilterBarProps) {
  // Local state for debounced symbol input
  const [symbolInput, setSymbolInput] = useState(symbolFilter)

  // Debounce symbol filter updates
  useEffect(() => {
    const timer = setTimeout(() => {
      if (symbolInput !== symbolFilter) {
        onSymbolChange(symbolInput)
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [symbolInput, symbolFilter, onSymbolChange])

  // Sync input with external value
  useEffect(() => {
    setSymbolInput(symbolFilter)
  }, [symbolFilter])

  return (
    <div className="space-y-3">
      {/* Filter controls row */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Status filter */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">Status:</span>
          {(['all', 'traded', 'skipped'] as const).map((f) => (
            <button
              key={f}
              onClick={() => onStatusChange(f)}
              className={`rounded-md px-3 py-1 text-sm ${
                statusFilter === f
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-gray-300 hover:bg-slate-600'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>

        {/* Symbol search */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">Symbol:</span>
          <input
            type="text"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value)}
            placeholder="e.g., AAPL"
            className="w-24 rounded-md border border-slate-600 bg-slate-700 px-3 py-1 text-sm text-white placeholder-gray-500"
          />
        </div>

        {/* Limit selector (optional) */}
        {limit !== undefined && onLimitChange && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">Limit:</span>
            <select
              value={limit}
              onChange={(e) => onLimitChange(Number(e.target.value))}
              className="rounded-md border border-slate-600 bg-slate-700 px-3 py-1 text-sm text-white"
            >
              {limitOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Summary stats row */}
      {(totalCount !== undefined || tradedCount !== undefined || skippedCount !== undefined) && (
        <div className="flex gap-6 text-sm">
          {totalCount !== undefined && (
            <span>
              Total: <strong className="text-white">{totalCount}</strong>
            </span>
          )}
          {tradedCount !== undefined && (
            <span>
              Traded: <strong className="text-green-400">{tradedCount}</strong>
            </span>
          )}
          {skippedCount !== undefined && (
            <span>
              Skipped: <strong className="text-gray-400">{skippedCount}</strong>
            </span>
          )}
        </div>
      )}
    </div>
  )
}
