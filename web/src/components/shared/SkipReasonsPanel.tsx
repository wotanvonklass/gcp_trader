/**
 * Shared SkipReasonsPanel component - displays breakdown of skip reasons.
 */

export interface SkipReasonsPanelProps {
  skipReasons: Record<string, number>
}

export function SkipReasonsPanel({ skipReasons }: SkipReasonsPanelProps) {
  const entries = Object.entries(skipReasons)

  if (entries.length === 0) {
    return null
  }

  // Sort by count descending
  const sorted = entries.sort((a, b) => b[1] - a[1])

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <h3 className="mb-2 text-sm font-medium text-gray-400">Skip Reasons</h3>
      <div className="flex flex-wrap gap-4 text-sm">
        {sorted.map(([reason, count]) => (
          <span key={reason}>
            {reason.replace('skip_', '').replace(/_/g, ' ')}:{' '}
            <strong className="text-white">{count}</strong>
          </span>
        ))}
      </div>
    </div>
  )
}

/**
 * Helper to compute skip reasons from a list of items.
 */
export function computeSkipReasons<T extends { decision?: string; skip_reason?: string }>(
  items: T[]
): Record<string, number> {
  const skipReasons: Record<string, number> = {}

  for (const item of items) {
    if (item.decision?.startsWith('skip')) {
      const reason =
        item.skip_reason ||
        item.decision.replace('skip_', '').replace(/_/g, ' ')
      skipReasons[reason] = (skipReasons[reason] || 0) + 1
    }
  }

  return skipReasons
}
