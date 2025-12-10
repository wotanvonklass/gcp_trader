const puppeteer = require('puppeteer');

async function test() {
  console.log('Testing Puppeteer launch...');
  console.log('Chrome executable path:', puppeteer.executablePath());

  try {
    console.log('Attempting to launch browser...');
    const browser = await puppeteer.launch({
      headless: "new",
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
      timeout: 30000,
    });

    console.log('✓ Browser launched successfully!');
    console.log('Browser version:', await browser.version());

    const page = await browser.newPage();
    console.log('✓ Page created successfully!');

    await page.goto('https://example.com');
    console.log('✓ Navigation successful!');
    console.log('Page title:', await page.title());

    await browser.close();
    console.log('✓ Test completed successfully!');
  } catch (error) {
    console.error('❌ Test failed:', error.message);
    console.error('Error name:', error.name);
    console.error('Full error:', error);
  }
}

test();
