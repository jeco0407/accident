#!/usr/bin/env python3
"""英文版（v80）

驗證重點：
  1. 手機語言是英文 → App 自動用英文，<html lang="en">
  2. 五個分頁（含展開的收合說明）、對方資料表單、事故卡、確認對話框的畫面上
     沒有漏翻的中文。刻意留著中文的（品牌名、台灣的文件名、查判決用的中文關鍵字）列在 ALLOW
  3. 請求明細、事故紀錄、複製出來的文字一律中英並列
  4. 設定頁可以切成中文、再切回英文，選擇會記住

用法：先在專案根目錄開 `python3 -m http.server 8899`，再跑這支。
"""
import asyncio, json, os, re, subprocess, sys, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9371
URL = "http://localhost:8899/index.html"
fails = []

# 英文畫面上刻意保留的中文
ALLOW = ["保險好鄰居", "交通事故當事人登記聯單", "車禍 慰撫金", "中文", "語言"]


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("　" + str(detail)) if detail else ""))
    if not ok:
        fails.append(name)


FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture-avatar.jpg")

# 畫面上看得到的文字裡，還剩哪些中文（扣掉 ALLOW）
CJK_JS = r"""(function(root){
  var out = [], w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (w.nextNode()){
    var n = w.currentNode, el = n.parentElement;
    if (!el || !n.nodeValue.trim()) continue;
    if (el.closest('script,style,option,[hidden]')) continue;
    if (el.checkVisibility && !el.checkVisibility({ visibilityProperty:true, opacityProperty:true })) continue;
    var t = n.nodeValue;
    ALLOW.forEach(function(a){ t = t.split(a).join(''); });
    if (/[\u4e00-\u9fff]/.test(t)) out.push(n.nodeValue.trim().slice(0, 40));
  }
  return out;
})"""

async def main():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-test-i18n", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                pg = [t for t in tabs if t["type"] == "page"]
                if pg:
                    ws_url = pg[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            await asyncio.sleep(.25)
        if not ws_url:
            print("CHROME_START_FAILED")
            sys.exit(1)

        import websockets
        async with websockets.connect(ws_url, max_size=40 * 1024 * 1024) as ws:
            n = 0

            async def send(m, p=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": m, "params": p or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == n:
                        return msg

            async def ev(e, awaitp=False):
                r = await send("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": awaitp})
                if r.get("result", {}).get("exceptionDetails"):
                    return "JS_ERR " + json.dumps(r["result"]["exceptionDetails"], ensure_ascii=False)[:300]
                return r.get("result", {}).get("result", {}).get("value")

            await send("Page.enable")
            await send("Network.enable")
            await send("Network.setBypassServiceWorker", {"bypass": True})
            await send("Network.setCacheDisabled", {"cacheDisabled": True})
            await send("Emulation.setDeviceMetricsOverride",
                       {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True})

            await send("DOM.enable")
            # 模擬英文手機。headless Chrome 在 macOS 上不吃 --lang，只好在每頁的程式跑之前改掉
            await send("Page.addScriptToEvaluateOnNewDocument", {"source":
                "Object.defineProperty(navigator, 'languages', { get: function(){ return ['en-US', 'en']; } });"
                "Object.defineProperty(navigator, 'language', { get: function(){ return 'en-US'; } });"})

            async def tab(v):
                await ev("document.querySelector('.tab[data-v=%s]').click(); 1" % v)
                await asyncio.sleep(.8)

            async def add_photo(slot):
                await ev("document.querySelectorAll('.ph')[%d].querySelector('.shoot').click(); 1" % slot)
                doc = await send("DOM.getDocument")
                q = await send("DOM.querySelector", {"nodeId": doc["result"]["root"]["nodeId"], "selector": "#picker"})
                await send("DOM.setFileInputFiles", {"nodeId": q["result"]["nodeId"], "files": [FIXTURE]})
                # setFileInputFiles 本身就會觸發 change，不要再自己 dispatch 一次（會變成兩張）
                await asyncio.sleep(2.5)

            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(2)
            await ev("localStorage.clear(); indexedDB.deleteDatabase('aa-photos'); 1")
            await send("Page.navigate", {"url": URL + "?fresh=1"})
            await asyncio.sleep(2.5)
            await ev("window.ALLOW = %s; window.cjk = %s; 1" % (json.dumps(ALLOW, ensure_ascii=False), CJK_JS))

            print("=== 英文手機自動用英文 ===")
            st = await ev("""({ lang: document.documentElement.lang,
                               tabs: [].map.call(document.querySelectorAll('.tab span:not(.badge)'), function(s){ return s.textContent; }),
                               title: document.title })""")
            check("<html lang> 是 en", st["lang"] == "en", st["lang"])
            check("分頁名稱是英文", st["tabs"] == ["Scene", "Evidence", "Insurer", "Claims", "Settings"], st["tabs"])
            check("網頁標題是英文", "Accident" in st["title"], st["title"])

            print("=== 各畫面沒有漏翻的中文 ===")
            # 先放一點資料，讓事故卡、對方資料、小計這些「有資料才出現」的畫面也檢查得到
            await ev("""(function(){
              var c = JSON.parse(localStorage.getItem('aa.cases.v1')), k = 'aa.case.' + c.cur;
              var d = JSON.parse(localStorage.getItem(k) || '{}');
              d['aa.site.v1'] = { lat:25.04, lon:121.51, acc:10, at:1758250000000, addr:'Taipei test address' };
              d['aa.other.v1'] = { plate:'ABC-1234', name:'Wang', tel:'0912345678', insurer:'Fubon' };
              d['aa.comp.v1'] = { med:'12000', car:'35000' };
              d['aa.timeline.v1'] = { hazard:true };
              localStorage.setItem(k, JSON.stringify(d)); return 1; })()""")
            await send("Page.navigate", {"url": URL + "?fresh=2"})
            await asyncio.sleep(2.5)
            await ev("window.ALLOW = %s; window.cjk = %s; 1" % (json.dumps(ALLOW, ensure_ascii=False), CJK_JS))
            for v in ["scene", "photo", "claim", "comp", "me"]:
                await tab(v)
                await ev("document.querySelectorAll('details').forEach(function(d){ d.open = true; }); 1")
                await asyncio.sleep(.3)
                left = await ev("cjk(document.getElementById('v-%s')).concat(cjk(document.querySelector('.tabbar')))" % v)
                check("「%s」分頁" % v, left == [], left)
            # 選一家保險公司，撥號鍵出來
            await tab("claim")
            ins = await ev("""(function(){ var s = document.getElementById('ins-sel'); s.value = '0';
                             s.dispatchEvent(new Event('change')); var a = document.getElementById('ins-call');
                             return { opt: s.options[1].textContent, call: a.textContent, hidden: a.hidden }; })()""")
            check("保險公司選單英文在前、中文在後", ins["opt"] == "Fubon Insurance (富邦產險)", ins["opt"])
            check("撥號鍵是英文", "Call hotline" in ins["call"] and not ins["hidden"], ins["call"])
            # 對方資料表單
            await tab("photo")
            await ev("document.getElementById('other-open').click(); 1")
            await asyncio.sleep(.6)
            left = await ev("cjk(document.getElementById('other-sheet'))")
            check("對方資料表單", left == [], left)
            await ev("document.getElementById('other-close').click(); 1")
            # 確認對話框
            await tab("me")
            await ev("document.querySelector('#case-box [data-act=close]').click(); 1")
            await asyncio.sleep(.4)
            left = await ev("cjk(document.getElementById('ask'))")
            check("確認對話框", left == [], left)
            check("確認對話框的按鈕", await ev("document.getElementById('ask-yes').textContent") == "Close case")
            await ev("document.getElementById('ask-no').click(); 1")

            print("=== 匯出文件中英並列 ===")
            await tab("comp")
            await ev("document.getElementById('cdoc-open').click(); 1")
            await asyncio.sleep(.6)
            doc = await ev("document.getElementById('cdoc-body').innerText")
            for zh, en in [("交通事故損害賠償請求明細", "Statement of Damages"), ("醫療費用", "Medical expenses"),
                           ("合計", "Total"), ("請求人簽名", "Claimant signature")]:
                check("請求明細有「%s」和「%s」" % (zh, en), zh in doc and en in doc)
            sheet = await ev("cjk(document.querySelector('#cdoc-sheet .cdoc-print-hide')).concat(cjk(document.querySelector('#cdoc-sheet .sheet-top')))")
            check("請求明細的按鈕與說明是英文", sheet == [], sheet)
            await ev("document.getElementById('cdoc-close').click(); 1")
            await tab("me")
            await ev("document.querySelector('#case-box [data-act=export]').click(); 1")
            await asyncio.sleep(.8)
            doc = await ev("document.getElementById('crec-body').innerText")
            for zh, en in [("交通事故紀錄", "Traffic Accident Record"), ("對方資料", "Other driver"),
                           ("開雙黃燈", "Turn on hazard lights"), ("調解準備文件", "Documents for mediation")]:
                check("事故紀錄有「%s」和「%s」" % (zh, en), zh in doc and en in doc)
            # 複製的文字：攔下 clipboard
            await ev("""window.__clip = ''; navigator.clipboard.writeText = function(t){ window.__clip = t; return Promise.resolve(); }; 1""")
            await ev("document.getElementById('crec-copy').click(); 1")
            await asyncio.sleep(.4)
            clip = await ev("window.__clip")
            check("複製的事故紀錄中英並列", "交通事故紀錄 Traffic Accident Record" in clip and "開雙黃燈、放三角警示架 / Turn on hazard lights" in clip, clip[:120])
            check("複製後的提示是英文", await ev("document.getElementById('toast').textContent") == "Record copied")
            await ev("document.getElementById('crec-close').click(); 1")

            print("=== 切換語言 ===")
            check("英文鍵是選取狀態", await ev("document.querySelector('#seg-lang [data-v=en]').getAttribute('aria-pressed')") == "true")
            check("條款連到英文版", (await ev("document.getElementById('row-terms').getAttribute('href')")) == "terms-en.html")
            await ev("document.querySelector('#seg-lang [data-v=zh]').click(); 1")
            await asyncio.sleep(2.5)
            st = await ev("""({ lang: document.documentElement.lang, tab: document.querySelector('.tab[data-v=scene] span').textContent,
                               saved: localStorage.getItem('aa.lang.v1') })""")
            check("切成中文：整頁變中文，而且記住了", st == {"lang": "zh-Hant-TW", "tab": "現場", "saved": "zh"}, st)
            await ev("document.querySelector('#seg-lang [data-v=en]').click(); 1")
            await asyncio.sleep(2.5)
            check("再切回英文", await ev("document.querySelector('.tab[data-v=scene] span').textContent") == "Scene")

            print("=== 英文版條款頁 ===")
            for pg in ["privacy-en.html", "terms-en.html"]:
                await send("Page.navigate", {"url": "http://localhost:8899/" + pg})
                await asyncio.sleep(1.2)
                await ev("window.ALLOW = %s; window.cjk = %s; 1" % (json.dumps(ALLOW + ["保險好鄰居"], ensure_ascii=False), CJK_JS))
                left = await ev("cjk(document.body)")
                check(pg + " 沒有漏翻", left == [] or left == ["保險好鄰居"] * len(left), left)
    finally:
        proc.terminate()

    print()
    print("全部通過" if not fails else "未通過：" + "、".join(fails))
    sys.exit(1 if fails else 0)


asyncio.run(main())
