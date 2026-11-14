# Browser test (needs: pip install playwright + Chrome). Start the app on the demo workspace first, then run this file.
import json, os, urllib.request
from playwright.sync_api import sync_playwright
R=[]
def ok(n,c,x=""): R.append(bool(c)); print(("PASS " if c else "FAIL ")+n+(" "+str(x) if x and not c else ""))
S="/tmp/shots/s-"
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"]);pg=b.new_page(viewport={"width":1459,"height":812})
    errs=[];pg.on("pageerror",lambda e:errs.append(str(e)));pg.on("console",lambda m:errs.append(m.text) if m.type=="error" else None)
    pg.goto("http://127.0.0.1:8765/");pg.wait_for_timeout(900);pg.screenshot(path=S+"1-top.png")
    ok("no sensitive content before selection",pg.locator("#studio .callout, #studio .req").count()==0 and "AKIA" not in pg.content())
    nav_h=pg.evaluate("document.querySelector('.nav').getBoundingClientRect().bottom")
    # nav clicks: heading visible below nav, active updates
    for k,shot in [("overview","2-overview"),("projects","3-projects"),("studio","4-studio"),("privacy","5-privacy"),("settings","6-settings")]:
        pg.click(f".tab[data-go={k}]");pg.wait_for_timeout(1300)
        top=pg.evaluate(f"document.querySelector('#{k} .ph h2').getBoundingClientRect().top")
        act=pg.evaluate("document.querySelector('.tab[aria-current]')?.dataset.go")
        ok(f"nav->{k}: heading clear of nav (top {top:.0f} > nav {nav_h:.0f})",top>=nav_h,top);ok(f"nav->{k}: active highlight",act==k,act)
        pg.screenshot(path=S+shot+".png")
    # manual scroll spy
    pg.evaluate("scrollTo({top:0,behavior:'instant'})");pg.wait_for_timeout(300)
    ok("top: no active tab",pg.evaluate("!document.querySelector('.tab[aria-current]')"))
    pg.evaluate("document.documentElement.style.scrollBehavior='auto'")
    seen=[]
    for y in range(0,pg.evaluate("document.documentElement.scrollHeight"),500):
        pg.evaluate(f"scrollTo(0,{y})");pg.wait_for_timeout(120);a=pg.evaluate("document.querySelector('.tab[aria-current]')?.dataset.go")
        if a and (not seen or seen[-1]!=a): seen.append(a)
    ok("manual scroll visits all sections in order",seen==["overview","projects","studio","privacy","settings"],seen)
    ok("back-to-top visible at bottom",pg.evaluate("document.querySelector('#totop').classList.contains('on')"))
    pg.click("#totop");pg.wait_for_timeout(1500);ok("back-to-top returns to top",pg.evaluate("scrollY")<5)
    pg.screenshot(path=S+"7-footer.png",clip=None)
    # nested scrollers
    ns=pg.evaluate("[...document.querySelectorAll('body *')].filter(e=>{const c=getComputedStyle(e);return /(auto|scroll)/.test(c.overflowY)&&e.scrollHeight>e.clientHeight+2&&!e.classList.contains('tabs')}).map(e=>e.className)")
    ok("no nested vertical scroll areas",not ns,ns)
    # journey
    pg.evaluate("document.documentElement.style.scrollBehavior=''")
    pg.click("#projects tr[data-pick*=acme]");pg.click("button[data-range='all']");pg.click("#load");pg.wait_for_selector("#projects .callout.ok")
    ok("select project + load",'6 work requests' in pg.inner_text("#projects .callout.ok"))
    ok("studio filled in place",pg.locator("#studio [data-req]").count()==6 and pg.locator("#overview").inner_text().count("Needs attention")==1)
    pg.click("#export");pg.wait_for_timeout(1500);ok("export blocked -> scrolls to privacy",pg.evaluate("document.querySelector('.tab[aria-current]')?.dataset.go")=="privacy")
    ok("raw key not in page","AKIAIOSFODNN7EXAMPLE" not in pg.content())
    pg.click("#addterm",no_wait_after=True) if False else None
    pg.fill("#term","storefront");pg.click("#addterm");pg.wait_for_timeout(900)
    pg.click("#approveall");pg.wait_for_timeout(300)
    ok("review state preserved & nav badge cleared",pg.locator(".tab .dot").count()==0)
    pg.locator('#studio [data-req]').nth(5).fill("Polished admin spacing (edited)")
    pg.click("#preview");pg.wait_for_selector(".frame");pg.wait_for_timeout(900)
    h=pg.evaluate("document.querySelector('.frame').getBoundingClientRect().height");ok("preview auto-sized (no inner scroller)",h>600,h)
    pg.click("#approveall",no_wait_after=True) if False else None
    ok("edit survives re-render",pg.locator('#studio [data-req]').nth(5).inner_text().startswith("Polished"))
    pg.locator(".frame").scroll_into_view_if_needed()
    pg.screenshot(path=S+"4b-studio-preview.png")
    pg.click("#export");pg.wait_for_selector("text=Exported.",timeout=60000)
    d=os.path.expanduser("~/WorkReceipt Reports");fs=os.listdir(d)
    ok("HTML+PDF exported",any(f.endswith('.html') for f in fs) and any(f.endswith('.pdf') for f in fs))
    html=open(os.path.join(d,[f for f in fs if f.endswith('.html')][0])).read();ok("export masked + edited",'AKIA' not in html and 'jane@' not in html and 'Polished admin' in html)
    ok("overview shows report",pg.locator("#overview table.tbl").count()==1)
    pg.fill("#s_author","Demo Dev");pg.click("#savesettings");pg.wait_for_timeout(600);ok("settings saved",json.load(open("/tmp/wr-home/settings.json"))["author"]=="Demo Dev")
    ok("project selection survives settings save",pg.locator("#studio [data-req]").count()==6)
    pg.click("#theme");pg.wait_for_timeout(300);ok("dark",pg.evaluate("document.documentElement.dataset.theme")=="dark")
    pg.evaluate("scrollTo(0,0)");pg.wait_for_timeout(400);pg.screenshot(path=S+"8-dark-top.png");pg.click("#theme")
    for w,hh,tag in [(1459,812,"desktop"),(820,1100,"tablet"),(390,844,"mobile")]:
        q=b.new_page(viewport={"width":w,"height":hh});q.goto("http://127.0.0.1:8765/");q.wait_for_timeout(600)
        q.evaluate("document.documentElement.style.scrollBehavior='auto'");
        for y in range(0,q.evaluate("document.documentElement.scrollHeight"),600): q.evaluate(f"scrollTo(0,{y})");q.wait_for_timeout(60)
        ok(f"{tag}: no horizontal overflow",q.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),q.evaluate("document.documentElement.scrollWidth"))
        if tag!="desktop":
            q.evaluate("scrollTo(0,0)");q.wait_for_timeout(300);q.screenshot(path=S+f"9-{tag}-full.png",full_page=True)
        q.close()
    r=b.new_context(viewport={"width":1200,"height":800},reduced_motion="reduce").new_page();r.goto("http://127.0.0.1:8765/");r.wait_for_timeout(600)
    ok("reduced motion: sections visible without reveal animation",r.evaluate("!document.documentElement.classList.contains('reveal')&&getComputedStyle(document.querySelector('#studio')).opacity=='1'"))
    ok("no page errors",not errs,errs)
    b.close()
print(sum(R),"/",len(R))
