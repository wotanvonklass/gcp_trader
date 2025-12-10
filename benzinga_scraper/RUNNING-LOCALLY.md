# Running the Scraper Locally

## Issue: Chrome Can't Launch in Remote Environments

The scraper is working correctly, but Chrome/Chromium cannot launch in remote environments like:
- Claude Code remote sessions
- SSH sessions
- VS Code Remote Development
- Other remote IDE connections

You'll see this error: `UniversalExceptionRaise: (os/kern) failure (5)` followed by `socket hang up`.

## Solution: Run on Your Local Machine

You need to run the scraper directly on your Mac (not through the IDE's remote environment).

### Option 1: Run in a New Terminal (Recommended)

1. Open a **new Terminal app** on your Mac (not the IDE's terminal)
2. Navigate to the project:
   ```bash
   cd /Users/wotanvonklass/Development/GCP-Trader/cloud-run-scraper
   ```

3. Run the scraper:
   ```bash
   # Simple version (standard Puppeteer)
   npm run dev:scraper:simple

   # Or with puppeteer-extra (has stealth plugin)
   npm run dev:scraper
   ```

4. You should see the browser launch and the scraper start working!

### Option 2: Test First

Test if Puppeteer works:
```bash
node test-puppeteer.js
```

If this succeeds, you're good to run the full scraper.

### What You'll See

When it works, you'll see output like:

```
🚀 Starting Benzinga Scraper (Local Dev Mode - Simple)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 Launching browser...
✓ Browser launched successfully
✓ Page created
📝 Opening login page...
⌨️  Typing credentials...
🔐 Clicking Log In...
✓ Logged in successfully
   Current URL: https://pro.benzinga.com/...
📊 Navigating to dashboard...
⏳ Waiting for Newsfeed to render...
✓ Newsfeed loaded (GLN/DJN content detected)
🔍 Injecting DOM observer...
✓ Observer attached and monitoring for news updates
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 STREAMING LIVE NEWS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Press Ctrl+C to stop

================================================================================
🆕  NEWS #1 DETECTED @ 2024-11-21T15:47:23.456Z
================================================================================
[News content here...]
================================================================================
```

## Files Created

- **`scraper-dev-simple.js`** - Uses standard Puppeteer (recommended for stability)
- **`scraper-dev.js`** - Uses puppeteer-extra with stealth plugin (more advanced)

Both implement the same MutationObserver approach for real-time news capture.

## Troubleshooting

### Still Getting Errors?

1. **Check you're in a local terminal**, not the IDE terminal
2. **Try with visible browser** to debug:
   - Edit `scraper-dev-simple.js`
   - Change `headless: "new"` to `headless: false`
   - You'll see Chrome open and can watch it work

3. **Check credentials** in `.env`:
   ```
   BENZINGA_EMAIL=your-email@example.com
   BENZINGA_PASSWORD=your-password
   ```

### For Production/Cloud Deployment

The remote environment issue only affects local development. When you deploy to:
- Google Cloud Run
- GCP Compute Engine
- Docker containers

The scraper will work fine because those environments are properly configured for headless Chrome.

## Next Steps

Once you verify it works locally:
1. You can integrate the MutationObserver approach into your production `index.js`
2. Add Pub/Sub publishing
3. Deploy to Cloud Run where it will work perfectly
