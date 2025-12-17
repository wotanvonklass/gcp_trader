const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const express = require('express');
const path = require('path');
const fs = require('fs').promises;
const { PubSub } = require('@google-cloud/pubsub');

// Use stealth plugin to avoid detection
puppeteer.use(StealthPlugin());

// Add timestamps to all console output
const originalLog = console.log;
const originalError = console.error;
const originalWarn = console.warn;

const timestamp = () => new Date().toISOString();

console.log = (...args) => originalLog(`[${timestamp()}]`, ...args);
console.error = (...args) => originalError(`[${timestamp()}]`, ...args);
console.warn = (...args) => originalWarn(`[${timestamp()}]`, ...args);

// Configuration
const PORT = process.env.PORT || 8080;
const BENZINGA_EMAIL = process.env.BENZINGA_EMAIL;
const BENZINGA_PASSWORD = process.env.BENZINGA_PASSWORD;
const SCRAPE_INTERVAL = parseInt(process.env.SCRAPE_INTERVAL || '60000'); // 60 seconds default
const WEBHOOK_URL = process.env.WEBHOOK_URL;
const RUN_MODE = process.env.RUN_MODE || 'continuous'; // 'continuous' or 'single'
const PUBSUB_TOPIC = process.env.PUBSUB_TOPIC || 'benzinga-news';
const ENABLE_PUBSUB = process.env.ENABLE_PUBSUB !== 'false'; // Enabled by default

// Initialize Pub/Sub
const pubsub = ENABLE_PUBSUB ? new PubSub() : null;

// Initialize Express (required for Cloud Run health checks)
const app = express();
let scrapingActive = false;
let lastScrapedNews = [];
let browser = null;

// Monitoring state
let scraperStartTime = Date.now();
let lastNewsTime = null;
let newsCountLastHour = 0;
let newsTimestamps = [];

// Health check endpoint
app.get('/', (req, res) => {
  res.json({
    status: 'running',
    scrapingActive,
    lastNewsCount: lastScrapedNews.length,
    uptime: process.uptime(),
    mode: RUN_MODE
  });
});

// Manual trigger endpoint
app.get('/scrape', async (req, res) => {
  try {
    const news = await scrapeNews();
    res.json({
      success: true,
      newsCount: news.length,
      news: news.slice(0, 10) // Return first 10 items
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Get latest news endpoint
app.get('/news', (req, res) => {
  res.json({
    count: lastScrapedNews.length,
    news: lastScrapedNews
  });
});

/**
 * Initialize browser with extension
 */
async function initBrowser() {
  console.log('Initializing headless Chrome with Benzinga extension...');

  const extensionPath = path.join(__dirname, 'benzinga-addon');

  // Check if extension exists
  try {
    await fs.access(extensionPath);
    console.log(`✓ Extension found at: ${extensionPath}`);
  } catch (error) {
    console.error('❌ Extension not found at:', extensionPath);
    throw new Error('Benzinga extension not found');
  }

  browser = await puppeteer.launch({
    headless: true, // Set to true for production, false for local debugging
    executablePath: process.platform === 'darwin'
      ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
      : undefined, // Use bundled Chromium on Linux (GCP VM)
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-accelerated-2d-canvas',
      '--no-first-run',
      '--no-zygote',
      '--disable-gpu',
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`,
      '--window-size=1920,1080',
      '--disable-blink-features=AutomationControlled',
      '--disable-features=IsolateOrigins,site-per-process',
      '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ],
    defaultViewport: {
      width: 1920,
      height: 1080
    }
  });

  console.log('✓ Browser initialized with extension loaded');
  return browser;
}

/**
 * Login to Benzinga Pro
 */
async function loginToBenzinga(page) {
  console.log('Logging into Benzinga Pro...');

  if (!BENZINGA_EMAIL || !BENZINGA_PASSWORD) {
    throw new Error('BENZINGA_EMAIL and BENZINGA_PASSWORD environment variables required');
  }

  try {
    // Navigate to login page
    await page.goto('https://www.benzinga.com/pro/login', {
      waitUntil: 'networkidle2',
      timeout: 60000
    });

    console.log('✓ Loaded login page');

    // Wait a bit for page to fully load
    await page.waitForTimeout(3000);

    // Try multiple selectors for email input
    let emailInput = null;
    const emailSelectors = [
      'input[type="email"]',
      'input[name="email"]',
      'input[placeholder*="email" i]',
      'input[id*="email" i]',
      '#email',
      'input[type="text"]'
    ];

    for (const selector of emailSelectors) {
      try {
        await page.waitForSelector(selector, { timeout: 2000 });
        emailInput = selector;
        console.log(`✓ Found email input with selector: ${selector}`);
        break;
      } catch (e) {
        console.log(`✗ Selector ${selector} not found`);
      }
    }

    if (!emailInput) {
      // Debug: save screenshot and page HTML
      await page.screenshot({ path: '/opt/benzinga-scraper/screenshots/login-page-debug.png' });
      const html = await page.content();
      console.log('Login page HTML snippet:', html.substring(0, 1000));
      throw new Error('Could not find email input field');
    }

    await page.type(emailInput, BENZINGA_EMAIL);
    console.log('✓ Entered email');

    // Fill password
    await page.type('input[type="password"]', BENZINGA_PASSWORD);
    console.log('✓ Entered password');

    // Click login button and wait for navigation
    const loginButtons = await page.$x("//button[contains(., 'Log In')]");
    if (loginButtons.length === 0) {
      throw new Error('Login button not found');
    }

    // Click login and wait for URL change (SPA doesn't trigger full navigation)
    await loginButtons[0].click();

    // Wait for URL to change from login page (Benzinga redirects to dashboard after login)
    await page.waitForFunction(
      () => !window.location.href.includes('/login'),
      { timeout: 60000 }
    );

    // Give the SPA a moment to initialize
    await new Promise(resolve => setTimeout(resolve, 3000));

    console.log('✓ Logged into Benzinga Pro');
    console.log('Current URL after login:', page.url());
    return true;
  } catch (error) {
    console.error('❌ Login failed:', error.message);
    throw error;
  }
}

/**
 * Scrape news from Benzinga Pro
 */
async function scrapeNews() {
  if (!browser) {
    browser = await initBrowser();
  }

  const page = await browser.newPage();

  try {
    // Capture console messages from the page (including extension logs)
    page.on('console', msg => {
      const text = msg.text();
      if (text.includes('Benzinga') || text.includes('extension')) {
        console.log(`[Browser Console] ${text}`);
      }
    });

    // Login to Benzinga (stealth handled by puppeteer-extra-plugin-stealth)
    await loginToBenzinga(page);

    // Take screenshot after login
    const screenshotDir = '/opt/benzinga-scraper/screenshots';
    try {
      await fs.mkdir(screenshotDir, { recursive: true });
      await page.screenshot({
        path: `${screenshotDir}/after-login.png`,
        fullPage: true
      });
      console.log('📸 Screenshot saved: after-login.png');
    } catch (e) {
      console.log('Note: Could not save screenshot (may not have write permissions)');
    }

    // Force navigation to the actual application (not marketing site)
    console.log('Navigating to Benzinga Pro application...');
    const appUrls = [
      'https://pro.benzinga.com/',
      'https://pro.benzinga.com/app',
      'https://pro.benzinga.com/dashboard'
    ];

    let foundApp = false;
    for (const url of appUrls) {
      try {
        await page.goto(url, {
          waitUntil: 'networkidle2',
          timeout: 30000
        });
        await page.waitForTimeout(3000);

        const currentUrl = page.url();
        console.log(`After navigating to ${url}, current URL: ${currentUrl}`);

        // Check if we're on the actual app (has sidebar navigation)
        const hasAppInterface = await page.evaluate(() => {
          // Look for app-specific elements
          const appIndicators = [
            document.querySelector('[class*="Sidebar"]'),
            document.querySelector('[class*="Navigation"]'),
            document.querySelector('[class*="Newsfeed"]'),
            document.querySelector('[data-test*="sidebar"]'),
            document.querySelector('nav[class*="side"]')
          ];
          return appIndicators.some(el => el !== null);
        });

        if (hasAppInterface && currentUrl.includes('pro.benzinga.com')) {
          console.log(`✓ Found app interface at: ${currentUrl}`);
          foundApp = true;
          break;
        }
      } catch (e) {
        console.log(`Could not access ${url}: ${e.message}`);
      }
    }

    if (!foundApp) {
      console.log('⚠️  Could not find app interface, staying on current page');
    }

    // Wait for the newsfeed grid to load
    console.log('Waiting for newsfeed grid...');
    try {
      await page.waitForSelector('[role="grid"], [class*="Newsfeed"], [class*="virtualized"]', {
        timeout: 15000
      });
      console.log('✓ Newsfeed grid detected');
    } catch (e) {
      console.log('⚠️  Newsfeed grid not detected, continuing anyway...');
    }

    // Give extra time for news items to populate (news can take 20-30 seconds to load)
    console.log('Waiting for news items to populate (20 seconds)...');
    await page.waitForTimeout(20000);
    console.log('✓ Wait complete');

    // Take screenshot of news page
    try {
      await page.screenshot({
        path: `${screenshotDir}/news-page.png`,
        fullPage: true
      });
      console.log('📸 Screenshot saved: news-page.png');
    } catch (e) {
      // Ignore if can't save
    }

    // Check what the extension sees
    console.log('Checking extension status...');
    const extensionInfo = await page.evaluate(() => {
      return {
        hasBenzingaFunction: typeof window.getBenzingaNews === 'function',
        hasExtensionLoaded: typeof window.benzingaExtensionLoaded !== 'undefined',
        allWindowFunctions: Object.keys(window).filter(k => k.includes('benzinga') || k.includes('Benzinga'))
      };
    });
    console.log('Extension info:', JSON.stringify(extensionInfo, null, 2));

    // First, let's see what elements exist on the page
    console.log('Analyzing page structure...');
    const pageStructure = await page.evaluate(() => {
      const selectors = [
        '[role="row"]',
        '[role="grid"]',
        '[class*="News"]',
        '[class*="news"]',
        '[class*="Story"]',
        '[class*="story"]',
        '[class*="Feed"]',
        '[class*="feed"]',
        '[class*="Item"]',
        '[class*="item"]',
        'article',
        '[data-testid*="news"]',
        '[data-test*="news"]'
      ];

      const results = {};
      selectors.forEach(sel => {
        const elements = document.querySelectorAll(sel);
        results[sel] = {
          count: elements.length,
          sampleClass: elements.length > 0 ? elements[0].className : '',
          sampleHTML: elements.length > 0 ? elements[0].outerHTML.substring(0, 300) : ''
        };
      });
      return results;
    });

    console.log('Page structure analysis:', JSON.stringify(pageStructure, null, 2));

    // Try extension first, fallback to direct DOM scraping
    console.log('Extracting news...');
    let newsData = await page.evaluate(() => {
      // Try extension first
      if (typeof window.getBenzingaNews === 'function') {
        return { source: 'extension', news: window.getBenzingaNews() };
      }

      // Fallback: scrape directly from DOM
      const newsItems = [];
      const newsContainers = document.querySelectorAll('.NewsfeedStory');

      newsContainers.forEach((row, index) => {
        try {
          // Extract headline
          const headlineEl = row.querySelector('[class*="headline"], [class*="title"]');
          const headline = headlineEl ? headlineEl.textContent.trim() : '';

          // Extract tickers
          const tickerEls = row.querySelectorAll('[class*="ticker"], [class*="symbol"]');
          const tickers = Array.from(tickerEls).map(el => el.textContent.trim()).filter(Boolean);

          // Extract time
          const timeEl = row.querySelector('[class*="time"], [class*="timestamp"]');
          const time = timeEl ? timeEl.textContent.trim() : '';

          // Extract source
          const sourceEl = row.querySelector('[class*="source"]');
          const source = sourceEl ? sourceEl.textContent.trim() : 'Benzinga';

          if (headline) {
            newsItems.push({
              id: `news-${Date.now()}-${index}`,
              headline,
              tickers,
              time,
              source,
              capturedAt: new Date().toISOString()
            });
          }
        } catch (e) {
          // Skip malformed rows
        }
      });

      return {
        source: 'dom',
        news: newsItems,
        debug: {
          rowCount: newsContainers.length,
          sampleHTML: newsContainers.length > 0 ? newsContainers[0].outerHTML.substring(0, 500) : ''
        }
      };
    });

    console.log(`Debug: Found ${newsData.debug.rowCount} row elements`);
    if (newsData.debug.sampleHTML) {
      console.log(`Debug: Sample row HTML: ${newsData.debug.sampleHTML}`);
    }

    console.log(`✓ Scraped ${newsData.news.length} news items (source: ${newsData.source})`);
    if (newsData.news.length > 0) {
      console.log('Sample news item:', JSON.stringify(newsData.news[0], null, 2));
    }
    lastScrapedNews = newsData.news;

    // Send to webhook if configured
    if (WEBHOOK_URL && newsData.news.length > 0) {
      await sendToWebhook(newsData.news);
    }

    // Publish to Pub/Sub if enabled
    if (newsData.news.length > 0) {
      await publishToPubSub(newsData.news);
    }

    return newsData.news;
  } catch (error) {
    console.error('❌ Scraping error:', error.message);
    throw error;
  } finally {
    await page.close();
  }
}

/**
 * Send news data to webhook
 */
async function sendToWebhook(news) {
  try {
    const response = await fetch(WEBHOOK_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        source: 'benzinga_cloud_run',
        timestamp: new Date().toISOString(),
        count: news.length,
        news: news
      })
    });

    if (response.ok) {
      console.log(`✓ Sent ${news.length} news items to webhook`);
    } else {
      console.error('❌ Webhook error:', response.status, response.statusText);
    }
  } catch (error) {
    console.error('❌ Webhook error:', error.message);
  }
}

/**
 * Publish news to Pub/Sub
 */
async function publishToPubSub(news) {
  if (!ENABLE_PUBSUB || !pubsub) {
    return;
  }

  try {
    const topic = pubsub.topic(PUBSUB_TOPIC);

    // Publish each news item as a separate message (all fields included)
    const publishPromises = news.map(async (newsItem) => {
      const dataBuffer = Buffer.from(JSON.stringify(newsItem));

      try {
        const messageId = await topic.publishMessage({ data: dataBuffer });
        return messageId;
      } catch (error) {
        console.error('❌ Pub/Sub publish error:', error.message);
        throw error;
      }
    });

    await Promise.all(publishPromises);
    const traceIds = news.map(n => {
      const ticker = n.tickers?.length > 0 ? n.tickers.join(',') : 'NO_TICKER';
      return `${ticker}:${n.storyId || n.id || 'unknown'}`;
    }).join(', ');
    console.log(`✓ Published ${news.length} news items to Pub/Sub [TRACE:${traceIds}]`);
  } catch (error) {
    console.error('❌ Pub/Sub error:', error.message);
  }
}

/**
 * Publish heartbeat to Pub/Sub for monitoring
 */
async function publishHeartbeat() {
  if (!ENABLE_PUBSUB || !pubsub) {
    return;
  }

  try {
    const topic = pubsub.topic(PUBSUB_TOPIC);

    // Clean old timestamps (older than 1 hour)
    const oneHourAgo = Date.now() - 3600000;
    newsTimestamps = newsTimestamps.filter(ts => ts > oneHourAgo);
    newsCountLastHour = newsTimestamps.length;

    const uptime = Math.floor((Date.now() - scraperStartTime) / 1000);
    const minutesSinceLastNews = lastNewsTime
      ? Math.floor((Date.now() - lastNewsTime) / 60000)
      : null;

    const heartbeat = {
      type: 'heartbeat',
      status: 'active',
      timestamp: new Date().toISOString(),
      uptime,
      newsCountLastHour,
      lastNewsAt: lastNewsTime ? new Date(lastNewsTime).toISOString() : null,
      minutesSinceLastNews
    };

    const dataBuffer = Buffer.from(JSON.stringify(heartbeat));
    await topic.publishMessage({ data: dataBuffer });

    console.log(`💓 Heartbeat published - ${newsCountLastHour} news/hour, last news ${minutesSinceLastNews || 'N/A'} min ago`);
  } catch (error) {
    console.error('❌ Heartbeat publish error:', error.message);
  }
}

/**
 * Monitor DOM for real-time news updates
 */
async function startRealtimeMonitoring() {
  console.log('Starting real-time DOM monitoring...');
  scrapingActive = true;

  try {
    // Initialize browser and login
    if (!browser) {
      browser = await initBrowser();
    }

    const page = await browser.newPage();

    // Capture console messages from the browser
    page.on('console', msg => {
      console.log(`[Browser] ${msg.text()}`);
    });

    // Login (stealth handled by puppeteer-extra-plugin-stealth)
    await loginToBenzinga(page);

    // Navigate to dashboard (use domcontentloaded - networkidle2 never completes due to WebSocket activity)
    console.log('Navigating to dashboard...');
    await page.goto('https://pro.benzinga.com/dashboard', {
      waitUntil: 'domcontentloaded',
      timeout: 30000
    });

    // Wait for React to render - domcontentloaded fires early before components mount
    console.log('Waiting for React components to render...');
    await page.waitForTimeout(10000);

    // Wait for newsfeed to load (increased timeout for slow renders)
    await page.waitForSelector('.ReactVirtualized__Grid', { timeout: 45000 });
    await page.waitForTimeout(5000);
    console.log('✓ Newsfeed loaded, starting DOM monitoring...');

    // Take screenshot for debugging (optional - may fail locally)
    try {
      await page.screenshot({ path: '/opt/benzinga-scraper/screenshots/newsfeed-debug.png', fullPage: false });
      console.log('📸 Screenshot saved to screenshots/newsfeed-debug.png');
    } catch (e) {
      console.log('Note: Could not save screenshot (local environment)');
    }

    // Track published IDs to prevent duplicates
    const publishedIds = new Set();

    // CDP Console Interception - fast path for news detection
    page.on('console', async (msg) => {
      const text = msg.text();
      if (text.startsWith('CDP_NEWS:')) {
        try {
          const newsItems = JSON.parse(text.slice(9));

          // Filter duplicates
          const newItems = newsItems.filter(item => {
            const id = item.storyId || item.id;
            if (publishedIds.has(id)) return false;
            publishedIds.add(id);
            return true;
          });

          if (newItems.length > 0) {
            const firstItem = newItems[0];
            const traceId = firstItem?.storyId || firstItem?.id || 'unknown';
            const tickerStr = firstItem?.tickers?.length > 0 ? firstItem.tickers.join(',') : 'NO_TICKER';

            console.log(`🔔 New news detected: ${newItems.length} items`);
            for (const item of newItems) {
              const t = item.tickers?.length > 0 ? item.tickers.join(',') : 'NO_TICKER';
              const id = item.storyId || item.id || 'unknown';
              console.log(`📰 [TRACE:${t}:${id}] "${item.headline?.substring(0, 50)}..."`);
            }

            lastScrapedNews = newItems;
            const now = Date.now();
            lastNewsTime = now;
            newItems.forEach(() => newsTimestamps.push(now));

            await publishToPubSub(newItems);

            if (WEBHOOK_URL) {
              await sendToWebhook(newItems);
            }
          }
        } catch (e) {
          console.error('CDP parse error:', e.message);
        }
      }
    });

    // Inject monitoring script into the page
    await page.evaluate(() => {
      console.log('🔍 Setting up MutationObserver...');

      const processedIds = new Set();

      // Get story object from React fiber
      function getStoryFromFiber(element) {
        try {
          const fiberKey = Object.keys(element).find(k => k.startsWith('__reactFiber'));
          if (!fiberKey) return null;

          let current = element[fiberKey];
          for (let i = 0; i < 10 && current; i++) {
            if (current.pendingProps?.story) {
              return current.pendingProps.story;
            }
            current = current.return;
          }
        } catch (e) {
          console.error('[getStoryFromFiber] Error:', e.message);
        }
        return null;
      }

      function extractNewsFromElement(element) {
        try {
          const story = getStoryFromFiber(element);
          if (!story) return null;

          const storyId = story.storyId;
          const nodeId = story.nodeId;
          const id = storyId || nodeId;
          if (!id || processedIds.has(id)) return null;

          const headline = story.title;
          if (!headline) return null;

          const sourceObj = story.source || {};
          const tickers = story.tickers || [];
          const channels = story.channels || [];
          const quotes = story.quotes || [];

          processedIds.add(id);
          const tickerStr = tickers.length > 0 ? tickers.map(t => t.name || t).join(',') : 'NO_TICKER';
          console.log(`[TRACE:${tickerStr}:${storyId || id}] Extracted: ${headline.substring(0, 50)}... | ${story.createdAt}`);

          return {
            id,
            storyId,
            nodeId,
            headline,
            teaserText: story.teaserText || null,
            body: story.body || null,
            author: story.author || null,
            createdAt: story.createdAt,
            updatedAt: story.updatedAt,
            tickers: tickers.map(t => t.name || t),
            quotes,
            source: sourceObj.shortName || 'Benzinga',
            sourceGroup: sourceObj.group || null,
            sourceFull: sourceObj.fullName || null,
            channels: channels.map(c => c.name || c),
            tags: story.tags || [],
            sentiment: story.sentiment ?? null,
            isBzPost: story.isBzPost ?? false,
            isBzProPost: story.isBzProPost ?? false,
            partnerURL: story.partnerURL || null,
            eventId: story.eventId || null,
            capturedAt: new Date().toISOString()
          };
        } catch (e) {
          console.error('Error extracting news:', e);
          return null;
        }
      }

      // Process initial news items
      const initialItems = Array.from(document.querySelectorAll('.NewsfeedStory'))
        .map(extractNewsFromElement)
        .filter(Boolean);

      console.log(`📰 Initial news items: ${initialItems.length}`);

      // Set up MutationObserver
      const observer = new MutationObserver((mutations) => {
        const newItems = [];

        mutations.forEach((mutation) => {
          mutation.addedNodes.forEach((node) => {
            if (node.nodeType === 1) {
              // Check if the node itself is a news story
              if (node.classList && node.classList.contains('NewsfeedStory')) {
                const item = extractNewsFromElement(node);
                if (item) newItems.push(item);
              }

              // Check children for news stories
              const newsElements = node.querySelectorAll ? node.querySelectorAll('.NewsfeedStory') : [];
              newsElements.forEach(el => {
                const item = extractNewsFromElement(el);
                if (item) newItems.push(item);
              });
            }
          });
        });

        if (newItems.length > 0) {
          console.log(`🆕 Detected ${newItems.length} new items`);
          // Emit via console.log for CDP interception (Node.js picks this up)
          console.log('CDP_NEWS:' + JSON.stringify(newItems));
        }
      });

      // Start observing
      const targetNode = document.querySelector('.ReactVirtualized__Grid') || document.body;
      observer.observe(targetNode, {
        childList: true,
        subtree: true
      });

      console.log('✅ MutationObserver active - monitoring for new news');
    });

    console.log('✅ Real-time monitoring active!');

    // Start heartbeat publishing (every 5 minutes)
    const heartbeatInterval = setInterval(async () => {
      await publishHeartbeat();
    }, 5 * 60 * 1000);

    // Keep the page alive
    while (scrapingActive) {
      await new Promise(resolve => setTimeout(resolve, 60000));
      console.log('💓 Monitoring heartbeat - still active');
    }

    // Cleanup
    clearInterval(heartbeatInterval);

  } catch (error) {
    console.error('❌ Real-time monitoring error:', error);
    scrapingActive = false;
    throw error;
  }
}

/**
 * Graceful shutdown
 */
async function shutdown() {
  console.log('Shutting down gracefully...');
  scrapingActive = false;

  if (browser) {
    await browser.close();
  }

  process.exit(0);
}

// Handle shutdown signals
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

// Start the server
app.listen(PORT, async () => {
  console.log(`🚀 Benzinga Scraper started on port ${PORT}`);
  console.log(`📊 Mode: ${RUN_MODE}`);
  console.log(`⏱️  Scrape interval: ${SCRAPE_INTERVAL}ms`);
  console.log(`📬 Pub/Sub: ${ENABLE_PUBSUB ? `Enabled (topic: ${PUBSUB_TOPIC})` : 'Disabled'}`);

  if (RUN_MODE === 'continuous') {
    // Start real-time DOM monitoring
    startRealtimeMonitoring().catch(console.error);
  } else {
    console.log('💡 Trigger scraping via: GET /scrape');
  }
});
