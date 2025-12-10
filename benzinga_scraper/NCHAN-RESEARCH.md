# Benzinga Nchan/WebSocket Research

## Overview

Research into Benzinga Pro's real-time news delivery mechanisms to potentially replace or supplement the DOM scraper.

## Discovered Endpoints

### 1. Nchan (Server-Sent Events)
- **URL**: `https://pro-live.benzinga.com/sub/news-alerts/`
- **Protocol**: EventSource (SSE)
- **Library**: NchanSubscriber (bundled in Benzinga Pro frontend)

### 2. Advanced News WebSocket ⭐ KEY FINDING
- **URL**: `wss://api.benzinga.com/api/v3/news/advanced/ws`
- **Protocol**: WebSocket with **JSON encoding** (NOT Protobuf!)
- **Auth**: Query param `?apikey=XXX` or session-based

#### Message Format (JSON)
```javascript
// Subscribe to news feed
{type: "news_sub", data: {fields: [...], limit: 100, id: "feedId", where: null}}

// Query news
{type: "news_query", data: {fields: [...], limit: 100, id: "queryId"}}
```

### 3. Quote WebSocket
- **URL**: `wss://pro-quote-v2.benzinga.com/quote/`
- **Purpose**: Real-time quotes (not news)

## Authentication Mechanism

### Session Key
- **Source**: `https://accounts.benzinga.com/api/v1/account/session/?allow_anonymous=true&include_perms=true&include_subs=true`
- **Format**: 32-character alphanumeric string (e.g., `u5nlu0nvopcvzhytu0ouajf41686ba0m`)
- **Associated User ID**: Available in session response

### Auth Header Patterns Found in Bundle
```javascript
// Pattern 1: Session header
headers.set("authorization", `session ${sessionKey}`)

// Pattern 2: x-session header
headers.set("x-session", sessionKey)

// Pattern 3: Cloudflare Access (for some endpoints)
headers: {
  "CF-Access-Client-Id": clientId,
  "CF-Access-Client-Secret": clientSecret
}
```

## Frontend Code Analysis

### NchanSubscriber Initialization
```javascript
new NchanSubscriber(`${window.env.NCHAN_ADDR}/news-alerts/`)
```

### Environment Variables (window.env) - Extracted Nov 2024
```javascript
{
  NCHAN_ADDR: "https://pro-live.benzinga.com/sub",
  ADV_NEWSFEED_URL: "wss://api.benzinga.com/api/v3/news/advanced/ws",
  QUOTE_ADDR: "wss://pro-quote-v2.benzinga.com/quote/",
  DATAAPI_KEY: "aH0FkLCohY5yxK6OEaJ28Zpv51Ze1GyY",  // Public data API key from bundle
  DATAAPI_ROOT: "https://data-api-pro.benzinga.com/rest/"
}
```

### Session Info (from authenticated page)
```javascript
sessionKey: "u5nlu0nvopcvzhytu0ouajf41686ba0m"  // 32-char, rotates
userId: 2393854
```

### NchanSubscriber Features
- Supports `withCredentials` option for cookie-based auth
- Supports custom headers via `headers` option
- Uses EventSource (SSE) as primary transport
- Falls back to long-polling if SSE unavailable

## Connection Attempts & Results

### Attempt 1: EventSource with Cookies
```javascript
new EventSource('https://pro-live.benzinga.com/sub/news-alerts/', { withCredentials: true })
```
**Result**: Connection error (readyState: 2 = CLOSED)

### Attempt 2: EventSource with Query Params
```javascript
new EventSource('https://pro-live.benzinga.com/sub/news-alerts/?session=xxx')
```
**Result**: Connection error

### Attempt 3: WebSocket with JSON Auth (OLD - incorrect)
```javascript
ws.send(JSON.stringify({ id: 1, sessionId: key, type: "AuthRequest" }))
```
**Result**: "Invalid message format" - Wrong message format

### Attempt 4: WebSocket with DATAAPI_KEY ✅ CONNECTED
```javascript
const ws = new WebSocket('wss://api.benzinga.com/api/v3/news/advanced/ws?apikey=aH0FkLCohY5yxK6OEaJ28Zpv51Ze1GyY');
ws.send(JSON.stringify({type: 'news_sub', data: {fields: [...], limit: 100, id: 'feed-id', where: null}}));
```
**Result**: Connected! Got `news_sub_confirm` response. Connection closes after ~60s of inactivity.

### Attempt 5: WebSocket with Session Key ⚠️ PARTIAL SUCCESS
```javascript
const ws = new WebSocket('wss://api.benzinga.com/api/v3/news/advanced/ws?session=SESSION_KEY');
ws.send(JSON.stringify({type: 'news_sub', data: {fields: [...], limit: 100, id: 'feed', where: null}}));
```
**Result**:
- ✅ Connected and stays open
- ✅ Subscription confirmed (`news_sub_confirm`)
- ❌ No actual news received (page received news but WS didn't)

### Attempt 6: Nchan SSE with Session Key ❌ FAILED
```javascript
new EventSource('https://pro-live.benzinga.com/sub/news-alerts/?session=SESSION_KEY', {withCredentials: true})
```
**Result**: Connection closed (state=2). Auth not working from our context.

## Current Status (Nov 2024)

**The page receives news via Nchan SSE** - Found these endpoints in network:
- `https://pro-live.benzinga.com/sub/news-alerts/?session=XXX`
- `https://pro-live.benzinga.com/sub/news-alerts/?token=XXX`

**Our attempts don't receive news** - WebSocket subscription confirms but news doesn't flow.

### Query Test Results
```javascript
// Query returns content: null despite "filter.match" success
{type: "news_query_resp", result: {code: "filter.match"}, data: {content: null}}
```
This suggests **the API key/session doesn't have permission to access actual news content** - only connection is allowed.

### Likely Cause
- The DATAAPI_KEY (`aH0FkLCohY5yxK6OEaJ28Zpv51Ze1GyY`) is for public data, not news content
- News content requires Pro subscription authentication (cookies, not just session key)
- The page receives news via Nchan SSE with cookies, not this WebSocket

## Key Findings

1. **⭐ NEWS WEBSOCKET USES JSON!** - The advanced news WebSocket (`wss://api.benzinga.com/api/v3/news/advanced/ws`) uses **JSON encoding**, NOT Protobuf. This makes direct connection much simpler!

2. **Quote WebSocket uses Protobuf** - Only the quote WebSocket (`wss://pro-quote-v2.benzinga.com/quote/`) uses Protobuf (quotestore namespace). News is JSON.

3. **Auth via apikey query param** - WebSocket connections use `?apikey=XXX` query parameter for authentication (found in ScannerEnvironment pattern)

4. **Nchan requires specific auth** - Neither cookies alone nor query params work from a different origin (CORS)

5. **Session cookie domain** - Auth cookies are scoped to `.benzinga.com` domain, making cross-origin requests difficult

6. **Hardcoded DATAAPI_KEY** - Bundle contains public API key `aH0FkLCohY5yxK6OEaJ28Zpv51Ze1GyY` for data API access

## Cookies Present (on pro.benzinga.com)

- `bz_access_type=subscribed`
- `has_bz_account=1`
- `csrftoken=xxx`
- `intercom-session-ez0ugkdw=xxx`
- Various analytics cookies

## Next Steps

### Option A: Direct JSON WebSocket Connection ⭐ NEW BEST OPTION
1. Connect to `wss://api.benzinga.com/api/v3/news/advanced/ws` with apikey/session
2. Send JSON subscription message: `{type: "news_sub", data: {...}}`
3. Receive JSON news events directly
4. Forward to Pub/Sub

**Pros**: No Protobuf needed! Direct WebSocket, lowest latency, simple JSON
**Cons**: Need to determine exact auth mechanism (apikey vs session)

**TODO**: Test connection with DATAAPI_KEY or session key in query params

### Option B: Puppeteer WebSocket Interception (Medium)
1. Use Puppeteer to login and navigate to dashboard
2. Intercept WebSocket messages via CDP (Chrome DevTools Protocol)
3. Forward decoded news events to Pub/Sub

**Pros**: Uses existing auth, guaranteed to work
**Cons**: Still requires Puppeteer/browser, adds complexity

### Option C: Enhance DOM Scraper (Current)
1. Keep current MutationObserver-based scraper
2. Improve extraction reliability
3. Add redundancy/failover

**Pros**: Already working, simple, maintainable
**Cons**: Higher latency than direct WebSocket

### Option D: Nchan from Same Origin - PARTIAL SUCCESS! (Nov 2024)

**BREAKTHROUGH:** Page logs Nchan messages to console!

```javascript
// Console output format:
console.log("Nchan Message:", JSON.stringify({
  Type: "newsdesk",
  Origin: "newsdesk-backend/1",
  SentAt: "2025-11-24T20:44:13.607983423Z",
  Payload: {
    _id: "6924c39d21a45000013d47ee",
    notificationType: "notice",
    title: "...",
    url: "...",
    startDate: "...",
    endDate: "..."
  }
}));
```

**Working approach:** Intercept `console.log` to capture Nchan messages:
```javascript
const origLog = console.log;
console.log = function(...args) {
  const str = args.join(' ');
  if (str.includes('Nchan Message:')) {
    // Extract and process the JSON payload
    // Forward to Pub/Sub
  }
  return origLog.apply(console, args);
};
```

**Pros**: Actually works! Can capture real-time Nchan messages
**Cons**: Relies on Benzinga keeping console.log statements (could be removed)

## Live Testing Results (Nov 24, 2024)

### Nchan Message Types Discovered

**Type: `newsdesk`** - Analyst commentary/chat
- Example: `"Stopped at the 50dma. Do we recapture next? HH sta..."`
- These are NOT actual news articles - they're analyst notes
- Captured via console.log intercept ✅

**Actual News Articles** - NOT coming through Nchan `newsdesk` type
- Example: "Copper Mountain Technologies Unveils Next-Generation..."
- Detected via DOM only (`[DOM-only]` in logs)
- Must come through different Nchan type or mechanism

### Key Observation
The Nchan console.log intercept captures `newsdesk` type messages (analyst chat), but actual press releases/news articles appear to come through a different channel or aren't logged to console.

### Latency Tracking Status
- ✅ Infrastructure working (processNchanMessage, checkNchanLatency)
- ✅ Console.log intercept captures `newsdesk` messages
- ⚠️ Actual news articles NOT matched - different source
- DOM scraper remains the primary/only method for actual news

## Recommendation (Updated Nov 2024)

### What Works
- **Option D (Console.log intercept)** ✅ - Page logs `Nchan Message:` to console, can intercept!
- **Option C (DOM scraper)** ✅ - Already working in production

### What Failed
- **Option A (Direct WebSocket)** - Connects but `content: null` (auth insufficient)
- **Option B (CDP interception)** - Too complex, EventSource messages bypass JS
- **Direct EventSource** - Bundle creates ES before inject can intercept

### Final Recommendation

**Two viable approaches:**

1. **Console.log interception (Option D - NEW!)** - Lower latency
   - Intercept `console.log` in Puppeteer via `page.evaluate()`
   - Capture messages containing "Nchan Message:"
   - Parse JSON payload and forward to Pub/Sub
   - ⚠️ Risk: Benzinga could remove console.log statements

2. **DOM scraper (Option C - CURRENT)** - More stable
   - MutationObserver on newsfeed container
   - Already working, proven stable
   - ~100ms latency after Nchan

**Recommended strategy:**
- Keep DOM scraper as primary (stable, working)
- Optionally add console.log intercept as secondary/fallback
- Both run in same Puppeteer instance for redundancy

## Code Snippets for Future Reference

### Test JSON WebSocket Connection (Node.js)
```javascript
const WebSocket = require('ws');

// Try with DATAAPI_KEY
const ws = new WebSocket('wss://api.benzinga.com/api/v3/news/advanced/ws?apikey=aH0FkLCohY5yxK6OEaJ28Zpv51Ze1GyY');

// Or try with session key
// const ws = new WebSocket('wss://api.benzinga.com/api/v3/news/advanced/ws?session=YOUR_SESSION_KEY');

ws.on('open', () => {
  console.log('Connected!');

  // Subscribe to news
  ws.send(JSON.stringify({
    type: 'news_sub',
    data: {
      fields: ['id', 'headline', 'tickers', 'created'],
      limit: 100,
      id: 'test-feed',
      where: null
    }
  }));
});

ws.on('message', (data) => {
  console.log('Received:', data.toString());
});

ws.on('error', (err) => {
  console.error('Error:', err.message);
});

ws.on('close', (code, reason) => {
  console.log('Closed:', code, reason.toString());
});
```

### Getting Session Key (from authenticated page)
```javascript
const resp = await fetch('https://accounts.benzinga.com/api/v1/account/session/?allow_anonymous=true&include_perms=true&include_subs=true', {
  credentials: 'include'
});
const data = await resp.json();
const sessionKey = data.key; // e.g., "u5nlu0nvopcvzhytu0ouajf41686ba0m"
```

### NchanSubscriber Usage (within page context)
```javascript
const subscriber = new NchanSubscriber('https://pro-live.benzinga.com/sub/news-alerts/');
subscriber.on('message', (message) => {
  console.log('News alert:', message);
});
subscriber.start();
```
