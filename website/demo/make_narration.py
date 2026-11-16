#!/usr/bin/env python3
"""Synthesize narration with Kokoro-82M (Apache-2.0, commercial use permitted) via kokoro-onnx.
Model files (not committed): https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0
Writes build/audio/<scene>-<n>.wav and build/narration_timing.json (sentence durations)."""
import json, os, sys, numpy as np, soundfile as sf
from kokoro_onnx import Kokoro
here = os.path.dirname(os.path.abspath(__file__)); out = os.path.join(here, "build", "audio"); os.makedirs(out, exist_ok=True)
mdir = os.environ.get("KOKORO_DIR", "/tmp/tts")
k = Kokoro(os.path.join(mdir, "kokoro.onnx"), os.path.join(mdir, "voices.bin"))
cfg = json.load(open(os.path.join(here, "narration.json")))
timing = {}
for sc in cfg["scenes"]:
    timing[sc["id"]] = []
    for i, line in enumerate(sc["lines"]):
        s, sr = k.create(line, voice=cfg["voice"], speed=cfg["speed"], lang="en-us")
        s = np.concatenate([s, np.zeros(int(0.12 * sr), dtype=s.dtype)])   # tiny tail so word endings are not clipped
        p = os.path.join(out, f"{sc['id']}-{i}.wav"); sf.write(p, s, sr)
        timing[sc["id"]].append({"text": line, "file": p, "dur": len(s) / sr})
        print(sc["id"], i, round(len(s) / sr, 2))
json.dump(timing, open(os.path.join(here, "build", "narration_timing.json"), "w"), indent=1)
