#!/usr/bin/env python3
"""只拍照也算一件事故＋匯出案件紀錄

驗證重點：
  1. 沒取得位置、只在「存證」拍了照 → 設定頁會出現這件事故（v78 以前被當成空的）
  2. 事故卡上是「匯出案件紀錄」，不是「分享照片」
  3. 匯出的紀錄有照片、對方資料、各清單的勾選狀態
  4. 使用者輸入有跳脫
  5. 列印時 body 底下只剩這張紀錄；複製的文字有重點

用法：先在專案根目錄開 `python3 -m http.server 8899`，再跑這支。
"""
import asyncio, json, subprocess, sys, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9364
URL = "http://localhost:8899/index.html"
fails = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("　" + str(detail)) if detail else ""))
    if not ok:
        fails.append(name)


import os
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture-avatar.jpg")
# App 的程式包在閉包裡，測試碰不到內部函式 —— 一律像使用者一樣點畫面


async def main():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-test-export", "about:blank"],
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

            # 全新狀態：清掉 localStorage 與照片資料庫
            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(2)
            await ev("localStorage.clear(); indexedDB.deleteDatabase('aa-photos'); 1")
            await send("Page.navigate", {"url": URL + "?fresh=1#photo"})
            await asyncio.sleep(2.5)

            print("=== 只拍照、沒取得位置 ===")
            await tab("me")
            check("一開始設定頁是空白狀態",
                  await ev("!!document.querySelector('#case-box .case-empty')") is True)
            await tab("photo")
            await add_photo(1)
            check("照片存進去了（碰撞點特寫打勾）",
                  await ev("document.querySelectorAll('.ph')[1].classList.contains('done')") is True)
            await tab("me")
            await asyncio.sleep(.8)
            st = await ev("""({ cards: document.querySelectorAll('#case-box .case-card').length,
                               empty: !!document.querySelector('#case-box .case-empty'),
                               meta: (document.querySelector('#case-box .case-card.is-cur .cc-meta')||{}).textContent })""")
            check("只拍了照片，也會出現這件事故", st["cards"] == 1 and not st["empty"], st)
            check("事故卡上寫著照片張數", "照片 1 張" in (st["meta"] or ""), st["meta"])

            # 寫入對方資料與現場勾選，再重新整理：也順便驗證重新整理後這件還在
            await ev("""(function(){
              var c = JSON.parse(localStorage.getItem('aa.cases.v1')), k = 'aa.case.' + c.cur;
              var d = JSON.parse(localStorage.getItem(k) || '{}');
              d['aa.other.v1'] = { plate:'ABC-1234', name:'<img src=x onerror=alert(1)>', tel:'0912345678', insurer:'富邦產險' };
              d['aa.timeline.v1'] = { hazard:true };
              localStorage.setItem(k, JSON.stringify(d));
            })(); 1""")
            await send("Page.navigate", {"url": URL + "?reload=1#me"})
            await asyncio.sleep(3)
            check("重新整理後這件事故還在",
                  await ev("document.querySelectorAll('#case-box .case-card').length") == 1)

            print("\n=== 匯出案件紀錄 ===")
            btns = await ev("[].map.call(document.querySelectorAll('#case-box .case-card.is-cur .cc-acts button'), function(b){ return b.textContent.trim(); })")
            check("事故卡上是「匯出案件紀錄」", "匯出案件紀錄" in btns and "分享照片" not in btns, btns)

            await ev("document.querySelector('#case-box [data-act=export]').click(); 1")
            await asyncio.sleep(.8)
            check("紀錄打得開", await ev("document.getElementById('crec-sheet').classList.contains('open')") is True)
            txt = await ev("document.getElementById('crec-body').innerText")
            html = await ev("document.getElementById('crec-body').innerHTML")
            check("有照片縮圖", await ev("document.querySelectorAll('#crec-body .crec-ph img').length") == 1)
            check("照片載得出來", await ev("""new Promise(function(r){ var i = document.querySelector('#crec-body .crec-ph img');
                   if (i.complete) r(i.naturalWidth > 0); else { i.onload = function(){ r(true); }; i.onerror = function(){ r(false); }; } })""", awaitp=True) is True)
            check("照片張數正確", "共 1 張" in txt)
            check("對方車牌有帶進來", "ABC-1234" in txt)
            check("對方姓名有跳脫", "<img src=x" not in html and "&lt;img src=x" in html)
            check("現場處理有勾選狀態", "開雙黃燈" in txt and "✓" in txt)
            check("沒有位置時寫「未記錄」", "未記錄" in txt)
            check("分享鍵顯示張數", await ev("document.getElementById('crec-share-t').textContent") == "分享照片（1 張）")
            check("有列印與複製鍵", await ev("!!document.getElementById('crec-print') && !!document.getElementById('crec-copy')") is True)

            print("\n=== 列印 ===")
            await send("Emulation.setEmulatedMedia", {"media": "print"})
            await asyncio.sleep(.4)
            vis = await ev("Array.prototype.filter.call(document.body.children,"
                           "function(e){return getComputedStyle(e).display!=='none'})"
                           ".map(function(e){return e.id||e.className}).join(',')")
            check("列印時 body 底下只剩這張紀錄", vis == "crec-sheet", vis)
            await send("Emulation.setEmulatedMedia", {"media": "screen"})

            await ev("document.getElementById('crec-close').click(); 1")
            check("關得掉", await ev("document.getElementById('crec-sheet').classList.contains('open')") is False)
    finally:
        proc.terminate()

    print("\n" + ("全部通過（0 項未通過）" if not fails
                  else "未通過 %d 項：%s" % (len(fails), "、".join(fails))))
    sys.exit(1 if fails else 0)


asyncio.run(main())
