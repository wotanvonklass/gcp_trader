/**
 * Zustand store for Pako Web dashboard state management.
 */

import { create } from 'zustand'
import type {
  PipelineEvent,
  ActiveStrategy,
  FeedItem,
  FeedItemStrategy,
  FeedItemStatus,
  PipelineStep,
  NewsReceivedData,
  NewsDecisionData,
  StrategySpawnedData,
  OrderPlacedData,
  OrderFilledData,
  StrategyStoppedData,
  SummaryStats,
} from './types'

// ==============================================================================
// Store Types
// ==============================================================================

interface PakoState {
  // Connection state
  connected: boolean
  lastEventTime: string | null
  error: string | null

  // Event data
  events: PipelineEvent[]
  feedItems: Map<string, FeedItem>
  activeStrategies: Map<string, ActiveStrategy>

  // Stats
  summaryStats: SummaryStats | null

  // UI state
  paused: boolean
  soundEnabled: boolean
  selectedNewsId: string | null

  // Actions
  setConnected: (connected: boolean) => void
  setError: (error: string | null) => void
  setPaused: (paused: boolean) => void
  setSoundEnabled: (enabled: boolean) => void
  setSelectedNewsId: (newsId: string | null) => void
  setSummaryStats: (stats: SummaryStats | null) => void

  // Event handling
  addEvent: (event: PipelineEvent) => void
  setInitialState: (events: PipelineEvent[], strategies: ActiveStrategy[]) => void
  clearEvents: () => void

  // Computed getters
  getFeedItemsArray: () => FeedItem[]
  getActiveStrategiesArray: () => ActiveStrategy[]
  getActiveCount: () => number
  getPipelineSteps: (newsId: string) => PipelineStep[]
}

// ==============================================================================
// Helper Functions
// ==============================================================================

function createOrUpdateFeedItem(
  feedItems: Map<string, FeedItem>,
  event: PipelineEvent
): Map<string, FeedItem> {
  const newMap = new Map(feedItems)
  const newsId = event.news_id

  if (event.type === 'news_received') {
    const data = event.data as unknown as NewsReceivedData
    const item: FeedItem = {
      news_id: newsId,
      headline: data.headline,
      tickers: data.tickers,
      source: data.source,
      pub_time: data.pub_time,
      news_age_ms: data.news_age_ms,
      received_at: event.timestamp,
      status: 'processing',
      strategies: [],
    }
    newMap.set(newsId, item)
  } else if (event.type === 'news_decision') {
    const existing = newMap.get(newsId)
    if (existing) {
      const data = event.data as unknown as NewsDecisionData
      const status: FeedItemStatus =
        data.decision === 'trade' ? 'processing' : 'skipped'
      newMap.set(newsId, {
        ...existing,
        status,
        decision: data.decision,
        skip_reason: data.skip_reason,
        volume_found: data.volume_found,
      })
    }
  } else if (event.type === 'strategy_spawned') {
    const existing = newMap.get(newsId)
    if (existing) {
      const data = event.data as unknown as StrategySpawnedData
      const strategy: FeedItemStrategy = {
        strategy_id: data.strategy_id,
        strategy_type: data.strategy_type,
        ticker: data.ticker,
        status: 'pending_entry',
        position_size_usd: data.position_size_usd,
        entry_price: data.entry_price,
        exit_delay_seconds: data.exit_delay_seconds,
      }
      newMap.set(newsId, {
        ...existing,
        status: 'traded',
        strategies: [...existing.strategies, strategy],
      })
    }
  } else if (event.type === 'order_filled') {
    const existing = newMap.get(newsId)
    if (existing) {
      const data = event.data as unknown as OrderFilledData
      const strategies = existing.strategies.map((s) =>
        s.strategy_id === data.strategy_id
          ? {
              ...s,
              status: data.order_role === 'entry' ? 'in_position' : 'completed',
              ...(data.order_role === 'entry'
                ? { entry_fill_price: data.fill_price, qty: data.qty }
                : { exit_fill_price: data.fill_price }),
            }
          : s
      ) as FeedItemStrategy[]
      newMap.set(newsId, { ...existing, strategies })
    }
  } else if (event.type === 'strategy_stopped') {
    const existing = newMap.get(newsId)
    if (existing) {
      const data = event.data as unknown as StrategyStoppedData
      const strategies = existing.strategies.map((s) =>
        s.strategy_id === data.strategy_id
          ? { ...s, status: 'completed', pnl: data.pnl }
          : s
      ) as FeedItemStrategy[]
      newMap.set(newsId, { ...existing, strategies })
    }
  }

  return newMap
}

function updateActiveStrategies(
  strategies: Map<string, ActiveStrategy>,
  event: PipelineEvent
): Map<string, ActiveStrategy> {
  const newMap = new Map(strategies)

  if (event.type === 'strategy_spawned') {
    const data = event.data as unknown as StrategySpawnedData
    newMap.set(data.strategy_id, {
      id: data.strategy_id,
      news_id: event.news_id,
      ticker: data.ticker,
      strategy_type: data.strategy_type,
      side: data.side,
      position_size_usd: data.position_size_usd,
      status: 'pending_entry',
      entry_limit_price: data.entry_price,
      exit_delay_seconds: data.exit_delay_seconds,
      spawned_at: event.timestamp,
      headline: data.headline || '',
    })
  } else if (event.type === 'order_placed') {
    const data = event.data as unknown as OrderPlacedData
    const existing = newMap.get(data.strategy_id)
    if (existing && data.order_role === 'exit') {
      newMap.set(data.strategy_id, { ...existing, status: 'pending_exit' })
    }
  } else if (event.type === 'order_filled') {
    const data = event.data as unknown as OrderFilledData
    const existing = newMap.get(data.strategy_id)
    if (existing) {
      if (data.order_role === 'entry') {
        newMap.set(data.strategy_id, {
          ...existing,
          status: 'in_position',
          entry_fill_price: data.fill_price,
          qty: data.qty,
          entry_filled_at: event.timestamp,
        })
      } else if (data.order_role === 'exit') {
        newMap.set(data.strategy_id, { ...existing, status: 'pending_close' })
      }
    }
  } else if (event.type === 'strategy_stopped') {
    const data = event.data as unknown as StrategyStoppedData
    newMap.delete(data.strategy_id)
  }

  return newMap
}

function buildPipelineSteps(
  events: PipelineEvent[],
  newsId: string
): PipelineStep[] {
  const newsEvents = events.filter((e) => e.news_id === newsId)
  const steps: PipelineStep[] = []

  for (const event of newsEvents) {
    if (event.type === 'news_received') {
      const data = event.data as unknown as NewsReceivedData
      steps.push({
        label: data.news_age_ms != null
          ? `News received (${data.news_age_ms}ms old)`
          : 'News received',
        status: 'complete',
        timestamp: event.timestamp,
      })
    } else if (event.type === 'news_decision') {
      const data = event.data as unknown as NewsDecisionData
      if (data.decision === 'trade') {
        steps.push({
          label: `Decision: TRADE`,
          status: 'complete',
          detail: data.volume_found
            ? `Volume: ${data.volume_found.toFixed(0)} shares`
            : undefined,
          timestamp: event.timestamp,
        })
      } else {
        steps.push({
          label: `SKIP: ${data.skip_reason || 'unknown'}`,
          status: 'skipped',
          timestamp: event.timestamp,
        })
      }
    } else if (event.type === 'strategy_spawned') {
      const data = event.data as unknown as StrategySpawnedData
      steps.push({
        label: `Strategy ${data.strategy_id.split('_')[0]}_${data.ticker} spawned`,
        status: 'complete',
        detail: `$${data.position_size_usd.toFixed(0)} @ $${data.entry_price.toFixed(2)}`,
        timestamp: event.timestamp,
      })
    } else if (event.type === 'order_placed') {
      const data = event.data as unknown as OrderPlacedData
      const action = data.order_role === 'entry' ? 'Entry' : 'Exit'
      const side = data.side.toUpperCase()
      steps.push({
        label: `${action} order placed: ${side} ${data.qty} @ $${data.limit_price?.toFixed(2) || 'MKT'}`,
        status: 'complete',
        timestamp: event.timestamp,
      })
    } else if (event.type === 'order_filled') {
      const data = event.data as unknown as OrderFilledData
      const action = data.order_role === 'entry' ? 'Entry' : 'Exit'
      const slippageStr = data.slippage
        ? ` (slippage: $${data.slippage.toFixed(2)})`
        : ''
      steps.push({
        label: `${action} filled: ${data.qty} @ $${data.fill_price.toFixed(2)}${slippageStr}`,
        status: data.order_role === 'entry' ? 'active' : 'complete',
        timestamp: event.timestamp,
      })
    } else if (event.type === 'strategy_stopped') {
      const data = event.data as unknown as StrategyStoppedData
      const pnlStr = data.pnl
        ? ` P&L: $${data.pnl.toFixed(2)} (${data.pnl_percent?.toFixed(2)}%)`
        : ''
      steps.push({
        label: `Strategy stopped: ${data.reason}${pnlStr}`,
        status: 'complete',
        timestamp: event.timestamp,
      })
    }
  }

  return steps
}

// ==============================================================================
// Store
// ==============================================================================

export const usePakoStore = create<PakoState>((set, get) => ({
  // Initial state
  connected: false,
  lastEventTime: null,
  error: null,
  events: [],
  feedItems: new Map(),
  activeStrategies: new Map(),
  summaryStats: null,
  paused: false,
  soundEnabled: false,
  selectedNewsId: null,

  // Setters
  setConnected: (connected) => set({ connected }),
  setError: (error) => set({ error }),
  setPaused: (paused) => set({ paused }),
  setSoundEnabled: (enabled) => set({ soundEnabled: enabled }),
  setSelectedNewsId: (newsId) => set({ selectedNewsId: newsId }),
  setSummaryStats: (stats) => set({ summaryStats: stats }),

  // Event handling
  addEvent: (event) => {
    const { paused, events, feedItems, activeStrategies } = get()
    if (paused) return

    set({
      events: [...events.slice(-999), event], // Keep last 1000 events
      lastEventTime: event.timestamp,
      feedItems: createOrUpdateFeedItem(feedItems, event),
      activeStrategies: updateActiveStrategies(activeStrategies, event),
    })
  },

  setInitialState: (events, strategies) => {
    const feedItems = new Map<string, FeedItem>()
    const activeStrategies = new Map<string, ActiveStrategy>()

    // Process events to build feed items
    for (const event of events) {
      const updated = createOrUpdateFeedItem(feedItems, event)
      updated.forEach((v, k) => feedItems.set(k, v))
    }

    // Set active strategies
    for (const strategy of strategies) {
      activeStrategies.set(strategy.id, strategy)
    }

    set({
      events,
      feedItems,
      activeStrategies,
      lastEventTime: events.length > 0 ? events[events.length - 1].timestamp : null,
    })
  },

  clearEvents: () => {
    set({
      events: [],
      feedItems: new Map(),
      lastEventTime: null,
    })
  },

  // Computed getters
  getFeedItemsArray: () => {
    const items = Array.from(get().feedItems.values())
    return items.sort(
      (a, b) =>
        new Date(b.received_at).getTime() - new Date(a.received_at).getTime()
    )
  },

  getActiveStrategiesArray: () => {
    return Array.from(get().activeStrategies.values())
  },

  getActiveCount: () => {
    return get().activeStrategies.size
  },

  getPipelineSteps: (newsId) => {
    return buildPipelineSteps(get().events, newsId)
  },
}))
