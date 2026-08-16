// Score generator for the Shade Route film.
//
// Writes a 107-second 48 kHz stereo WAV. Everything is synthesised from
// scratch — detuned sine partials with real envelopes, a Schroeder reverb and a
// soft limiter — so there is no licence attached to the output and no
// third-party asset in the repository, which is the same constraint the rest of
// the project runs under. It also means the harmony can be pinned to the film's
// own cuts rather than to an arbitrary bar line.
//
//   node video/score.mjs [seconds] → video/score.wav
//
// The progression sits in A minor and resolves to C major on the sign-off. The
// film is about a walk being made survivable, not about winning, so it stays
// warm and low rather than triumphant, and the two explanatory scenes drop to
// almost nothing so the diagram can be read rather than scored over.

import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SR = 48000;
const DUR = Number(process.argv[2]) || 107.0;
const N = Math.round(SR * DUR);

const NOTE = {
  A1: 55.00, C2: 65.41, D2: 73.42, E2: 82.41, F2: 87.31, G2: 98.00,
  A2: 110.00, B2: 123.47, C3: 130.81, D3: 146.83, E3: 164.81, F3: 174.61, G3: 196.00,
  A3: 220.00, B3: 246.94, C4: 261.63, D4: 293.66, E4: 329.63, F4: 349.23,
  G4: 392.00, A4: 440.00, C5: 523.25, E5: 659.25, G5: 783.99, A5: 880.00,
};

// Section boundaries are the film's own cut points, in seconds, so the harmony
// turns where the picture does. `level` is the pad gain for that section.
const SECTIONS = [
  { at:   0.0, chord: [NOTE.A2, NOTE.E3, NOTE.A3],                   level: 0.30 }, // every map optimises for time
  { at:   5.0, chord: [NOTE.A2, NOTE.C3, NOTE.E3, NOTE.A3],          level: 0.38 }, // Marisol
  { at:  11.0, chord: [NOTE.F2, NOTE.C3, NOTE.F3, NOTE.A3],          level: 0.42 }, // the arterial — unresolved
  { at:  16.0, chord: [NOTE.G2, NOTE.D3, NOTE.G3, NOTE.B3],          level: 0.52 }, // shade isn't on the map
  { at:  20.0, chord: [NOTE.C3, NOTE.G3, NOTE.C4, NOTE.E4],          level: 0.62 }, // the name
  { at:  24.0, chord: [NOTE.A2, NOTE.E3, NOTE.A3, NOTE.C4],          level: 0.58 }, // the product
  { at:  30.0, chord: [NOTE.F2, NOTE.C3, NOTE.F3, NOTE.A3],          level: 0.64 }, // 44 against 85
  { at:  37.0, chord: [NOTE.A2, NOTE.E3, NOTE.A3],                   level: 0.34 }, // act 01 — pull back
  { at:  40.0, chord: [NOTE.D2, NOTE.A2, NOTE.D3, NOTE.F3],          level: 0.30 }, // the geometry — quietest
  { at:  49.0, chord: [NOTE.E2, NOTE.B2, NOTE.E3, NOTE.G3],          level: 0.36 }, // the cost function
  { at:  57.0, chord: [NOTE.A2, NOTE.E3, NOTE.A3, NOTE.C4],          level: 0.58 }, // the shadow field
  { at:  64.0, chord: [NOTE.F2, NOTE.C3, NOTE.F3, NOTE.A3],          level: 0.60 }, // when should she leave
  { at:  72.0, chord: [NOTE.C3, NOTE.G3, NOTE.C4, NOTE.E4],          level: 0.60 }, // benches
  { at:  78.0, chord: [NOTE.G2, NOTE.D3, NOTE.G3, NOTE.B3],          level: 0.62 }, // read without the map
  { at:  84.0, chord: [NOTE.A2, NOTE.E3, NOTE.A3, NOTE.C4, NOTE.E4], level: 0.68 }, // what it is built out of
  { at:  91.0, chord: [NOTE.D2, NOTE.A2, NOTE.D3],                   level: 0.28 }, // limitations — almost bare
  { at:  99.0, chord: [NOTE.C3, NOTE.G3, NOTE.C4, NOTE.E4, NOTE.G4], level: 0.72 }, // home
];

function sectionWeights(t) {
  // Cross-fade between neighbouring sections so the harmony turns rather than
  // switches. 1.5 s is long enough to be inaudible as an edit.
  const XF = 1.5;
  const w = new Array(SECTIONS.length).fill(0);
  let idx = 0;
  for (let i = 0; i < SECTIONS.length; i++) if (t >= SECTIONS[i].at) idx = i;
  w[idx] = 1;
  const next = SECTIONS[idx + 1];
  if (next && t > next.at - XF) {
    const p = (t - (next.at - XF)) / XF;
    const e = p * p * (3 - 2 * p);          // smoothstep
    w[idx] = 1 - e;
    w[idx + 1] = e;
  }
  return w;
}

const L = new Float64Array(N);
const R = new Float64Array(N);

// ---------- pad ----------
// Three detuned partials per note. The detune is what stops additive sines
// sounding like a test tone: the beating between them is the whole texture.
const DETUNE = [-0.13, 0, 0.15];
console.log('pad…');
for (let i = 0; i < N; i++) {
  const t = i / SR;
  const w = sectionWeights(t);
  let l = 0, r = 0;
  for (let s = 0; s < SECTIONS.length; s++) {
    if (w[s] < 1e-4) continue;
    const sec = SECTIONS[s];
    const g = w[s] * sec.level;
    for (let n = 0; n < sec.chord.length; n++) {
      const f = sec.chord[n];
      // Higher partials sit quieter, which is what makes a stack of sines read
      // as one instrument instead of a chord of whistles.
      const voice = 1 / (1 + n * 0.75);
      for (let d = 0; d < 3; d++) {
        const ph = 2 * Math.PI * (f + DETUNE[d]) * t;
        const a = Math.sin(ph) * voice * 0.34;
        // Spread the detuned copies across the stereo field.
        const pan = 0.5 + DETUNE[d] * 2.2;
        l += a * g * (1 - pan) * 2;
        r += a * g * pan * 2;
      }
    }
  }
  L[i] += l * 0.055;
  R[i] += r * 0.055;
}

// ---------- pulse ----------
// A slow plucked figure that enters with the product and leaves before the
// limitations, so the honest beat is the quietest thing in the film.
const BPM = 68;
const BEAT = 60 / BPM;
const PULSE_IN = 20.0;
const PULSE_OUT = 91.0;

function pluck(startT, freq, gain, decay) {
  const start = Math.floor(startT * SR);
  const len = Math.floor(decay * SR);
  for (let k = 0; k < len; k++) {
    const i = start + k;
    if (i < 0 || i >= N) break;
    const t = k / SR;
    const env = Math.exp(-t / (decay * 0.32)) * (1 - Math.exp(-t * 900));
    const a = (Math.sin(2 * Math.PI * freq * t) * 0.7 +
               Math.sin(4 * Math.PI * freq * t) * 0.18 +
               Math.sin(6 * Math.PI * freq * t) * 0.07) * env * gain;
    const pan = 0.5 + Math.sin(startT * 0.7) * 0.22;
    L[i] += a * (1 - pan);
    R[i] += a * pan;
  }
}

console.log('pulse…');
const ARP = [0, 2, 1, 3, 1, 2];
let step = 0;
for (let t = PULSE_IN; t < PULSE_OUT; t += BEAT) {
  const w = sectionWeights(t);
  let idx = 0;
  for (let i = 0; i < w.length; i++) if (w[i] > w[idx]) idx = i;
  const chord = SECTIONS[idx].chord;
  const note = chord[ARP[step % ARP.length] % chord.length] * 2;
  // Ease the figure in and out so it never simply starts.
  const edge = Math.min(1, (t - PULSE_IN) / 4.5, (PULSE_OUT - t) / 6.0);
  pluck(t, note, 0.052 * Math.max(0, edge), 1.5);
  step++;
}

// ---------- bass ----------
console.log('bass…');
for (let s = 0; s < SECTIONS.length; s++) {
  const sec = SECTIONS[s];
  const end = s + 1 < SECTIONS.length ? SECTIONS[s + 1].at : DUR;
  const root = sec.chord[0] / 2;
  const start = Math.floor(sec.at * SR);
  const stop = Math.min(N, Math.floor(end * SR));
  for (let i = start; i < stop; i++) {
    const t = (i - start) / SR;
    const total = (stop - start) / SR;
    const env = Math.min(1, t / 1.2) * Math.min(1, (total - t) / 1.2);
    const a = Math.sin(2 * Math.PI * root * (i / SR)) * env * sec.level * 0.10;
    L[i] += a; R[i] += a;
  }
}

// ---------- swells ----------
// One rising bloom into each of the three moments the film wants you to feel:
// the name, the two numbers, and the sign-off.
function swell(atT, dur, gain) {
  const start = Math.floor((atT - dur) * SR);
  const len = Math.floor(dur * SR);
  for (let k = 0; k < len; k++) {
    const i = start + k;
    if (i < 0 || i >= N) continue;
    const p = k / len;
    const env = Math.pow(p, 2.4) * (1 - Math.pow(p, 14));
    const f = 220 * (1 + p * 0.5);
    const a = (Math.sin(2 * Math.PI * f * (i / SR)) * 0.5 +
               Math.sin(2 * Math.PI * f * 1.5 * (i / SR)) * 0.3) * env * gain;
    L[i] += a; R[i] += a;
  }
}
console.log('swells…');
swell(20.0, 2.2, 0.045);
swell(30.0, 2.0, 0.040);
swell(99.0, 2.6, 0.055);

// ---------- reverb ----------
// Schroeder: four combs into two all-passes. Cheap, and it is the difference
// between "synthesised in a script" and "recorded in a room".
function reverb(buf, mix) {
  const combs = [1557, 1617, 1491, 1422].map((d) => ({ d, buf: new Float64Array(d), i: 0, g: 0.80 }));
  const aps = [225, 556].map((d) => ({ d, buf: new Float64Array(d), i: 0, g: 0.5 }));
  const out = new Float64Array(buf.length);
  for (let i = 0; i < buf.length; i++) {
    let acc = 0;
    for (const c of combs) {
      const v = c.buf[c.i];
      acc += v;
      c.buf[c.i] = buf[i] + v * c.g;
      c.i = (c.i + 1) % c.d;
    }
    acc *= 0.25;
    for (const a of aps) {
      const v = a.buf[a.i];
      const y = -a.g * acc + v;
      a.buf[a.i] = acc + a.g * y;
      a.i = (a.i + 1) % a.d;
      acc = y;
    }
    out[i] = buf[i] * (1 - mix) + acc * mix;
  }
  return out;
}
console.log('reverb…');
const LR = reverb(L, 0.30);
const RR = reverb(R, 0.30);

// ---------- master ----------
const FADE_IN = 2.0, FADE_OUT = 6.0;
console.log('master…');
// Normalise on RMS, not on peak. The reverb's comb filters produce occasional
// transients several times louder than anything audible, so dividing by the
// absolute peak set the gain from a spike nobody hears and left the whole score
// at -19 dB — inaudible under a film. RMS sets the level from the body of the
// music, and the tanh limiter below catches the spikes.
let sum = 0;
for (let i = 0; i < N; i++) sum += LR[i] * LR[i] + RR[i] * RR[i];
const rms = Math.sqrt(sum / (N * 2));
const norm = rms > 0 ? 0.16 / rms : 1;      // ~ -16 dBFS RMS, a normal bed level

const bytes = Buffer.alloc(N * 4);
for (let i = 0; i < N; i++) {
  const t = i / SR;
  const fade = Math.min(1, t / FADE_IN, (DUR - t) / FADE_OUT);
  // Soft limiter: tanh rather than a hard clip, so the loud sections compress
  // instead of buzzing.
  const l = Math.tanh(LR[i] * norm * fade * 1.15);
  const r = Math.tanh(RR[i] * norm * fade * 1.15);
  bytes.writeInt16LE(Math.max(-32767, Math.min(32767, Math.round(l * 32767))), i * 4);
  bytes.writeInt16LE(Math.max(-32767, Math.min(32767, Math.round(r * 32767))), i * 4 + 2);
}

const header = Buffer.alloc(44);
header.write('RIFF', 0);
header.writeUInt32LE(36 + bytes.length, 4);
header.write('WAVE', 8);
header.write('fmt ', 12);
header.writeUInt32LE(16, 16);
header.writeUInt16LE(1, 20);            // PCM
header.writeUInt16LE(2, 22);            // stereo
header.writeUInt32LE(SR, 24);
header.writeUInt32LE(SR * 4, 28);       // byte rate
header.writeUInt16LE(4, 32);            // block align
header.writeUInt16LE(16, 34);           // bits
header.write('data', 36);
header.writeUInt32LE(bytes.length, 40);

const out = path.join(HERE, 'score.wav');
writeFileSync(out, Buffer.concat([header, bytes]));
console.log(`wrote ${out}  ${DUR.toFixed(1)}s  ${(bytes.length / 1048576).toFixed(1)} MB`);
