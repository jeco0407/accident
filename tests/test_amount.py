#!/usr/bin/env python3
"""求償金額的輸入與加總（v81）

金額錯一位數，整份請求明細就失去可信度，所以這裡逐項驗：
  1. 小計＝各欄位相加，匯出的明細與複製的文字也是同一個數字
  2. 收據上的寫法（1,500.50、全形數字、前面補 0）不會變成別的數字
     特別是小數：舊版把 1500.50 濾成 150050，剛好十倍，畫面上看起來還很正常
  3. 被調整時（捨去小數、截到 9 位數）會告訴使用者
  4. 舊版已經存壞的值，讀出來也會被清乾淨

用法：先在專案根目錄開 `python3 -m http.server 8899`，再跑這支。
"""
import asyncio, json, subprocess, sys, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9378
URL = "http://localhost:8899/index.html"
fails = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("　" + str(detail)) if detail else ""))
    if not ok:
        fails.append(name)


async def main():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-test-amount", "about:blank"],
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

            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(2)
            await ev("localStorage.clear(); 1")
            await send("Page.navigate", {"url": URL + "?amt=1#comp"})
            await asyncio.sleep(2.5)

            async def typeamt(k, txt):
                await ev("""(function(){ var i = document.getElementById('comp-%s'); i.focus(); i.value = %s;
                  i.dispatchEvent(new Event('input', {bubbles:true})); })()""" % (k, json.dumps(txt)))
                await asyncio.sleep(.25)

            async def fresh():
                await ev("localStorage.clear(); 1")
                await send("Page.navigate", {"url": URL + "?amt=" + str(n) + "#comp"})
                await asyncio.sleep(1.6)

            print("=== 小計就是各欄相加 ===")
            for k, v in [("med", "12800"), ("trans", "1500"), ("car", "45600")]:
                await typeamt(k, v)
            st = await ev("""({ total: document.getElementById('comp-total').textContent,
                               n: document.getElementById('comp-count').textContent })""")
            check("12,800 + 1,500 + 45,600 = $59,900", st["total"] == "$59,900", st["total"])
            check("項數是 3", "3" in st["n"], st["n"])

            print("=== 匯出的明細跟小計一致 ===")
            await ev("document.getElementById('cdoc-open').click(); 1")
            await asyncio.sleep(.6)
            doc = await ev("document.getElementById('cdoc-body').innerText")
            check("明細上的合計也是 $59,900", "$59,900" in doc)
            check("明細列出三個項目的金額", all(x in doc for x in ["$12,800", "$1,500", "$45,600"]))
            await ev("""window.__clip=''; navigator.clipboard.writeText = function(t){ window.__clip = t; return Promise.resolve(); };
                        document.getElementById('cdoc-copy').click(); 1""")
            await asyncio.sleep(.4)
            clip = await ev("window.__clip")
            check("複製出來的文字也是 $59,900", "$59,900" in clip)
            await ev("document.getElementById('cdoc-close').click(); 1")

            print("=== 收據上的各種寫法 ===")
            for txt, want, tip in [("12800", "12800", False),
                                   ("12,800", "12800", False),
                                   ("012800", "12800", False),
                                   ("１２８００", "12800", False),
                                   (" 12 800 ", "12800", False),
                                   ("1500.50", "1500", True),
                                   ("1500.99", "1500", True),
                                   ("-500", "500", False),
                                   ("99999999999", "999999999", True)]:
                await fresh()
                await typeamt("med", txt)
                got = await ev("document.getElementById('comp-med').value")
                shown = await ev("""document.getElementById('toast').classList.contains('show')
                                    ? document.getElementById('toast').textContent : ''""")
                check("輸入 %s → %s" % (txt, want), got == want, got)
                if tip:
                    check("輸入 %s 會提示使用者" % txt, bool(shown), shown)

            print("=== 舊版存壞的值 ===")
            await fresh()
            await ev("""(function(){
              var c = JSON.parse(localStorage.getItem('aa.cases.v1')), k = 'aa.case.' + c.cur;
              var d = JSON.parse(localStorage.getItem(k) || '{}');
              /* 舊版濾掉小數點後存進去的十倍數字沒辦法還原，但前導零與超長值要清掉 */
              d['aa.comp.v1'] = { med:'0012800', car:'99999999999' };
              localStorage.setItem(k, JSON.stringify(d)); })()""")
            await send("Page.navigate", {"url": URL + "?amt=old#comp"})
            await asyncio.sleep(2)
            st = await ev("""({ med: document.getElementById('comp-med').value,
                               car: document.getElementById('comp-car').value,
                               total: document.getElementById('comp-total').textContent })""")
            check("前面的 0 清掉", st["med"] == "12800", st["med"])
            check("超長的值截到 9 位數", st["car"] == "999999999", st["car"])
            check("小計跟著欄位走", st["total"] == "$1,000,012,799", st["total"])
    finally:
        proc.terminate()

    print()
    print("全部通過" if not fails else "未通過：" + "、".join(fails))
    sys.exit(1 if fails else 0)


asyncio.run(main())
