import { useState } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { useTorbiStore } from './store'
import {
  ActiveStrategiesView,
  PipelineView,
  StatsView,
  SystemHealthView,
  ErrorBoundary,
} from './components'
import { NewsView } from './components/NewsView'
import { JournalView } from './components/JournalView'

interface NavTab {
  to: string
  label: string
}

const navTabs: NavTab[] = [
  { to: '/', label: 'News' },
  { to: '/positions', label: 'Positions' },
  { to: '/journal', label: 'Journal' },
]

function App() {
  // Get active strategies count from store
  const { getActiveStrategiesArray } = useTorbiStore()
  const activeStrategies = getActiveStrategiesArray().length

  // Settings dropdown state
  const [showSettings, setShowSettings] = useState(false)

  return (
    <div className="min-h-screen bg-slate-900 text-gray-200">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-800">
        <div className="flex items-center justify-between px-4 py-3">
          {/* Logo and main nav */}
          <div className="flex items-center gap-6">
            <NavLink to="/" className="text-xl font-bold text-white hover:text-blue-400">
              TORBI
            </NavLink>

            {/* Main Navigation Tabs */}
            <nav className="flex gap-1">
              {navTabs.map((tab) => (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  end={tab.to === '/'}
                  className={({ isActive }) =>
                    `px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                      isActive
                        ? 'bg-slate-700 text-white'
                        : 'text-gray-400 hover:text-gray-200 hover:bg-slate-700/50'
                    }`
                  }
                >
                  {tab.label}
                  {tab.to === '/positions' && activeStrategies > 0 && (
                    <span className="ml-1.5 inline-flex items-center justify-center h-5 w-5 text-xs rounded-full bg-red-500/20 text-red-400">
                      {activeStrategies}
                    </span>
                  )}
                </NavLink>
              ))}
            </nav>
          </div>

          {/* Right side: settings */}
          <div className="flex items-center gap-4">
            {/* Settings dropdown */}
            <div className="relative">
              <button
                onClick={() => setShowSettings(!showSettings)}
                className="p-2 rounded-md text-gray-400 hover:text-white hover:bg-slate-700 transition-colors"
                title="Settings"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </button>
              {showSettings && (
                <>
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setShowSettings(false)}
                  />
                  <div className="absolute right-0 top-full mt-1 w-40 bg-slate-800 border border-slate-700 rounded-md shadow-lg z-20">
                    <NavLink
                      to="/stats"
                      onClick={() => setShowSettings(false)}
                      className="block px-4 py-2 text-sm text-gray-300 hover:bg-slate-700 hover:text-white"
                    >
                      Stats
                    </NavLink>
                    <NavLink
                      to="/health"
                      onClick={() => setShowSettings(false)}
                      className="block px-4 py-2 text-sm text-gray-300 hover:bg-slate-700 hover:text-white"
                    >
                      System Health
                    </NavLink>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="p-4">
        <ErrorBoundary>
          <Routes>
            {/* Main views */}
            <Route path="/" element={<NewsView />} />
            <Route path="/news/:newsId" element={<PipelineView />} />
            <Route path="/positions" element={<ActiveStrategiesView />} />
            <Route path="/journal" element={<JournalView />} />
            <Route path="/journal/:tradeId" element={<JournalView />} />

            {/* Settings pages */}
            <Route path="/stats" element={<StatsView />} />
            <Route path="/health" element={<SystemHealthView />} />

            {/* Legacy redirects */}
            <Route path="/active" element={<Navigate to="/positions" replace />} />
            <Route path="/trades" element={<Navigate to="/journal" replace />} />
            <Route path="/history" element={<Navigate to="/" replace />} />
            <Route path="/pipeline" element={<Navigate to="/" replace />} />
            <Route path="/pipeline/:newsId" element={<Navigate to="/news/:newsId" replace />} />

            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  )
}

export default App
