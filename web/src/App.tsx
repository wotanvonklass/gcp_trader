import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { useEventStream } from './hooks/useEventStream'
import { usePakoStore } from './store'
import {
  LiveFeedView,
  ActiveStrategiesView,
  PipelineView,
  TradesView,
  NewsHistoryView,
  StatsView,
  SystemHealthView,
  ErrorBoundary,
} from './components'

interface NavTab {
  to: string
  label: string
  sublabel?: string
}

const navTabs: NavTab[] = [
  { to: '/', label: 'Live', sublabel: 'Feed' },
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/active', label: 'Active' },
  { to: '/trades', label: 'Trades' },
  { to: '/history', label: 'News', sublabel: 'History' },
  { to: '/stats', label: 'Stats' },
  { to: '/health', label: 'System', sublabel: 'Health' },
]

function App() {
  // Connect to SSE stream
  useEventStream()

  // Get active strategies count from store
  const { getActiveStrategiesArray, connected } = usePakoStore()
  const activeStrategies = getActiveStrategiesArray().length

  return (
    <div className="min-h-screen bg-slate-900 text-gray-200">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-800">
        <div className="flex items-center justify-between px-4 py-3">
          {/* Logo */}
          <div className="flex items-center gap-4">
            <NavLink to="/" className="text-xl font-bold text-white hover:text-blue-400">
              PAKO
            </NavLink>
            {activeStrategies > 0 && (
              <NavLink
                to="/active"
                className="flex items-center gap-1.5 rounded-full bg-red-500/20 px-3 py-1 text-sm text-red-400 hover:bg-red-500/30"
              >
                <span className="h-2 w-2 animate-pulse rounded-full bg-red-500"></span>
                {activeStrategies} Active
              </NavLink>
            )}
            {/* Connection indicator */}
            <span
              className={`flex items-center gap-1.5 text-xs ${
                connected ? 'text-green-400' : 'text-gray-500'
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  connected ? 'bg-green-500' : 'bg-gray-500'
                }`}
              ></span>
              {connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>

          {/* Right side controls */}
          <div className="flex items-center gap-3">
            <div className="relative group">
              <select
                className="rounded-md bg-slate-700 px-3 py-1.5 text-sm text-gray-200 border border-slate-600 cursor-not-allowed opacity-60"
                disabled
                title="Trading mode switching coming soon"
              >
                <option>Paper</option>
                <option>Live</option>
              </select>
              <span className="absolute -bottom-6 left-1/2 -translate-x-1/2 hidden group-hover:block text-xs text-gray-500 whitespace-nowrap">
                Coming soon
              </span>
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <nav className="flex gap-1 px-4">
          {navTabs.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.to === '/' || tab.to === '/health' || tab.to === '/stats'}
              className={({ isActive }) =>
                `px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                  isActive
                    ? 'bg-slate-900 text-white border-t border-l border-r border-slate-700'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-slate-700/50'
                }`
              }
            >
              <div className="flex flex-col items-center leading-tight">
                <span>{tab.label}</span>
                {tab.sublabel && <span className="text-xs opacity-70">{tab.sublabel}</span>}
              </div>
            </NavLink>
          ))}
        </nav>
      </header>

      {/* Main Content */}
      <main className="p-4">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<LiveFeedView />} />
            <Route path="/pipeline" element={<PipelineView />} />
            <Route path="/pipeline/:newsId" element={<PipelineView />} />
            <Route path="/active" element={<ActiveStrategiesView />} />
            <Route path="/active/:strategyId" element={<ActiveStrategiesView />} />
            <Route path="/trades" element={<TradesView />} />
            <Route path="/trades/:strategyId" element={<TradesView />} />
            <Route path="/history" element={<NewsHistoryView />} />
            <Route path="/history/:newsId" element={<NewsHistoryView />} />
            <Route path="/stats" element={<StatsView />} />
            <Route path="/health" element={<SystemHealthView />} />
            {/* Redirect unknown routes to home */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  )
}

export default App
