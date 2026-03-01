const puppeteer = require('puppeteer');

(async () => {
    try {
        console.log("Launching browser...");
        const browser = await puppeteer.launch({ headless: 'new' });
        const page = await browser.newPage();

        page.on('console', msg => console.log('PAGE LOG:', msg.text()));
        page.on('pageerror', error => console.log('PAGE ERROR:', error.message));
        page.on('requestfailed', request => console.log('REQUEST FAILED:', request.url(), request.failure()?.errorText));

        console.log("Navigating to localhost:5173...");
        await page.goto('http://localhost:5173', { waitUntil: 'domcontentloaded', timeout: 10000 });

        // Wait another 2 seconds just to capture async errors
        await new Promise(r => setTimeout(r, 2000));

        await browser.close();
        console.log("Done");
    } catch (e) {
        console.error("Puppeteer script failed:", e);
    }
})();
