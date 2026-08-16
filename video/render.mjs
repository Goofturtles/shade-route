// Render the Shade Route launch video.
//
// The scene is an ordinary web page, but it is NOT allowed to animate itself.
// CSS animations and requestAnimationFrame both run off the wall clock, and a
// wall clock does not survive a capture loop: a frame that takes 400 ms to
// screenshot would advance the animation 400 ms, so the output would stutter
// and would differ on every run. Instead the page exposes window.seek(frame),
// which sets every animated value as a pure function of the frame number. The
// renderer calls seek(n), screenshots, and moves on. Same input, same pixels,
// every time — and the capture can take as long as it likes.
//
//   node render.mjs --scene scene.html --out shade-route-4k.mp4 --fps 30
//
// Flags: --frames N   stop early (for quick previews)
//        --scale S    output scale, 1 = 4K (3840x2160), 0.5 = 1080p preview
//        --skip-capture  re-encode frames already on disk

import { spawn } from 'node:child_process';
import { mkdir, rm, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

// Playwright is a render-time tool and deliberately not a dependency of the app
// (§4 keeps the frontend build-step free). Point PW at its node_modules if it is
// installed somewhere other than alongside this script.
const { chromium } = await import(process.env.PW
  ? `file:///${process.env.PW.replace(/\\/g, '/')}/playwright/index.mjs`
  : 'playwright');

function arg(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  if (i === -1) return fallback;
  const next = process.argv[i + 1];
  return next && !next.startsWith('--') ? next : true;
}

const SCENE = arg('scene', 'scene.html');
const OUT = arg('out', 'shade-route-4k.mp4');
const FPS = +arg('fps', 30);
const SCALE = +arg('scale', 1);
const FRAME_LIMIT = arg('frames', null);
const SKIP_CAPTURE = !!arg('skip-capture', false);

// Authoring happens in 1920x1080 CSS pixels because those are the numbers a
// layout is comfortable to write in; the device pixel ratio does the upscale,
// so text is rasterised at full 4K rather than scaled up from 1080p.
const CSS_W = 1920, CSS_H = 1080;
const DPR = 2 * SCALE;

// Frames are large and transient — thousands of 4K PNGs — so they go to the
// system temp dir. Hard-coding one machine's profile path wrote into a stranger's
// home directory on another Windows box, and on POSIX path.join treated it as
// relative and created a literal "C:/Users/..." folder beside the script.
const FRAME_DIR = path.join(os.tmpdir(), 'shade-route-film', 'frames');
// Resolve against the working directory first, then against this script, so
// both `node video/render.mjs --scene video/scene.html` from the repo root and
// `node render.mjs --scene scene.html` from in here work. Resolving only
// against the script turned the documented command into video/video/scene.html.
function resolveIn(p) {
  const fromCwd = path.resolve(process.cwd(), p);
  return existsSync(fromCwd) ? fromCwd : path.resolve(HERE, p);
}
const scenePath = resolveIn(SCENE);
if (!existsSync(scenePath)) {
  console.error('scene not found: ' + SCENE);
  process.exit(1);
}
const outPath = path.isAbsolute(OUT) ? OUT : path.resolve(process.cwd(), OUT);
const sceneUrl = pathToFileURL(scenePath).href;

async function capture() {
  if (existsSync(FRAME_DIR)) await rm(FRAME_DIR, { recursive: true, force: true });
  await mkdir(FRAME_DIR, { recursive: true });

  const browser = await chromium.launch({
    args: [
      '--force-color-profile=srgb',
      '--font-render-hinting=none',
      '--disable-lcd-text',            // greyscale AA; subpixel fringes look like colour noise once encoded
      '--hide-scrollbars',
      '--disable-background-timer-throttling',
      '--force-device-scale-factor=' + DPR,
    ],
  });
  const page = await browser.newPage({
    viewport: { width: CSS_W, height: CSS_H },
    deviceScaleFactor: DPR,
    colorScheme: 'light',
  });

  const problems = [];
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') problems.push('console: ' + m.text()); });

  await page.goto(sceneUrl, { waitUntil: 'load', timeout: 120000 });

  // Nothing may be captured until every font and image is decoded, or the first
  // frames silently record fallback type and empty boxes.
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => Promise.all(
    Array.from(document.images)
      .filter(img => !img.complete)
      .map(img => new Promise(res => { img.onload = img.onerror = res; }))
  ));
  await page.waitForFunction(() => typeof window.seek === 'function' &&
                                   typeof window.TOTAL_FRAMES === 'number', null,
                             { timeout: 30000 });

  let total = await page.evaluate(() => window.TOTAL_FRAMES);
  if (FRAME_LIMIT) total = Math.min(total, +FRAME_LIMIT);

  console.log(`scene ${SCENE}`);
  console.log(`capturing ${total} frames at ${CSS_W * DPR}x${CSS_H * DPR} (${FPS} fps, ` +
              `${(total / FPS).toFixed(1)}s)`);

  const started = Date.now();
  for (let f = 0; f < total; f++) {
    await page.evaluate(n => window.seek(n), f);
    await page.screenshot({
      path: path.join(FRAME_DIR, String(f).padStart(5, '0') + '.png'),
      scale: 'device',
      animations: 'disabled',
    });
    if (f % 30 === 0 || f === total - 1) {
      const done = f + 1;
      const rate = done / ((Date.now() - started) / 1000);
      const left = (total - done) / Math.max(rate, 0.01);
      process.stdout.write(`\r  frame ${done}/${total}  ${rate.toFixed(1)} fps  ` +
                           `~${Math.round(left)}s left    `);
    }
  }
  process.stdout.write('\n');

  if (problems.length) {
    console.log('PAGE PROBLEMS:');
    for (const p of [...new Set(problems)].slice(0, 12)) console.log('  ' + p);
  } else {
    console.log('no page errors');
  }

  await browser.close();
  return total;
}

function encode() {
  // NVENC on the 4090 does 4K in realtime; libx264 would take many minutes.
  // yuv420p + Rec.709 tagging is what makes the file play correctly everywhere
  // instead of arriving washed out or green in QuickTime and browsers.
  // The score is optional: without it the film still encodes, just silent. With
  // it, -shortest trims whichever track runs long so a score generated for a
  // slightly different duration cannot leave a tail of black or of silence.
  const scorePath = path.join(HERE, 'score.wav');
  const hasScore = existsSync(scorePath);
  console.log(hasScore ? 'scoring from ' + scorePath : 'no score.wav — encoding silent');

  const args = [
    '-y',
    '-framerate', String(FPS),
    '-i', path.join(FRAME_DIR, '%05d.png'),
    ...(hasScore ? ['-i', scorePath] : []),
    ...(hasScore ? ['-c:a', 'aac', '-b:a', '192k', '-ac', '2', '-ar', '48000', '-shortest'] : []),
    '-c:v', 'h264_nvenc',
    '-preset', 'p7', '-tune', 'hq',
    '-rc', 'vbr', '-cq', '19', '-b:v', '0', '-maxrate', '90M', '-bufsize', '180M',
    '-profile:v', 'high', '-level', '5.2',
    '-pix_fmt', 'yuv420p',
    '-colorspace', 'bt709', '-color_primaries', 'bt709',
    '-color_trc', 'bt709', '-color_range', 'tv',
    '-movflags', '+faststart',
    outPath,
  ];
  console.log('encoding: ffmpeg ' + args.join(' '));
  return new Promise((resolve, reject) => {
    const ff = spawn('ffmpeg', args, { stdio: ['ignore', 'inherit', 'inherit'] });
    ff.on('close', code => code === 0 ? resolve() : reject(new Error('ffmpeg exit ' + code)));
    ff.on('error', reject);
  });
}

if (!SKIP_CAPTURE) {
  await capture();
} else {
  const n = (await readdir(FRAME_DIR)).filter(f => f.endsWith('.png')).length;
  console.log(`re-encoding ${n} existing frames`);
}
await encode();
console.log('\ndone ->', outPath);
