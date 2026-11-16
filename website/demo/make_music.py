#!/usr/bin/env python3
"""Original instrumental bed, synthesized from scratch with numpy (no samples, no third-party music): soft pad,
sparse plucks and a quiet sub on a C-major progression, 76 BPM. Output: build/music.wav (48 kHz stereo)."""
import sys, os, numpy as np, soundfile as sf
from scipy.signal import fftconvolve, butter, sosfilt
SR = 48000; dur = float(sys.argv[1]) if len(sys.argv) > 1 else 84.0
here = os.path.dirname(os.path.abspath(__file__)); rng = np.random.default_rng(7)
n = int(SR * (dur + 3)); L = np.zeros(n); R = np.zeros(n)
def hz(m): return 440 * 2 ** ((m - 69) / 12)
bpm = 76; beat = 60 / bpm; bar = 4 * beat
prog = [  # (bass, chord tones, pluck pool)
  (36, [60, 64, 67, 71, 74], [72, 74, 76, 79, 83]),   # Cmaj9
  (33, [57, 60, 64, 67, 71], [69, 72, 76, 79, 81]),   # Am9
  (41, [60, 65, 69, 72, 76], [72, 76, 77, 81, 84]),   # Fmaj7
  (43, [59, 62, 67, 69, 74], [71, 74, 79, 81, 83]),   # G6/9
]
def add(buf, x, t, gain=1.0):
    i = int(t * SR); j = min(n, i + len(x))
    if i < n: buf[i:j] += x[: j - i] * gain
def env(m, a, r, hold=None):
    e = np.ones(m); a = int(a * SR); r = int(r * SR)
    e[:a] = np.linspace(0, 1, a) ** 2; e[m - r:] *= np.linspace(1, 0, r) ** 2; return e
def pad_note(f, length, pan):
    t = np.arange(int(length * SR)) / SR
    x = sum(np.sin(2 * np.pi * f * (1 + d) * t + p) * a for d, p, a in [(0, 0, 1), (.0035, 1, .6), (-.0035, 2, .6)])
    x += .25 * np.sin(2 * np.pi * 2 * f * t) + .08 * np.sin(2 * np.pi * 3 * f * t)
    return x * env(len(t), 1.6, 1.8) * .05
def pluck(f, length=1.8):
    t = np.arange(int(length * SR)) / SR
    x = np.sin(2 * np.pi * f * t) + .35 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 6) + .12 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 9)
    return x * np.exp(-t * 3.4) * (1 - np.exp(-t * 400)) * .11
def sub(f, length):
    t = np.arange(int(length * SR)) / SR
    return np.sin(2 * np.pi * f * t) * env(len(t), .08, .9) * .16
bars = int((dur + 3) / bar) + 1
for b in range(bars):
    t0 = b * bar; bass, ch, pool = prog[b % 4]
    for k, m in enumerate(ch):
        x = pad_note(hz(m), bar + 2.2, 0); p = .25 + .5 * k / (len(ch) - 1)
        add(L, x, t0, 1 - p); add(R, x, t0, p)
    add(L, sub(hz(bass), bar * .98), t0, 1); add(R, sub(hz(bass), bar * .98), t0, 1)
    if b >= 1:
        for q in range(8):                     # sparse eighth-note plucks
            if rng.random() < (.5 if q % 2 else .72):
                m = pool[int(rng.integers(0, len(pool)))]; x = pluck(hz(m)); p = rng.uniform(.2, .8)
                add(L, x, t0 + q * beat / 2, 1 - p); add(R, x, t0 + q * beat / 2, p)
# soft hi-passed air texture
air = rng.standard_normal(n) * .004; sos = butter(2, 5000, "hp", fs=SR, output="sos"); air = sosfilt(sos, air); L += air; R += air
# reverb: decaying noise impulse response, ~28% wet
ir = rng.standard_normal(int(2.4 * SR)) * np.exp(-np.arange(int(2.4 * SR)) / (0.55 * SR)); ir /= np.abs(ir).sum() / 14
def rv(x): w = fftconvolve(x, ir)[: len(x)]; return .72 * x + .28 * w * 3
L, R = rv(L), rv(R)
m = int(dur * SR); L, R = L[:m], R[:m]
fi = np.minimum(1, np.arange(m) / (2.5 * SR)); fo = np.minimum(1, (m - np.arange(m)) / (3.5 * SR)); g = (fi * fo) ** 1.5
out = np.stack([L * g, R * g], 1); out /= max(1e-9, np.abs(out).max()) / .8
sf.write(os.path.join(here, "build", "music.wav"), out.astype(np.float32), SR); print("music", out.shape, round(float(np.sqrt((out ** 2).mean())), 3))
