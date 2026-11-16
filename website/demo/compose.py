#!/usr/bin/env python3
"""Edit the recording into the final video: macOS-style window on the website's backdrop, smooth zooms toward the
logged targets, scene chips, dips at the brand cards, narration + music mix, WebVTT/SRT captions, MP4, poster.
Inputs: build/markers.json, build/frames, build/audio, build/music.wav.  Outputs: build/out/*"""
import bisect, json, math, os, re, subprocess, sys
import cv2, numpy as np, soundfile as sf
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__)); B = os.path.join(HERE, "build"); OUT = os.path.join(B, "out"); os.makedirs(OUT, exist_ok=True)
M = json.load(open(os.path.join(B, "markers.json"))); TM = json.load(open(os.path.join(B, "narration_timing.json")))
FPS, OW, OH, CW, CH = 30, 1280, 720, 1920, 1080
WX, WY, WW, TB = 110, 42, 1700, 40            # window rect on the canvas and title-bar height
AW, AH = WW, int(WW * 810 / 1440)             # app content size inside the window (956)
frames = M["frames"]; ts = [f[0] for f in frames]
marks = M["marks"]; T0 = marks[0]["t"]; TEND = marks[-1]["t"]; DUR = TEND - T0
scenes = [m for m in marks if m["kind"] == "scene"]; sc = {s["name"]: s["t"] - T0 for s in scenes}
INTRO_END = sc["intro"] + 0.5 + TM["intro"][0]["dur"] + 0.9 + 0.05; OUTRO_START = sc["outro"] - 0.3
LABELS = {"overview": "Overview", "projects": "Projects", "studio": "Report Studio", "privacy": "Privacy Center", "export": "Export", "report": "The finished report"}
ORDER = ["overview", "projects", "studio", "privacy", "export", "report"]

# ---------- assets rendered with the website's own fonts/colours
def make_assets():
    def setc(pg, html):   # same-origin page so the website font loads
        open(os.path.join(B, "_tmp.html"), "w").write(html); pg.goto("http://127.0.0.1:8901/demo/build/_tmp.html?%f" % __import__("time").time()); pg.evaluate("document.fonts.ready")
    from playwright.sync_api import sync_playwright
    css = '@font-face{font-family:"Bricolage Grotesque";src:url("http://127.0.0.1:8901/assets/fonts/bricolage-grotesque-latin-wght-normal.woff2");font-weight:200 800}*{box-sizing:border-box;margin:0}'
    bg = css + f'''body{{width:{CW}px;height:{CH}px;background:radial-gradient(70% 90% at 12% 0%,rgba(13,139,127,.26),transparent 62%),radial-gradient(60% 80% at 100% 100%,rgba(176,120,0,.16),transparent 60%),#ece8dd;position:relative}}
    .w{{position:absolute;left:{WX}px;top:{WY}px;width:{WW}px;height:{TB + AH}px;border-radius:16px;background:#fff;box-shadow:0 2px 4px rgba(27,28,26,.10),0 40px 80px -24px rgba(27,28,26,.55)}}'''
    chrome = css + f'''html{{background:transparent}}body{{width:{WW}px;height:{TB + AH}px;background:transparent;position:relative}}
    .bar{{height:{TB}px;background:#f6f3ec;border-bottom:1px solid rgba(27,28,26,.12);display:flex;align-items:center;padding:0 16px;gap:8px;font:500 15px "Bricolage Grotesque";color:#8c8a80;border-radius:16px 16px 0 0}}
    .bar i{{width:13px;height:13px;border-radius:50%;background:#d9d5ca}}.bar span{{margin:0 auto;transform:translateX(-30px)}}'''
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": CW, "height": CH})
        setc(pg, f"<style>{bg}</style><div class=w></div>"); pg.wait_for_timeout(300); pg.screenshot(path=os.path.join(B, "bg.png"))
        pg = b.new_page(viewport={"width": WW, "height": TB + AH})
        setc(pg, f"<style>{chrome}</style><div class=bar><i></i><i></i><i></i><span>WorkReceipt</span></div>"); pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(B, "chrome.png"), omit_background=True)
        pg.set_viewport_size({"width": 700, "height": 60})
        for i, k in enumerate(ORDER):
            setc(pg, f'<style>{css}html{{background:transparent}}body{{background:transparent;padding:6px}}.c{{display:inline-flex;gap:10px;align-items:center;height:34px;padding:0 16px 0 6px;border-radius:99px;background:rgba(27,28,26,.88);color:#fdfbf7;font:550 17px "Bricolage Grotesque"}}.c b{{width:24px;height:24px;border-radius:50%;background:#0d8b7f;display:grid;place-items:center;font-size:14px}}</style><div class=c><b>{i + 1}</b>{LABELS[k]}</div>')
            pg.wait_for_timeout(120); pg.screenshot(path=os.path.join(B, f"chip-{k}.png"), omit_background=True)
        b.close()

def smooth(p): p = min(1, max(0, p)); return p * p * (3 - 2 * p)

def camera_events():
    ev = sorted([(m["t"] - T0, m["s"], m["cx"], m["cy"]) for m in marks if m["kind"] == "zoom"])
    return [(0.0, 1.0, 720.0, 405.0)] + ev
def camera(t, ev, dur=1.0):
    j = bisect.bisect_right([e[0] for e in ev], t) - 1
    if j <= 0: return ev[0][1:]
    p = smooth((t - ev[j][0]) / dur); a, b = ev[j - 1][1:], ev[j][1:]
    r = [x + (y - x) * p for x, y in zip(a, b)]; r[0] = 1 + (r[0] - 1) * 0.75   # soften zooms
    return tuple(r)

def render():
    bg = cv2.imread(os.path.join(B, "bg.png")); ch = cv2.imread(os.path.join(B, "chrome.png"), cv2.IMREAD_UNCHANGED)
    if ch.shape[2] == 3:   # screenshot came back opaque: only the title bar is chrome, the rest is the app
        a_ = np.zeros(ch.shape[:2] + (1,), np.uint8); a_[:TB] = 255; ch = np.concatenate([ch, a_], 2)
    alpha = ch[:, :, 3:4].astype(np.float32) / 255; chrgb = ch[:, :, :3].astype(np.float32)
    mask = np.zeros((TB + AH, WW), np.uint8); cv2.rectangle(mask, (16, 0), (WW - 17, TB + AH), 255, -1); cv2.rectangle(mask, (0, 16), (WW, TB + AH - 17), 255, -1)
    for cx, cy in [(16, 16), (WW - 17, 16), (16, TB + AH - 17), (WW - 17, TB + AH - 17)]: cv2.circle(mask, (cx, cy), 16, 255, -1)
    mk = (mask.astype(np.float32) / 255)[:, :, None]
    chips = {k: cv2.imread(os.path.join(B, f"chip-{k}.png"), cv2.IMREAD_UNCHANGED) for k in ORDER}
    ev = camera_events(); paper = np.array([221, 232, 236], np.float32)   # BGR of #ece8dd
    n = int(DUR * FPS); cache = {"i": -1, "img": None}
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                           "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart", os.path.join(OUT, "silent.mp4")], stdin=subprocess.PIPE)
    shots = {}
    for fi in range(n):
        t = fi / FPS; tabs = T0 + t
        i = max(0, bisect.bisect_right(ts, tabs) - 1)
        if cache["i"] != i: cache["i"] = i; cache["img"] = cv2.imread(os.path.join(B, "frames", frames[i][1]))
        src = cache["img"]; brand = t < INTRO_END or t >= OUTRO_START
        if brand:
            out = cv2.resize(src, (CW, CH), interpolation=cv2.INTER_AREA).astype(np.float32); s = 1.0; cx = cy = 0
        else:
            app = cv2.resize(src, (AW, AH), interpolation=cv2.INTER_AREA).astype(np.float32)
            win = np.empty((TB + AH, WW, 3), np.float32); win[TB:] = app; win[:TB] = 255
            win = win * (1 - alpha) + chrgb * alpha
            can = bg.astype(np.float32); roi = can[WY:WY + TB + AH, WX:WX + WW]; can[WY:WY + TB + AH, WX:WX + WW] = roi * (1 - mk) + win * mk
            out = can
            # chip
            for k in ORDER:
                a, b2 = sc[k], (sc[ORDER[ORDER.index(k) + 1]] if ORDER.index(k) < 5 else OUTRO_START)
                if a - 0.2 <= t < b2:
                    op = min(1, (t - a + 0.2) / 0.4, (b2 - t) / 0.3); c = chips[k]; h, w = c.shape[:2]; y0, x0 = 4, WX - 6
                    al = c[:, :, 3:4].astype(np.float32) / 255 * op; out[y0:y0 + h, x0:x0 + w] = out[y0:y0 + h, x0:x0 + w] * (1 - al) + c[:, :, :3] * al
            s, cx, cy = camera(t, ev)
        # camera (zoom) in canvas space
        if s > 1.001 and not brand:
            ccx = WX + cx * AW / 1440; ccy = WY + TB + cy * AH / 810
            w, h = CW / s, CH / s; x0 = min(max(ccx - w / 2, 0), CW - w); y0 = min(max(ccy - h / 2, 0), CH - h)
            M_ = np.float32([[OW / w, 0, -x0 * OW / w], [0, OH / h, -y0 * OH / h]])
            fr = cv2.warpAffine(out, M_, (OW, OH), flags=cv2.INTER_AREA if s < 1.01 else cv2.INTER_CUBIC)
        else:
            fr = cv2.resize(out, (OW, OH), interpolation=cv2.INTER_AREA)
        # dips to paper at the brand-card boundaries
        d = min(abs(t - INTRO_END), abs(t - OUTRO_START))
        if d < 0.3: k = 0.85 * (1 - d / 0.3); fr = fr * (1 - k) + paper * k
        # fade in / out
        if t < 0.35: fr = fr * (t / 0.35)
        if DUR - t < 0.6: fr = fr * max(0, (DUR - t) / 0.6)
        ff.stdin.write(np.clip(fr, 0, 255).astype(np.uint8).tobytes())
        for name, tt in (("poster", sc["overview"] + 1.7), ("intro", 4.6)):
            if abs(t - tt) < 0.5 / FPS: shots[name] = np.clip(fr, 0, 255).astype(np.uint8)
    ff.stdin.close(); ff.wait()
    for k, v in shots.items(): cv2.imwrite(os.path.join(OUT, f"shot-{k}.png"), v)

def captions():
    cues = []
    for m in [m for m in marks if m["kind"] == "say"]:
        ln = TM[m["scene"]][m["i"]]; st = m["t"] - T0; en = st + ln["dur"] - 0.12
        words = ln["text"].split(); chunks = []; cur = []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) >= 44 or (w[-1] in ".,;" and len(" ".join(cur)) >= 22): chunks.append(cur); cur = []
        if cur: (chunks.append(cur) if len(" ".join(cur)) > 10 or not chunks else chunks[-1].extend(cur))
        wt = [sum(len(w) + 1 for w in c) for c in chunks]; tot = sum(wt); a = st
        for c, w in zip(chunks, wt):
            b = a + (en - st) * w / tot; cues.append((a, b, " ".join(c))); a = b
    def tc(x, sep): h, r = divmod(x, 3600); mi, r = divmod(r, 60); return f"{int(h):02d}:{int(mi):02d}:{int(r):02d}{sep}{int(round((r % 1) * 1000)):03d}"
    vtt = ["WEBVTT", ""] + [f"{i + 1}\n{tc(a, '.')} --> {tc(b, '.')}\n{t}\n" for i, (a, b, t) in enumerate(cues)]
    srt = [f"{i + 1}\n{tc(a, ',')} --> {tc(b, ',')}\n{t}\n" for i, (a, b, t) in enumerate(cues)]
    open(os.path.join(OUT, "workreceipt-demo.en.vtt"), "w").write("\n".join(vtt)); open(os.path.join(OUT, "captions.srt"), "w").write("\n".join(srt))

def audio():
    SR = 48000; n = int((DUR + 0.2) * SR); voice = np.zeros(n, np.float32)
    for m in [m for m in marks if m["kind"] == "say"]:
        x, sr = sf.read(TM[m["scene"]][m["i"]]["file"], dtype="float32"); x = resample_poly(x, SR, sr).astype(np.float32)
        i = int((m["t"] - T0) * SR); voice[i:i + len(x)] += x[: n - i]
    voice *= 0.89 / max(1e-6, np.abs(voice).max())
    music, msr = sf.read(os.path.join(B, "music.wav"), dtype="float32"); mus = np.zeros((n, 2), np.float32); mus[: min(n, len(music))] = music[:n]
    # duck the music under speech: smoothed envelope of the voice
    e = np.abs(voice); k = int(0.25 * SR); env = np.convolve(e, np.ones(k) / k, "same"); env = np.convolve((env > 0.01).astype(np.float32), np.ones(int(.4 * SR)) / int(.4 * SR), "same")
    gain = 0.16 * (1 - 0.45 * np.clip(env, 0, 1))      # ~ -16 dB bed, ~ -21 dB under speech
    mix = mus * gain[:, None] + voice[:, None] * 0.9
    sf.write(os.path.join(OUT, "mix.wav"), np.clip(mix, -1, 1), SR)

def mux():
    run = lambda a: subprocess.run(a, check=True)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(OUT, "silent.mp4"), "-i", os.path.join(OUT, "mix.wav"),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=9,afade=t=out:st=%.2f:d=0.6" % (DUR - 0.6), "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-shortest", "-movflags", "+faststart", os.path.join(OUT, "workreceipt-demo.mp4")])
    st = "FontName=Bricolage Grotesque,FontSize=11,PrimaryColour=&H00F7FBFD,OutlineColour=&H00201C1B,BorderStyle=3,Outline=1,Shadow=0,MarginV=14,Alignment=2,BackColour=&HB0201C1B"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(OUT, "workreceipt-demo.mp4"), "-vf", f"subtitles={OUT}/captions.srt:fontsdir={B}:force_style='{st}'",
         "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", os.path.join(OUT, "workreceipt-demo-captioned.mp4")])

def publish():
    import shutil; A = os.path.join(HERE, "..", "assets", "demo"); os.makedirs(A, exist_ok=True)
    for f in ["workreceipt-demo.mp4", "workreceipt-demo-captioned.mp4", "workreceipt-demo.en.vtt"]: shutil.copy(os.path.join(OUT, f), A)
    im = cv2.imread(os.path.join(OUT, "shot-poster.png"))
    cv2.imwrite(os.path.join(A, "workreceipt-demo-poster.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 84]); cv2.imwrite(os.path.join(A, "workreceipt-demo-poster.webp"), im, [cv2.IMWRITE_WEBP_QUALITY, 82])

if __name__ == "__main__":
    steps = sys.argv[1:] or ["assets", "captions", "audio", "render", "mux"]
    for s in steps: print("::", s, flush=True); {"assets": make_assets, "captions": captions, "audio": audio, "render": render, "mux": mux, "publish": publish}[s]()
    print("duration", round(DUR, 1))
