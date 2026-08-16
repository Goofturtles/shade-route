// Capture the stills the launch film is cut from, straight out of the running app.
//
// The film never draws a mock interface. Every product frame in it is a
// screenshot of this app answering the same query, so the numbers on screen
// cannot drift from the numbers the code produces.
//
//   1. start the server:  .venv/Scripts/python -m uvicorn app.main:app
//   2. node video/capture_footage.mjs
//   3. node video/render.mjs --scene video/scene.html --out video/shade-route-4k.mp4
//
// Playwright is a render-time tool, not a dependency of the app — §4 keeps the
// frontend free of any build step, and nothing here ships to a user.
//   npm i playwright   (anywhere; set PW to its node_modules if not alongside)

import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// A static import cannot take a computed specifier, and the module may live
// outside this folder, so resolve it at runtime.
const { chromium } = await import(process.env.PW
  ? `file:///${process.env.PW.replace(/\\/g, '/')}/playwright/index.mjs`
  : 'playwright');

const APP = process.env.APP || 'http://127.0.0.1:8000/';
const OUT = fileURLToPath(new URL('./footage/', import.meta.url));
await mkdir(OUT, { recursive: true });

const browser = await chromium.launch({
  args: ['--force-color-profile=srgb', '--font-render-hinting=none',
         '--disable-lcd-text', '--hide-scrollbars'],
});

// Wait for the example route to finish rather than for a fixed delay: the first
// run has to build the shade field, which takes far longer than any sleep worth
// hard-coding, and a short sleep silently yields an empty frame.
async function ready(page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => {
    const h = document.getElementById('hero');
    return h && !h.hidden;
  }, null, { timeout: 300000 });
  await page.waitForTimeout(4000);
  await page.evaluate(() => Promise.all(
    Array.from(document.images).filter(i => !i.complete)
      .map(i => new Promise(r => { i.onload = i.onerror = r; }))));
  await page.waitForTimeout(1200);
}

async function open(width, height, dpr, theme) {
  const page = await browser.newPage({
    viewport: { width, height }, deviceScaleFactor: dpr,
    colorScheme: theme === 'dark' ? 'dark' : 'light',
  });
  await page.goto(APP, { waitUntil: 'load', timeout: 120000 });
  if (theme === 'dark') {
    await page.evaluate(() => {
      const t = document.getElementById('theme-toggle');
      if (t && document.documentElement.getAttribute('data-theme') !== 'dark') t.click();
    });
  }
  await ready(page);
  return page;
}

async function shot(page, name, selector) {
  const target = selector ? page.locator(selector).first() : page;
  await target.screenshot({ path: path.join(OUT, name + '.png'), scale: 'device' });
  console.log('  ' + name);
}

// --- Whole-frame plates, 1920x1080 CSS at dpr 2 -> a true 3840x2160 -----------
console.log('full frames @2x:');
for (const theme of ['light', 'dark']) {
  const page = await open(1920, 1080, 2, theme);
  await shot(page, theme === 'light' ? 'full' : 'full-dark');
  await page.close();
}

// --- Panel close-ups at dpr 4 -------------------------------------------------
// A panel is only ~1400px wide inside the 4K plate, so filling a 3840px frame
// with one means upscaling it ~2.7x. Capturing at 4x instead keeps it native.
console.log('close-ups @4x:');
const page = await open(1500, 1000, 4, 'light');
await shot(page, 'big-directions', '#directions');
await shot(page, 'big-summary', '#summary-panel');

// --- The shadow field ---------------------------------------------------------
// The proof shot. The whole field arrives as ONE MultiPolygon, so Leaflet draws
// it as a single <path> with many subpaths — wait for any increase in the path
// count, not a large one, or this silently captures a map with no shadows on it.
const before = await page.evaluate(() => document.querySelectorAll('#map path').length);
const clicked = await page.evaluate(() => {
  const b = Array.from(document.querySelectorAll('button'))
    .find(x => /show shadows/i.test(x.textContent || ''));
  if (!b) return false;
  b.click();
  return true;
});
if (!clicked) throw new Error('shadow toggle not found');
await page.waitForFunction(n => document.querySelectorAll('#map path').length > n,
                           before, { timeout: 300000 });
await page.waitForTimeout(6000);
const after = await page.evaluate(() => document.querySelectorAll('#map path').length);
if (after <= before) throw new Error('shadow layer never rendered');
await shot(page, 'big-map-shadows', '.map-card');

await page.close();
await browser.close();
console.log('\nfootage -> ' + OUT);
