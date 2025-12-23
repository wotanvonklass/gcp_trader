# PAKO Web App Test Plan

## Overview
Comprehensive test plan for the PAKO News Trading Monitor web application.

**Tech Stack:** React 19 + TypeScript + Vite + Tailwind CSS + Zustand + lightweight-charts
**API Endpoint:** http://35.236.202.231:8100
**Purpose:** Real-time monitoring dashboard for news-driven trading system

---

## Test Categories

### 1. Application Startup & Navigation
- [ ] App loads without console errors
- [ ] All 7 navigation tabs are visible and clickable
- [ ] Header displays correctly (PAKO logo, status, settings)
- [ ] Active strategy counter badge updates
- [ ] Trading mode selector (Paper/Live) works
- [ ] Connection indicator shows correct state (green/gray)

### 2. Live Feed View (`/`)
- [ ] Real-time news items appear as they arrive
- [ ] Status badges show correct state (processing/traded/skipped)
- [ ] Summary stats display (P&L, win rate, trade count)
- [ ] Pause button stops feed updates
- [ ] Sound toggle works
- [ ] Click on item navigates to Pipeline view
- [ ] Relative timestamps update correctly

### 3. Pipeline View (`/pipeline/:newsId`)
- [ ] Breadcrumb navigation works
- [ ] News details display (headline, tickers, source, time)
- [ ] Event timeline shows all pipeline stages
- [ ] Status indicators are color-coded correctly
- [ ] Candlestick chart renders with correct data
- [ ] Timeframe selector (1s/5s/15s/1m) updates chart
- [ ] News marker appears on chart at correct time
- [ ] Strategy execution details are accurate

### 4. Active Strategies View (`/active`)
- [ ] All active strategies display in grid
- [ ] Unrealized P&L updates in real-time
- [ ] P&L colors: green for profit, red for loss
- [ ] Exit countdown timer counts down correctly
- [ ] Manual Exit button sends request and updates UI
- [ ] Extend Timer button works (adds minutes)
- [ ] Cancel Order button works for pending orders
- [ ] Clicking strategy card shows detail view
- [ ] Position size, entry price, ticker display correctly

### 5. Trades View (`/trades`)
- [ ] Completed trades list displays
- [ ] Filter buttons work (all/winners/losers)
- [ ] Trade detail view shows candlestick chart
- [ ] Entry/exit markers appear on chart
- [ ] P&L calculation is accurate
- [ ] Trade timing information correct
- [ ] News headline and tickers display

### 6. News History View (`/history`)
- [ ] Historical news list loads
- [ ] Filter: traded only works
- [ ] Filter: skipped only works
- [ ] Symbol search filters correctly (with debounce)
- [ ] Limit selector changes results count
- [ ] URL reflects filter state
- [ ] Click navigates to detail view

### 7. Stats View (`/stats`)
- [ ] Period selector (1/7/30 days) works
- [ ] Summary cards show correct values (P&L, win rate, trades)
- [ ] Performance by hour table displays
- [ ] Performance by strategy table displays
- [ ] Data refreshes on period change

### 8. System Health View (`/health`)
- [ ] Component status cards display (News API, SSE, Trading)
- [ ] Status colors: green=healthy, yellow=degraded, red=error
- [ ] Latency metrics display (P50/P99)
- [ ] Event counts are accurate
- [ ] SSE client count updates
- [ ] Uptime information displays

### 9. SSE Real-time Streaming
- [ ] Initial connection establishes
- [ ] `connected` event received and processed
- [ ] `initial_state` loads existing data
- [ ] `active_strategies` updates strategy list
- [ ] `heartbeat` keeps connection alive
- [ ] Pipeline events update UI in real-time
- [ ] Reconnection works after disconnect (3s delay)
- [ ] Connection status indicator updates correctly

### 10. API Endpoints Testing
- [ ] `GET /health` returns status
- [ ] `GET /health/detailed` returns component health
- [ ] `GET /news` returns news list
- [ ] `GET /news?traded_only=true` filters correctly
- [ ] `GET /news/{symbol}` filters by ticker
- [ ] `GET /news/detail/{newsId}` returns full details
- [ ] `GET /strategies/active` returns active list
- [ ] `POST /strategies/{id}/exit` sends exit request
- [ ] `POST /strategies/{id}/extend?minutes=N` extends timer
- [ ] `GET /stats/summary?days=N` returns stats
- [ ] `GET /market/bars/{ticker}` returns OHLCV data

### 11. Chart Component
- [ ] Candlestick chart renders correctly
- [ ] Volume histogram displays below price
- [ ] EMA overlays (8/21/55) display if enabled
- [ ] Hover tooltips show OHLCV values
- [ ] Dark theme applied correctly
- [ ] Chart responds to window resize
- [ ] Markers (news/entry/exit) positioned correctly

### 12. Error Handling
- [ ] API errors show user-friendly message
- [ ] SSE disconnect shows disconnected state
- [ ] Invalid routes show 404 or redirect
- [ ] Empty states handled gracefully
- [ ] Loading states display during data fetch

### 13. Performance
- [ ] App loads in < 3 seconds
- [ ] No memory leaks during extended use
- [ ] Event buffer limited to 1000 items
- [ ] Smooth scrolling in long lists
- [ ] Chart updates don't cause lag

---

## Test Execution Log

### Session: Dec 22, 2025

| Test | Status | Notes |
|------|--------|-------|
| TypeScript build | PASS | Build completes in ~700ms, 66 modules |
| Code review | PASS | 8 issues identified, 5 fixed |
| Dev server startup | PASS | Server runs on port 5175 |
| Error Boundaries | ADDED | New component wraps Routes |
| SSE race condition | FIXED | Both events handled independently |
| Stale closure | FIXED | useEffect dependencies corrected |
| Non-functional UI | FIXED | Disabled selector, removed buttons |

**Browser Testing:** Chrome DevTools MCP unavailable - requires restart of Claude Code or MCP server.

**Manual Testing Recommended:**
1. Open http://localhost:5175 in browser
2. Check all 7 navigation tabs load correctly
3. Verify SSE connection (console logs show initial state)
4. Test error boundary by triggering component error
5. Verify News History symbol filter debounce works

---

## Issues Found (Code Review - Dec 22, 2025)

### Issue #1: Non-functional Trading Mode Selector
- **Location:** `src/App.tsx:74-87`
- **Description:** The Paper/Live dropdown selector in the header is a visual placeholder with no functionality.
- **Severity:** Medium
- **Fix:** Disabled the selector and added "Coming soon" tooltip
- **Status:** FIXED

### Issue #2: Non-functional Settings and Notifications Buttons
- **Location:** `src/App.tsx:78-88`
- **Description:** The Settings and Notifications buttons were visual placeholders.
- **Severity:** Low
- **Fix:** Removed the non-functional buttons from UI
- **Status:** FIXED

### Issue #3: SSE Initial State Race Condition
- **Location:** `src/hooks/useEventStream.ts:79-116`
- **Description:** The hook added a `once: true` listener for `active_strategies` inside the `initial_state` handler, creating a race condition.
- **Severity:** Medium
- **Fix:** Both events now independently store their data and call `trySetInitialState()` which only completes when both are ready
- **Status:** FIXED

### Issue #4: Symbol Filter Stale Closure
- **Location:** `src/components/NewsHistoryView.tsx:62-69`
- **Description:** The `useEffect` for symbol debouncing was missing `symbolFilter` and `setSymbolFilter` in dependency array.
- **Severity:** Low
- **Fix:** Added missing dependencies to useEffect
- **Status:** FIXED

### Issue #5: N+1 Query Problem in Trades View
- **Location:** `src/components/TradesView.tsx:78-103`
- **Description:** The component fetches news first, then iterates and makes an API call for each news item's strategies (`getNewsStrategies`). With 100 news items, this makes 100+ API calls.
- **Severity:** High - Causes slow loading and excessive API requests
- **Recommended Fix:** Create a bulk API endpoint or fetch strategies with news in a single call
- **Status:** Open

### Issue #6: No Error Boundaries
- **Location:** `src/App.tsx`, `src/components/ErrorBoundary.tsx`
- **Description:** The app lacked React Error Boundaries - component errors crashed the entire app.
- **Severity:** High
- **Fix:** Created ErrorBoundary component and wrapped Routes in App.tsx
- **Status:** FIXED

### Issue #7: Unrealized P&L Not Updated in Real-time
- **Location:** `src/store.ts` - `updateActiveStrategies` function
- **Description:** The store only updates active strategies on specific events (spawned, order_placed, order_filled, stopped). There's no mechanism to receive unrealized P&L updates from the server for live price changes.
- **Severity:** Medium - Users see stale P&L values unless server pushes updates
- **Status:** Open (may be server-side limitation)

### Issue #8: Chart Recreated on EMA Toggle
- **Location:** `src/components/TradingChart.tsx:64-257`
- **Description:** The entire chart (including all series) is destroyed and recreated when `emasVisible` state changes. This is expensive and causes visual flicker.
- **Severity:** Low - Performance impact when toggling EMAs
- **Recommended Fix:** Use chart series show/hide methods instead of recreating
- **Status:** Open

---

## Execution Workflow

### Phase 1: Setup
1. Start local dev server: `cd web && npm run dev`
2. Navigate browser to `http://localhost:5173`
3. Open DevTools to monitor console/network

### Phase 2: Systematic Testing (Browser Automation)
Use chrome-devtools MCP tools to:
- Take snapshots of each view
- Click through navigation
- Verify element visibility and content
- Test interactive elements (buttons, filters, inputs)
- Capture screenshots for documentation
- Check console for errors

### Phase 3: Test Execution Order
1. **App Startup** - Load app, check console, verify header
2. **Navigation** - Click through all 7 tabs
3. **Live Feed** - Check real-time updates, status badges
4. **Pipeline** - Select news item, verify chart, timeline
5. **Active Strategies** - Check cards, P&L, action buttons
6. **Trades** - View completed trades, filters, charts
7. **News History** - Test search, filters
8. **Stats** - Verify period selector, data display
9. **System Health** - Check status indicators

### Phase 4: Document & Fix
- Log all findings in this document
- Fix issues in code
- Re-test fixed items
- Iterate until all pass

---

## Files to Review During Testing

- `src/App.tsx` - Router and layout
- `src/api.ts` - API client functions
- `src/store.ts` - Zustand state management
- `src/hooks/useEventStream.ts` - SSE connection
- `src/components/*.tsx` - View components
- `src/utils.ts` - Formatting functions
- `src/types.ts` - TypeScript definitions

---

## Summary

### Fixes Applied (Dec 22, 2025)
1. **ErrorBoundary component** - New component at `src/components/ErrorBoundary.tsx`
2. **Routes wrapped** - ErrorBoundary wraps all routes in `App.tsx`
3. **SSE race condition** - `useEventStream.ts` now handles both initial events independently
4. **Stale closure** - NewsHistoryView useEffect dependencies fixed
5. **Non-functional UI** - Trading mode selector disabled, placeholder buttons removed

### Remaining Issues (Require API Changes)
- **Issue #5**: N+1 query in TradesView - needs bulk API endpoint
- **Issue #7**: Real-time P&L updates - needs server-side push of price updates
- **Issue #8**: Chart EMA toggle recreation - lower priority optimization

### Files Modified
- `src/App.tsx`
- `src/components/ErrorBoundary.tsx` (new)
- `src/components/index.ts`
- `src/hooks/useEventStream.ts`
- `src/components/NewsHistoryView.tsx`
