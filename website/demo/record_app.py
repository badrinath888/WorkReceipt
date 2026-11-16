#!/usr/bin/env python3
"""Record the REAL WorkReceipt app (workreceipt_app.py, local web UI) driving a synthetic workspace.
Playwright drives genuine mouse/keyboard events; an injected overlay draws the cursor and click ripples.
Frames come from Chrome's screencast (build/frames) with wall-clock timestamps; build/markers.json logs
scene starts, narration starts and zoom targets for compose.py. Nothing here fakes UI: every screen is the app.

Prereq: /tmp/startapp.sh equivalent (see build.sh): app on :8900, static server for website/ on :8901."""
import asyncio, base64, glob, json, math, os, shutil, subprocess, sys, time
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__)); BUILD = os.path.join(HERE, "build"); FR = os.path.join(BUILD, "frames")
APP = "http://127.0.0.1:8900/"; STATIC = "http://127.0.0.1:8901/demo/"
T = json.load(open(os.path.join(BUILD, "narration_timing.json")))
W, H, DSF = 1440, 810, 1.5

INIT = r"""
(()=>{
 const CSS='@keyframes __rp{from{transform:scale(.35);opacity:1}to{transform:scale(1.8);opacity:0}}@keyframes __rg{0%{opacity:0}20%{opacity:1}80%{opacity:1}100%{opacity:0}}';
 function mk(){ if(!document.body) return requestAnimationFrame(mk);
  const css=document.createElement('style'); css.textContent=CSS; document.head.appendChild(css);
  const c=document.createElement('div'); c.id='__cur';
  c.style.cssText='position:fixed;left:0;top:0;width:30px;height:30px;z-index:2147483647;pointer-events:none;transform:translate(-200px,-200px);filter:drop-shadow(0 3px 4px rgba(0,0,0,.35))';
  c.innerHTML='<svg width="30" height="30" viewBox="0 0 30 30" style="transition:transform .08s"><path d="M5 3 L5 24 L10.5 19 L14.2 27 L18 25.3 L14.4 17.6 L22 17.2 Z" fill="#fff" stroke="#151615" stroke-width="1.7" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  addEventListener('mousemove',e=>{c.style.transform='translate('+(e.clientX-5)+'px,'+(e.clientY-3)+'px)'},true);
  addEventListener('mousedown',e=>{c.firstChild.style.transform='scale(.86)';
    const r=document.createElement('div');r.style.cssText='position:fixed;left:'+(e.clientX-20)+'px;top:'+(e.clientY-20)+'px;width:40px;height:40px;border-radius:50%;border:3px solid #0d8b7f;background:rgba(13,139,127,.2);pointer-events:none;z-index:2147483646;animation:__rp .6s ease-out forwards';
    document.body.appendChild(r);setTimeout(()=>r.remove(),700)},true);
  addEventListener('mouseup',()=>{c.firstChild.style.transform=''},true);
 } mk();
 window.__ring=(el,ms)=>{ if(!el) return; const b=el.getBoundingClientRect(); const d=document.createElement('div');
  d.style.cssText='position:fixed;left:'+(b.left-8)+'px;top:'+(b.top-8)+'px;width:'+(b.width+16)+'px;height:'+(b.height+16)+'px;border:2.5px solid #0d8b7f;border-radius:14px;background:rgba(13,139,127,.07);box-shadow:0 0 0 6px rgba(13,139,127,.12);pointer-events:none;z-index:2147483645;animation:__rg '+ms+'ms ease forwards';
  document.body.appendChild(d); setTimeout(()=>d.remove(),ms+60)};
})();
"""

marks = []
def log(kind, **kw): marks.append(dict(kind=kind, **kw))
def ease(p): return p * p * (3 - 2 * p)

async def main():
    shutil.rmtree(FR, ignore_errors=True); os.makedirs(FR)
    async with async_playwright() as pw:
        br = await pw.chromium.launch()
        # ---- prep (not recorded): finish onboarding, export one earlier report so Overview has history
        pc = await br.new_context(viewport={"width": W, "height": H}); pp = await pc.new_page()
        await pp.goto(APP); await pp.wait_for_timeout(700)
        for sel in ["#obnext", "#obnext", "#obskip"]:
            if await pp.locator(sel).count(): await pp.click(sel); await pp.wait_for_timeout(250)
        await pp.click("#tabs >> text=Projects"); await pp.wait_for_timeout(400)
        await pp.click("text=northwind-api >> nth=0"); await pp.fill("#client", "Northwind Labs"); await pp.click("#load"); await pp.wait_for_timeout(2200)
        await pp.click("#tabs >> text=Report Studio"); await pp.wait_for_timeout(500)
        await pp.click("#export"); await pp.wait_for_selector("text=Exported:", timeout=30000)
        await pc.close()

        # ---- recorded session
        ctx = await br.new_context(viewport={"width": W, "height": H}, device_scale_factor=DSF)
        await ctx.add_init_script(INIT)
        page = await ctx.new_page()
        cdp = await ctx.new_cdp_session(page)
        n = [0]; stamps = []
        def on_frame(p):
            fn = os.path.join(FR, f"{n[0]:05d}.jpg")
            with open(fn, "wb") as f: f.write(base64.b64decode(p["data"]))
            stamps.append((p["metadata"]["timestamp"], os.path.basename(fn))); n[0] += 1
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))
        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": int(W * DSF), "maxHeight": int(H * DSF), "everyNthFrame": 1})

        cur = [980.0, 520.0]
        async def mv(x, y): cur[0], cur[1] = x, y; await page.mouse.move(x, y)
        async def glide(x, y, dur=0.9):
            x0, y0 = cur; dist = math.hypot(x - x0, y - y0); k = 0.07 * dist
            nx, ny = (-(y - y0) / dist, (x - x0) / dist) if dist else (0, 0)
            t0 = time.time()
            while True:
                p = (time.time() - t0) / dur
                if p >= 1: break
                e = ease(p); a = math.sin(math.pi * e) * k
                await mv(x0 + (x - x0) * e + nx * a, y0 + (y - y0) * e + ny * a); await asyncio.sleep(0.011)
            await mv(x, y)
        async def center(sel, dx=.5, dy=.5, nth=0):
            loc = page.locator(sel).nth(nth); await loc.scroll_into_view_if_needed(); b = await loc.bounding_box()
            return b["x"] + b["width"] * dx, b["y"] + b["height"] * dy
        async def go(sel, dur=0.9, dx=.5, dy=.5, nth=0):
            x, y = await center(sel, dx, dy, nth); await glide(x, y, dur)
        async def click(sel, dur=0.9, dx=.5, dy=.5, nth=0):
            await go(sel, dur, dx, dy, nth); await asyncio.sleep(0.12)
            await page.mouse.down(); await asyncio.sleep(0.09); await page.mouse.up(); await asyncio.sleep(0.18)
        async def ring(sel, ms=1800, nth=0):
            await ring_loc(page.locator(sel).nth(nth), ms)
        async def ring_loc(loc, ms=1800):
            h = await loc.element_handle(); await page.evaluate("([e,ms])=>window.__ring(e,ms)", [h, ms])
        async def zoom(s, sel=None, nth=0, dx=.5, dy=.5):
            if sel is None: log("zoom", t=time.time(), s=1.0, cx=W / 2, cy=H / 2); return
            x, y = await center(sel, dx, dy, nth); log("zoom", t=time.time(), s=s, cx=x, cy=y)
        async def zoom_loc(s, loc):
            b = await loc.bounding_box(); log("zoom", t=time.time(), s=s, cx=b["x"] + b["width"] / 2, cy=b["y"] + b["height"] / 2)

        class Scene:
            def __init__(s, name):
                s.name = name; s.t0 = time.time(); s.starts = []; t = 0.5
                for l in T[name]: s.starts.append(t); t += l["dur"] + 0.35
                s.narr_end = t - 0.35; log("scene", name=name, t=s.t0)
                for i, st in enumerate(s.starts): log("say", scene=name, i=i, t=s.t0 + st)
            async def at(s, t):
                d = s.t0 + t - time.time()
                if d > 0: await asyncio.sleep(d)
            async def end(s, extra=0.9): await s.at(s.narr_end + extra)

        # ================= intro (brand card)
        await page.goto(STATIC + "brand/intro.html"); await page.wait_for_timeout(300)
        s = Scene("intro"); await s.end(0.9)

        # ================= overview
        await page.goto(APP); await page.wait_for_selector("#tabs"); await page.wait_for_timeout(500)
        await mv(980, 520)
        s = Scene("overview")
        await s.at(0.6); await go(".stat >> nth=1", 1.0); await ring(".stat", 2200, 1)
        await s.at(2.6); await zoom(1.18, ".card:has-text('Session activity')", 0, .5, .45); await go(".card:has-text('Session activity')", 1.1, .55, .55)
        await s.at(5.0); await zoom(1.0); await go(".card:has-text('Recent reports')", 1.0, .5, .6)
        await s.end(1.0)

        # ================= projects
        s = Scene("projects")
        await s.at(0.3); await click("#tabs >> text=Projects", 0.9)
        await s.at(1.55); await click("text=acme-storefront >> nth=0", 0.8)
        await s.at(s.starts[1] + 0.2); await click("#client", 0.8); await page.keyboard.type("Acme Demo Co", delay=75)
        await asyncio.sleep(0.3); await click("#load", 0.7)
        await page.wait_for_selector("text=Loaded:", timeout=20000)
        res = page.locator("text=Loaded:").locator("xpath=..")
        await zoom_loc(1.22, res); await ring_loc(res, 2400)
        await s.end(1.2); await zoom(1.0)

        # ================= studio
        s = Scene("studio")
        await s.at(0.2); await click("#tabs >> text=Report Studio", 0.8)
        await s.at(1.2); await zoom(1.12, ".card:has-text('Work requested')", 0, 1.0, .35)
        await go(".req >> nth=0", 0.9, .6, .5); await ring(".card:has-text('Work requested')", 2200)
        await s.at(3.2); await go(".card:has-text('Git evidence')", 1.0, .5, .3); await ring(".card:has-text('Git evidence')", 1800)
        await s.at(s.starts[1] - 0.1); await zoom(1.2, ".req .tx", 1, .5, .5)
        await click(".req .tx >> nth=1", 0.9, .5, .5)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("Fixed a rounding error that made some cart totals one cent off, and added tests so it stays fixed.", delay=34)
        await asyncio.sleep(0.4); await page.mouse.click(1200, 120); await zoom(1.0)  # click empty area to blur
        await s.end(1.0)

        # ================= privacy
        s = Scene("privacy")
        await s.at(0.2); await click("#tabs >> text=Privacy Center", 0.8)
        await s.at(1.2); await zoom(1.15, ".stat", 1, .5, 1.2)
        await go(".stat >> nth=0", 0.9); await ring(".stat", 1800, 0)
        await s.at(2.8); await go(".gh", 0.9, .35, .5); await ring(".gh", 1800)
        await s.at(s.starts[1] - 0.2); await zoom(1.0)
        await click("text=Show 1 detection", 0.9)
        await asyncio.sleep(0.5); await click("[data-review]", 0.8)
        await asyncio.sleep(0.5); await zoom(1.2, ".dlgbox")
        await click("input[name=disp] >> nth=1", 0.8, .1, .5)  # "Not a credential (test or dummy value)": the key is a synthetic example
        await click("#ack", 0.7, .05, .5)
        await click("#confirmrev", 0.7)
        await asyncio.sleep(0.8); await zoom(1.0); await ring(".stat", 2000, 3)
        await s.end(1.0)

        # ================= export
        s = Scene("export")
        await s.at(0.2); await click("#tabs >> text=Report Studio", 0.8)
        await s.at(1.6); await click("#export", 0.9)
        await page.wait_for_selector("text=Exported: HTML and PDF", timeout=40000)
        res = page.locator("text=Exported: HTML and PDF").locator("xpath=../..")
        await zoom_loc(1.22, res); await ring_loc(res, 2600)
        names = await page.evaluate("[...document.querySelectorAll('[data-open]')].map(e=>e.dataset.open)")
        pdfname = next(n for n in names if n.endswith(".pdf")); pdfpath = os.path.join(os.path.expanduser("~"), "WorkReceipt Reports", pdfname)
        await s.end(1.0); await zoom(1.0)

        # real exported PDF -> PNG pages for the viewer scene
        pv = os.path.join(BUILD, "pdfview"); shutil.rmtree(pv, ignore_errors=True); os.makedirs(pv)
        subprocess.run(["pdftoppm", "-r", "110", "-png", pdfpath, os.path.join(pv, "p")], check=True)
        for f in glob.glob(os.path.join(pv, "p-*.png")):   # pdftoppm zero-pads when >9 pages; normalise to p-N.png
            b = os.path.basename(f)[2:-4].lstrip("0") or "0"; os.rename(f, os.path.join(pv, f"p-{int(b)}.png"))
        npages = len(glob.glob(os.path.join(pv, "p-*.png")))

        # ================= report (HTML, then PDF)
        s = Scene("report")
        await s.at(0.2); await click("#tabs >> text=Reports", 0.8)
        await s.at(1.4)
        row_open = "tr:has-text('acme-storefront') [data-open][data-kind=html]"
        await page.evaluate("()=>{window.open=function(u){window.location.assign(u);return {}}}")
        await click(row_open, 1.0)
        await page.wait_for_load_state("load"); await asyncio.sleep(0.4); await mv(cur[0], cur[1])
        await s.at(3.0)
        for i in range(34):
            await page.mouse.wheel(0, 24); await asyncio.sleep(0.07)
        await asyncio.sleep(0.6)
        await s.at(s.starts[2] - 0.4)
        await page.go_back(); await page.wait_for_selector("#tabs"); await asyncio.sleep(0.5)
        if not await page.locator("tr:has-text('acme-storefront')").count(): await click("#tabs >> text=Reports", 0.6)
        await mv(cur[0], cur[1])
        await page.evaluate("([base,n,name])=>{window.open=function(u){window.location.assign(base+'pdfview.html?n='+n+'&name='+encodeURIComponent(name));return {}}}", [STATIC, npages, pdfname])
        await click("tr:has-text('acme-storefront') [data-open][data-kind=pdf]", 0.9)
        await page.wait_for_load_state("load"); await asyncio.sleep(0.8); await mv(cur[0], cur[1])
        await zoom(1.12, "body", 0, .5, .5)
        for i in range(36):
            await page.evaluate("y=>window.__pdfScroll(y)", i * 7); await asyncio.sleep(0.06)
        await s.end(1.0); await zoom(1.0)

        # ================= outro
        await page.goto(STATIC + "brand/outro.html"); await page.wait_for_timeout(300)
        s = Scene("outro"); await s.end(1.4)
        log("end", t=time.time())
        await cdp.send("Page.stopScreencast")
        await br.close()
    json.dump({"marks": marks, "frames": stamps, "w": W, "h": H, "dsf": DSF}, open(os.path.join(BUILD, "markers.json"), "w"))
    print("frames", len(stamps), "dur", round(marks[-1]["t"] - marks[0]["t"], 1))

asyncio.run(main())
