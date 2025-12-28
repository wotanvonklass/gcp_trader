/**
 * Zustand store for Torbi Web dashboard state management.
 * Simplified version - no SSE, uses polling instead.
 */

import { create } from 'zustand'
import type {
  ActiveStrategy,
  SummaryStats,
} from './types'

// ==============================================================================
// Store Types
// ==============================================================================

interface TorbiState {
  // Active strategies (fetched via polling)
  activeStrategies: ActiveStrategy[]

  // Stats
  summaryStats: SummaryStats | null

  // UI state
  selectedNewsId: string | null

  // Actions
  setActiveStrategies: (strategies: ActiveStrategy[]) => void
  setSummaryStats: (stats: SummaryStats | null) => void
  setSelectedNewsId: (newsId: string | null) => void

  // Computed getters
  getActiveStrategiesArray: () => ActiveStrategy[]
  getActiveCount: () => number
}


// ==============================================================================
// Store
// ==============================================================================

export const useTorbiStore = create<TorbiState>((set, get) => ({
  // Initial state
  activeStrategies: [],
  summaryStats: null,
  selectedNewsId: null,

  // Setters
  setActiveStrategies: (strategies) => set({ activeStrategies: strategies }),
  setSummaryStats: (stats) => set({ summaryStats: stats }),
  setSelectedNewsId: (newsId) => set({ selectedNewsId: newsId }),

  // Computed getters
  getActiveStrategiesArray: () => get().activeStrategies,
  getActiveCount: () => get().activeStrategies.length,
}))
