// Score generator for the Shade Route film.
//
// Writes exactly 120.000 s of 48 kHz stereo. Everything is synthesised from
// scratch, so no licensed audio enters the repository - the same rule the rest
// of the project runs under - and the harmony can be pinned to the film's own
// cut points rather than to an arbitrary bar line.
//
//   node video/score.mjs [seconds] -> video/score.wav
//
// 90 BPM in 4/4, written half-time so the FELT pulse is 45 BPM: a resting heart
// rate, not a trailer. 20 frames to the beat, 80 to the bar, 45 bars in 3600
// frames - the grid is frame-integral at 30 fps by construction.
//
// Key of F major, with no leading tone anywhere: every cadence is plagal. A
// leading tone pulls, and this film is about a walk being made survivable
// rather than about winning, so nothing in it is allowed to sound triumphant.
//
// The one structural decision worth naming is section E: fourteen seconds of
// near nothing, immediately before the lift. Generated scores almost never
// leave a hole, and the hole is what makes the lift land.

import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SR = 48000;
const DUR = Number(process.argv[2]) || 120.0;
const N = Math.round(SR * DUR);
const BPM = 90, BEAT = 60 / BPM, BAR = BEAT * 4;

const L = new Float64Array(N);
const R = new Float64Array(N);
const SEND = new Float64Array(N);          // reverb bus

const nf = (n) => 440 * Math.pow(2, (n - 69) / 12);           // MIDI -> Hz
const M = { F2: 41, C3: 48, F3: 53, G3: 55, A3: 57, Bb3: 58, C4: 60, D4: 62,
            E4: 64, F4: 65, G4: 67, A4: 69, Bb4: 70, C5: 72, D5: 74 };

// Sections, in seconds, on the film's own cut points.
const SEC = {
  A: [0.00,    8.00],   // cold open - one pad voice, no bass, no rhythm
  B: [8.00,   24.00],   // premise   - felt piano enters
  C: [24.00,  34.00],   // the name  - sub enters, filter opens
  D: [34.00,  72.00],   // the body  - one element in and one out per block
  E: [72.00,  86.00],   // THE DROP  - near nothing
  F: [86.00, 102.00],   // the lift  - full arrangement, peak
  G: [102.00, 112.00],  // proof run - stripped, harmonic rhythm doubles
  H: [112.00, 116.00],  // limits    - pad and piano only
  I: [116.00, 120.00],  // endcard   - final chord, then air
};

// Three progressions in F. No V7 anywhere; the dominant appears only as Csus4.
const PROG1 = [[M.F2, M.C4, M.F4, M.A4],
               [M.Bb3, M.D4, M.F4, M.Bb4],
               [M.D4, M.F4, M.A4, M.D5],
               [M.C4, M.F4, M.G4, M.C5]];
const PROG2 = [[M.F2, M.C4, M.G4, M.C5],
               [M.Bb3, M.D4, M.F4, M.C5],
               [M.Bb3, M.D4, M.F4, M.Bb4],
               [M.F2, M.C4, M.G4, M.A4]];
const PROG3 = [[M.Bb3, M.D4, M.F4, M.C5],
               [M.D4, M.F4, M.A4, M.E4 + 12],
               [M.C4, M.G4, M.D5],
               [M.F2, M.A3, M.C4, M.F4]];

function progAt(t) {
  if (t < SEC.C[1]) return PROG1;
  if (t < SEC.E[0]) return PROG2;
  if (t < SEC.F[0]) return PROG1;
  if (t < SEC.G[0]) return PROG3;
  if (t < SEC.H[0]) return PROG2;
  return PROG1;
}
const chordAt = (t) => { const p = progAt(t); return p[Math.floor(t / BAR) % p.length]; };

const ramp = (a, b, x) => Math.max(0, Math.min(1, (x - a) / (b - a)));
function level(t) {
  if (t < 8)   return 0.34;
  if (t < 24)  return 0.42;
  if (t < 34)  return 0.52 + 0.08 * ramp(24, 34, t);
  if (t < 72)  return 0.60 + 0.20 * ramp(34, 72, t);
  if (t < 86)  return 0.38;                                   // the drop
  if (t < 102) return 0.80 + 0.20 * ramp(86, 92, t) - 0.08 * ramp(96, 102, t);
  if (t < 112) return 0.56;
  if (t < 116) return 0.46;
  return 0.48 * (1 - ramp(117.8, 120, t));
}

function add(i, l, r, send = 0) {
  if (i < 0 || i >= N) return;
  L[i] += l; R[i] += r; SEND[i] += send;
}

// ------------------------------------------------------------------ pad ----
// Seven detuned saws per voice through two one-pole lowpass stages. Detune is
// in CENTS, not Hz: in Hz the low voices beat far slower than the high ones and
// the bottom of the chord smears.
console.log('pad...');
{
  const CENTS = [-11, -7, -3, 0, 3, 7, 11];
  const ph = new Float64Array(CENTS.length * 4);
  let lp1 = 0, lp2 = 0;
  for (let i = 0; i < N; i++) {
    const t = i / SR;
    if (t >= SEC.E[0] && t < SEC.F[0]) continue;              // pad out for the drop
    const chord = chordAt(t);
    const g = level(t) * (t < SEC.B[0] ? 1.0 : 0.72);
    let s = 0;
    for (let v = 0; v < Math.min(chord.length, 4); v++) {
      const f = nf(chord[v]);
      for (let d = 0; d < CENTS.length; d++) {
        const k = v * CENTS.length + d;
        ph[k] = (ph[k] + (f * Math.pow(2, CENTS[d] / 1200)) / SR) % 1;
        s += (2 * ph[k] - 1) / (1 + v * 0.8);
      }
    }
    s /= CENTS.length * 3;
    // The cutoff opens across section C, on the film's own reveal.
    const cut = t < 24 ? 380 : t < 34 ? 380 + ((t - 24) / 10) * 1820 : 2200;
    const a = 1 - Math.exp((-2 * Math.PI * cut) / SR);
    lp1 += a * (s - lp1);
    lp2 += a * (lp1 - lp2);
    const out = lp2 * g * 0.5;
    add(i, out * 0.98, out * 1.02, out * 0.5);
  }
}

// ----------------------------------------------------------- felt piano ----
// Additive with inharmonicity plus 3 ms of hammer noise. The inharmonicity is
// what stops a stack of sines sounding like a test tone.
function piano(t0, midi, gain, dur = 3.2) {
  const f0 = nf(midi), B = 0.0004;
  const start = Math.floor(t0 * SR), len = Math.floor(dur * SR);
  for (let k = 0; k < len; k++) {
    const i = start + k, t = k / SR;
    if (i < 0 || i >= N) break;
    const env = Math.exp(-t * 1.15) * (1 - Math.exp(-t * 420));
    let s = 0;
    for (let h = 1; h <= 8; h++) {
      const fh = f0 * h * Math.sqrt(1 + B * h * h);
      s += Math.sin(2 * Math.PI * fh * t) / (h * h * 0.55 + 0.45);
    }
    let hammer = 0;
    if (t < 0.003) {
      const nse = (Math.sin((start + k) * 12.9898) * 43758.5453) % 1;
      hammer = nse * 0.5 * (1 - t / 0.003);
    }
    const out = (s * 0.33 + hammer) * env * gain;
    add(i, out * 0.94, out * 1.06, out * 0.55);
  }
}

// ----------------------------------------------------------------- bass ----
// Split: a mono sub at the fundamental with no reverb send, and an FM body an
// octave up. The split is what makes it survive a laptop speaker - the sub is
// felt on monitors, the body carries the note on a phone.
function bass(t0, midi, dur, gain) {
  const f = nf(midi);
  const start = Math.floor(t0 * SR), len = Math.floor(dur * SR);
  for (let k = 0; k < len; k++) {
    const i = start + k, t = k / SR;
    if (i < 0 || i >= N) break;
    const env = Math.min(1, t / 0.05) * Math.min(1, (dur - t) / 0.35);
    const sub = Math.tanh(Math.sin(2 * Math.PI * f * t) * 1.35) * 0.55;
    const idx = 1.6 * Math.exp(-t * 2.2) + 0.4;
    const body = Math.sin(2 * Math.PI * f * 2 * t + idx * Math.sin(2 * Math.PI * f * 2 * t));
    const out = (sub + body * 0.3) * env * gain;
    add(i, out, out, 0);                                       // zero reverb send
  }
}

function marimba(t0, midi, gain) {
  const f = nf(midi);
  const start = Math.floor(t0 * SR), len = Math.floor(1.1 * SR);
  for (let k = 0; k < len; k++) {
    const i = start + k, t = k / SR;
    if (i < 0 || i >= N) break;
    const env = Math.exp(-t * 5.5) * (1 - Math.exp(-t * 900));
    const idx = 2.6 * Math.exp(-t / 0.022);
    const s = Math.sin(2 * Math.PI * f * t + idx * Math.sin(2 * Math.PI * f * 4 * t));
    const out = s * env * gain;
    add(i, out * 1.05, out * 0.95, out * 0.4);
  }
}

// Karplus-Strong. A real decaying string costs about a dozen lines, and no
// stack of sines sounds like one.
function pluck(t0, midi, gain) {
  const f = nf(midi), start = Math.floor(t0 * SR);
  const nBuf = Math.max(2, Math.round(SR / f));
  const buf = new Float64Array(nBuf);
  let seed = (start * 2654435761) >>> 0;
  for (let k = 0; k < nBuf; k++) {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    buf[k] = (seed / 4294967296) * 2 - 1;
  }
  const len = Math.floor(2.6 * SR);
  let idx = 0, last = 0;
  for (let k = 0; k < len; k++) {
    const i = start + k;
    if (i < 0 || i >= N) break;
    const cur = buf[idx];
    const avg = 0.5 * (cur + last) * 0.9965;
    buf[idx] = avg;
    last = cur;
    idx = (idx + 1) % nBuf;
    const out = avg * Math.exp((-k / SR) * 1.1) * gain;
    add(i, out * 0.9, out * 1.1, out * 0.45);
  }
}

function shaker(t0, gain) {
  const start = Math.floor(t0 * SR), len = Math.floor(0.075 * SR);
  let seed = (start * 22695477) >>> 0, hp = 0;
  for (let k = 0; k < len; k++) {
    const i = start + k, t = k / SR;
    if (i < 0 || i >= N) break;
    seed = (seed * 1664525 + 1013904223) >>> 0;
    hp = 0.86 * (hp + ((seed / 4294967296) * 2 - 1) * 0.5);
    const out = hp * Math.exp(-t * 55) * (1 - Math.exp(-t * 3000)) * gain;
    add(i, out * 0.8, out * 1.2, out * 0.25);
  }
}

function kick(t0, gain) {
  const start = Math.floor(t0 * SR), len = Math.floor(0.5 * SR);
  for (let k = 0; k < len; k++) {
    const i = start + k, t = k / SR;
    if (i < 0 || i >= N) break;
    const f = 46 + (105 - 46) * Math.exp(-t / 0.045);          // pitch drop
    const out = Math.sin(2 * Math.PI * f * t) * Math.exp(-t * 8.5) * gain;
    add(i, out, out, 0);
  }
}

// ---------------------------------------------------------- arrangement ----
console.log('arrangement...');
const motif = [M.A4, M.C5, M.D5, M.C5, M.A4, M.G4, M.F4];

for (let bar = 0; bar * BAR < DUR; bar++) {
  const t = bar * BAR;
  const chord = chordAt(t);
  const inDrop = t >= SEC.E[0] && t < SEC.F[0];

  if (t >= SEC.C[0]) {
    if (inDrop) bass(t, chord[0] - 12, BAR * 0.9, 0.16);
    else bass(t, chord[0] - 12, BAR * 0.98, 0.26 * level(t) + 0.06);
  }

  if (t >= SEC.B[0] && !inDrop) {
    const oct = t >= SEC.F[0] && t < SEC.G[0] ? 12 : 0;        // motif up an octave in the lift
    piano(t, chord[1] + oct, 0.2 * level(t) + 0.05);
    piano(t + BEAT * 2, chord[2] + oct, 0.15 * level(t) + 0.04);
    if (t >= SEC.C[0]) {
      for (let s = 0; s < 4; s++) {
        if ((bar + s) % 3 === 0) {
          piano(t + s * BEAT, motif[(bar * 2 + s) % motif.length] + oct, 0.1 * level(t));
        }
      }
    }
  }

  // One element enters per block and one leaves: marimba in at D1, out at D4.
  if ((t >= 34 && t < 58) || (t >= SEC.G[0] && t < SEC.H[0])) {
    for (let s = 0; s < 4; s++) {
      if (s % 2 === 0 || (bar + s) % 3 === 0) {
        marimba(t + s * BEAT, chord[(s + 1) % chord.length], 0.13 * level(t) + 0.03);
      }
    }
  }

  if ((t >= 42 && t < SEC.E[0]) || (t >= SEC.F[0] && t < SEC.H[0])) {
    const div = t >= SEC.F[0] && t < SEC.G[0] ? 8 : 4;         // sixteenths in the lift
    const accents = [1.0, 0.55, 0.72, 0.5, 0.9, 0.5, 0.7, 0.48];
    for (let s = 0; s < div; s++) {
      const jitter = ((Math.sin((bar * 31 + s) * 12.9898) * 43758.5453) % 1) * 0.007;
      shaker(t + (s * BAR) / div + jitter, 0.055 * accents[s % 8] * (level(t) + 0.2));
    }
  }

  // The kick is a heartbeat: beats 1 and 3 only, never a backbeat.
  if ((t >= 50 && t < SEC.E[0]) || (t >= SEC.F[0] && t < SEC.G[0])) {
    kick(t, 0.3 * level(t));
    kick(t + BEAT * 2, 0.22 * level(t));
  }

  if (t >= 58 && t < SEC.E[0]) {
    for (let s = 0; s < 3; s++) pluck(t + s * BEAT * 1.3, chord[(s + 2) % chord.length] + 12, 0.11);
  }
  if (inDrop) pluck(t, chord[1] + 12, 0.13);                   // one note a bar, and nothing else
  if (t >= SEC.F[0] && t < SEC.G[0]) {
    for (let s = 0; s < 4; s++) pluck(t + s * BEAT, chord[s % chord.length] + 12, 0.09);
  }
}

// The final chord lands on the cut to the wordmark, and the piano quotes only
// the first three notes of the motif before stopping. An unfinished quotation
// reads as confidence; finishing it would read as a jingle.
{
  const t = SEC.I[0];
  for (const n of PROG1[0]) piano(t, n, 0.15);
  bass(t, PROG1[0][0] - 12, 3.4, 0.24);
  piano(t + 0.35, motif[0], 0.11);
  piano(t + 0.80, motif[1], 0.10);
  piano(t + 1.25, motif[2], 0.09);
}

// --------------------------------------------------------------- reverb ----
// Freeverb topology: eight damped combs into four allpasses. The delay lengths
// are the classic constants, scaled by 48/44.1 because they are quoted at
// 44.1 kHz and using them unscaled shortens the room by 9%.
console.log('reverb...');
function freeverb(buf) {
  const k = SR / 44100;
  const combs = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617]
    .map((d) => ({ b: new Float64Array(Math.round(d * k)), i: 0, s: 0 }));
  const aps = [556, 441, 341, 225]
    .map((d) => ({ b: new Float64Array(Math.round(d * k)), i: 0 }));
  const out = new Float64Array(buf.length);
  const fb = 0.86, damp = 0.28;
  for (let i = 0; i < buf.length; i++) {
    const x = buf[i] * 0.22;
    let acc = 0;
    for (const c of combs) {
      const v = c.b[c.i];
      acc += v;
      c.s = v * (1 - damp) + c.s * damp;
      c.b[c.i] = x + c.s * fb;
      c.i = (c.i + 1) % c.b.length;
    }
    acc *= 0.125;
    for (const a of aps) {
      const v = a.b[a.i];
      const y = -0.5 * acc + v;
      a.b[a.i] = acc + 0.5 * y;
      a.i = (a.i + 1) % a.b.length;
      acc = y;
    }
    out[i] = acc;
  }
  return out;
}

// High-pass the send at 280 Hz. Reverb on the low end is what turns a mix to
// mud, and it is the commonest tell of a score assembled in code.
{
  let hp = 0, prev = 0;
  const a = Math.exp((-2 * Math.PI * 280) / SR);
  for (let i = 0; i < N; i++) {
    hp = a * (hp + SEND[i] - prev);
    prev = SEND[i];
    SEND[i] = hp;
  }
}
{
  const wet = freeverb(SEND);
  for (let i = 0; i < N; i++) {
    L[i] += wet[i] * 0.92;
    R[i] += wet[i] * 0.88;
  }
}

// --------------------------------------------------------------- master ----
// BS.1770 K-weighting, so the level is set by measured loudness rather than by
// whichever single transient happens to be the tallest sample. Peak-normalising
// and then clipping hands the level of the whole film to one bell.
console.log('master...');
function biquad(x, b, a) {
  const out = new Float64Array(x.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < x.length; i++) {
    const y = b[0] * x[i] + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2;
    x2 = x1; x1 = x[i]; y2 = y1; y1 = y;
    out[i] = y;
  }
  return out;
}
function kWeight(x) {
  const shelf = biquad(x, [1.53512485958697, -2.69169618940638, 1.19839281085285],
                          [1, -1.69065929318241, 0.73248077421585]);
  return biquad(shelf, [1.0, -2.0, 1.0], [1, -1.99004745483398, 0.99007225036621]);
}
function lufs(l, r) {
  const kl = kWeight(l), kr = kWeight(r);
  const block = Math.round(SR * 0.4), step = Math.round(SR * 0.1);
  const loud = [];
  for (let s = 0; s + block < l.length; s += step) {
    let acc = 0;
    for (let i = s; i < s + block; i++) acc += kl[i] * kl[i] + kr[i] * kr[i];
    loud.push(-0.691 + 10 * Math.log10(acc / block + 1e-12));
  }
  const gated = loud.filter((v) => v > -70);
  if (!gated.length) return -70;
  const absMean = gated.reduce((a, v) => a + Math.pow(10, v / 10), 0) / gated.length;
  const relGate = -0.691 + 10 * Math.log10(absMean) - 10;
  const keep = gated.filter((v) => v > relGate);
  const mean = keep.reduce((a, v) => a + Math.pow(10, v / 10), 0) / Math.max(keep.length, 1);
  return -0.691 + 10 * Math.log10(mean + 1e-12);
}

const measured = lufs(L, R);
const TARGET = -16.0;
const gain = Math.pow(10, (TARGET - measured) / 20);
console.log(`  measured ${measured.toFixed(2)} LUFS -> static gain ${gain.toFixed(3)}`);

// A lookahead limiter, not tanh across the mix: tanh distorts everything in
// order to tame one peak; a limiter only moves where it has to.
const LOOK = Math.round(SR * 0.005);
const CEIL = Math.pow(10, -1.5 / 20);
const rel = Math.exp(-1 / (SR * 0.09));
let env = 1;
const bytes = Buffer.alloc(N * 4);
for (let i = 0; i < N; i++) {
  let peak = 0;
  for (let k = 0; k < LOOK; k += 8) {
    const j = i + k;
    if (j >= N) break;
    peak = Math.max(peak, Math.abs(L[j] * gain), Math.abs(R[j] * gain));
  }
  const need = peak > CEIL ? CEIL / peak : 1;
  env = need < env ? need : env * rel + need * (1 - rel);
  const fade = Math.min(1, i / SR / 0.6, (DUR - i / SR) / 1.2);
  const l = Math.max(-1, Math.min(1, L[i] * gain * env * fade));
  const r = Math.max(-1, Math.min(1, R[i] * gain * env * fade));
  bytes.writeInt16LE(Math.round(l * 32767), i * 4);
  bytes.writeInt16LE(Math.round(r * 32767), i * 4 + 2);
}

const header = Buffer.alloc(44);
header.write('RIFF', 0);
header.writeUInt32LE(36 + bytes.length, 4);
header.write('WAVE', 8);
header.write('fmt ', 12);
header.writeUInt32LE(16, 16);
header.writeUInt16LE(1, 20);
header.writeUInt16LE(2, 22);
header.writeUInt32LE(SR, 24);
header.writeUInt32LE(SR * 4, 28);
header.writeUInt16LE(4, 32);
header.writeUInt16LE(16, 34);
header.write('data', 36);
header.writeUInt32LE(bytes.length, 40);

writeFileSync(path.join(HERE, 'score.wav'), Buffer.concat([header, bytes]));
console.log(`wrote score.wav  ${DUR.toFixed(3)}s  ${N.toLocaleString()} samples  ` +
            `${(bytes.length / 1048576).toFixed(1)} MB`);
