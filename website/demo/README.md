# WorkReceipt demo video: production workflow

Output (committed) is in `website/assets/demo/`: `workreceipt-demo.mp4` (1280x720, H.264/AAC, ~82 s), `-captioned.mp4`, `.en.vtt`, poster (`.webp`/`.jpg`), transcript.

## What is real
- The recording is the genuine WorkReceipt app UI (`workreceipt_app.py`) driven by Playwright with real clicks and typing, on a **synthetic** workspace (`examples/make_demo_workspace.py`). No client data, private logs or credentials.
- The exported HTML and PDF are produced by the app; the PDF is rasterized (pdftoppm) for the viewer scene.
- Capture uses a `window.open` shim so report views stay in the recorded tab. This only affects recording; the shipped app is untouched.
- It is the app's local web UI in a browser, framed in a macOS-style window, not a native macOS window capture.

## Tools and licenses
- Voice: Kokoro-82M via `kokoro-onnx`, Apache-2.0, commercial use allowed. Model files are not committed; download `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the kokoro-onnx releases into `/tmp/tts/`.
- Music: original, synthesized by `make_music.py` (numpy/scipy). No third-party audio.
- Fonts: Bricolage Grotesque, IBM Plex Mono (OFL).
- Compositing: OpenCV/numpy, ffmpeg (libx264, AAC, libass).

## Reproduce
```bash
pip install playwright kokoro-onnx numpy scipy opencv-python soundfile && playwright install chromium
python3 examples/make_demo_workspace.py /Users/demo/projects
# start the app on :8900 against the demo workspace, and a static server for brand cards:
python3 -m http.server -d website 8901 &
cd website/demo
python3 make_narration.py     # narration.json -> audio + timings
python3 make_music.py         # original music bed
python3 record_app.py         # records real app, writes build/markers.json
python3 compose.py assets captions audio render mux publish
```
`build/` is generated and gitignored. Edit `narration.json` to change the script; rerun from `make_narration.py`.
