// Render the video thumbnail from video/thumb.html.
//
//   node video/thumb.mjs        -> video/thumb-1920.png and video/thumb-1280.png
//
// Two sizes: 1920x1080 for anywhere that wants full resolution, and 1280x720
// because that is what YouTube and Devpost actually ask for. Both come from the
// same page at devicePixelRatio 2 and are downsampled, which is sharper than
// laying the page out at 1280 and hoping the type holds.

import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = await import(process.env.PW
  ? `file:///${process.env.PW.replace(/\\/g, '/')}/playwright/index.mjs`
  : 'playwright');

const browser = await chromium.launch({
  args: [
    '--force-color-profile=srgb',
    '--font-render-hinting=none',
    '--disable-lcd-text',
    '--hide-scrollbars',
    // Without these, headless Chromium falls back to SwiftShader and renders the
    // shadow map differently from the film it is meant to represent.
    '--use-gl=angle', '--use-angle=d3d11',
    '--enable-gpu', '--ignore-gpu-blocklist',
  ],
});
const page = await browser.newPage({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 2,
});

const problems = [];
page.on('pageerror', (e) => problems.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') problems.push('console: ' + m.text()); });

await page.goto(pathToFileURL(path.join(HERE, 'thumb.html')).href,
                { waitUntil: 'load', timeout: 120000 });
await page.evaluate(() => document.fonts.ready);
await page.waitForFunction(() => window.THUMB_READY === true, null, { timeout: 60000 });
await page.waitForTimeout(400);

await mkdir(HERE, { recursive: true });
await page.screenshot({ path: path.join(HERE, 'thumb-3840.png'), scale: 'device' });
console.log('wrote thumb-3840.png  3840x2160');

console.log(problems.length ? 'PAGE PROBLEMS:\n  ' + [...new Set(problems)].join('\n  ')
                            : 'no page errors');
await browser.close();
