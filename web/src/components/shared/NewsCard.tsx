/**
 * Shared NewsCard component - works with both FeedItem (live) and NewsEvent (history).
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  formatRelativeTime,
  formatDateTime,
  getFeedItemBorderClass,
  getStatusIcon,
  truncate,
} from '../../utils'
import type { PipelineStep, FeedItemStrategy } from '../../types'

export interface NewsCardProps {
  // Core data (works with both types)
  newsId: string
  headline: string
  tickers: string[]
  source?: string
  pubTime?: string
  newsAgeMs?: number
  receivedAt?: string

  // Status
  status: 'processing' | 'traded' | 'skipped'
  decision?: string
  skipReason?: string

  // Display options
  showRelativeTime?: boolean
  expandable?: boolean
  defaultExpanded?: boolean

  // Pipeline data (for expansion)
  pipelineSteps?: PipelineStep[]
  strategies?: FeedItemStrategy[]

  // Loading state for lazy-loaded pipeline
  pipelineLoading?: boolean

  // Callbacks
  onToggleExpand?: () => void
}

export function NewsCard({
  newsId,
  headline,
  tickers,
  source,
  pubTime,
  newsAgeMs,
  receivedAt,
  status,
  skipReason,
  showRelativeTime = true,
  expandable = true,
  defaultExpanded = false,
  pipelineSteps,
  strategies,
  pipelineLoading = false,
  onToggleExpand,
}: NewsCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  const statusIcon = getStatusIcon(status)
  const borderClass = getFeedItemBorderClass(status)

  // Determine display time
  const timestamp = receivedAt || pubTime
  const timeDisplay = timestamp
    ? showRelativeTime
      ? formatRelativeTime(timestamp)
      : formatDateTime(timestamp)
    : '-'

  // Status text for non-live items
  const getStatusText = () => {
    if (status === 'traded') return 'TRADED'
    if (status === 'skipped') {
      return skipReason ? `SKIP: ${skipReason}` : 'SKIPPED'
    }
    return 'PENDING'
  }

  const statusColorClass =
    status === 'traded'
      ? 'text-green-400'
      : status === 'skipped'
      ? 'text-gray-500'
      : 'text-yellow-400'

  const handleToggle = () => {
    const newExpanded = !expanded
    setExpanded(newExpanded)
    if (newExpanded && onToggleExpand) {
      onToggleExpand()
    }
  }

  return (
    <div className={`rounded-lg border ${borderClass} bg-slate-800 p-4`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <span>{statusIcon}</span>
            <span>{timeDisplay}</span>
            {/* Show status text for history-style view (absolute time) */}
            {!showRelativeTime && (
              <span className={statusColorClass}>{getStatusText()}</span>
            )}
            <Link
              to={`/pipeline/${newsId}`}
              className="ml-2 text-blue-400 hover:text-blue-300"
            >
              View Pipeline &rarr;
            </Link>
          </div>
          <p className="mt-1 font-medium text-white">
            {truncate(headline, 120)}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-gray-400">
            {tickers.length > 0 ? (
              tickers.map((t) => (
                <span
                  key={t}
                  className="rounded bg-slate-700 px-1.5 py-0.5 text-xs font-medium text-blue-400"
                >
                  {t}
                </span>
              ))
            ) : (
              <span className="text-gray-600">No tickers</span>
            )}
            {source && (
              <>
                <span>|</span>
                <span>{source}</span>
              </>
            )}
            {newsAgeMs != null && (
              <>
                <span>|</span>
                <span>Age: {newsAgeMs}ms</span>
              </>
            )}
            {/* Strategy count for history view */}
            {strategies && strategies.length > 0 && (
              <>
                <span>|</span>
                <span className="text-green-400">
                  {strategies.length} strateg{strategies.length === 1 ? 'y' : 'ies'}
                </span>
              </>
            )}
          </div>
        </div>
        {expandable && (
          <button
            onClick={handleToggle}
            className="ml-2 p-1 text-gray-500 hover:text-white"
          >
            {expanded ? '\u25B2' : '\u25BC'}
          </button>
        )}
      </div>

      {/* Pipeline steps */}
      {expandable && expanded && (
        <div className="ml-4 mt-3 space-y-1 border-l-2 border-slate-700 pl-4">
          {pipelineLoading ? (
            <div className="text-sm text-gray-500">Loading pipeline...</div>
          ) : pipelineSteps && pipelineSteps.length > 0 ? (
            <>
              {pipelineSteps.map((step, i) => (
                <PipelineStepRow key={i} step={step} />
              ))}
              {/* Active position info */}
              {status === 'traded' && strategies?.some((s) => s.status === 'in_position') && (
                <ActivePositionInfo strategies={strategies} />
              )}
            </>
          ) : (
            <div className="text-sm text-gray-500">No pipeline data</div>
          )}
        </div>
      )}
    </div>
  )
}

function PipelineStepRow({ step }: { step: PipelineStep }) {
  const icon =
    step.status === 'pending'
      ? '\u23F3'
      : step.status === 'complete'
      ? '\u2713'
      : step.status === 'active'
      ? '\u{1F7E2}'
      : step.status === 'skipped'
      ? '\u23ED'
      : '\u274C'

  const colorClass =
    step.status === 'active'
      ? 'text-green-400'
      : step.status === 'skipped'
      ? 'text-gray-500'
      : step.status === 'error'
      ? 'text-red-400'
      : 'text-gray-300'

  return (
    <div className="flex items-center gap-2 text-sm">
      <span>{icon}</span>
      <span className={colorClass}>{step.label}</span>
      {step.detail && <span className="text-gray-500">| {step.detail}</span>}
    </div>
  )
}

function ActivePositionInfo({ strategies }: { strategies: FeedItemStrategy[] }) {
  const activeStrategy = strategies.find((s) => s.status === 'in_position')
  if (!activeStrategy) return null

  const exitIn = activeStrategy.exit_delay_seconds
    ? Math.floor(activeStrategy.exit_delay_seconds / 60)
    : 7

  return (
    <div className="mt-2 flex items-center gap-2 text-sm">
      <span>{'\u{1F7E2}'}</span>
      <span className="text-green-400">IN POSITION</span>
      <span className="text-gray-500">
        | {activeStrategy.qty} shares @ ${activeStrategy.entry_fill_price?.toFixed(2)} |
        Exit in: {exitIn}m
      </span>
    </div>
  )
}
