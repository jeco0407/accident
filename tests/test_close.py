#!/usr/bin/env python3
"""結案之後畫面上該有什麼、不該有什麼。

v56 之前：按下結案，列表會多出一張跟剛結案那件同一天、同樣標題、
卻什麼都沒有的卡 —— 因為結案會自動開一件新的，而那件新的照常畫成卡片。
看起來像結案沒結成功。連按幾次還會累積一堆空案件。

App 內部隨時握著一個案件是**實作需求**，不該讓使用者看到。

用法：先在專案根目錄開 `python3 -m http.server 8899`，再跑這支。
"""
import asyncio, json, subprocess, sys, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9376
URL = "http://localhost:8899/index.html"

SEED = """
(function(){var id='c1';
localStorage.setItem('aa.cases.v1',JSON.stringify({cur:id,list:[{id:id,ts:Date.now(),closed:0}]}));
localStorage.setItem('aa.case.'+id,JSON.stringify({
 'aa.site.v1':{lat:25.04776,lon:121.51706,at:Date.now(),addr:'臺北市中正區北平西路3號'},
 'aa.other.v1':{plate:'ABC-1234',name:'王小明'}}));})()
"""

STATE = """(function(){
  var c=JSON.parse(localStorage.getItem('aa.cases.v1'));
  return {
    案件數:c.list.length,
    已結案數:c.list.filter(function(x){return !!x.closed}).length,
    卡片數:document.querySelectorAll('#case-box .case-card').length,
    卡片:[].map.call(document.querySelectorAll('#case-box .case-card'),function(e){
      return e.querySelector('.cc-meta').innerText;}),
    有空白狀態:!!document.querySelector('#case-box .case-empty'),
    有開始新案件:!!document.querySelector('#case-box [data-act=new]'),
    有結案鈕:!!document.querySelector('#case-box [data-act=close]')
  };})()"""

fails = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("　" + str(detail)) if detail else ""))
    if not ok:
        fails.append(name)


async def main():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-test-close", "about:blank"],
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

            async def ev(e):
                r = await send("Runtime.evaluate", {"expression": e, "returnByValue": True})
                if r.get("result", {}).get("exceptionDetails"):
                    return "JS_ERR " + json.dumps(
                        r["result"]["exceptionDetails"], ensure_ascii=False)[:200]
                return r.get("result", {}).get("result", {}).get("value")

            async def close_current():
                """結案要走自己畫的確認框，不是瀏覽器的 confirm()"""
                await ev("var b=document.querySelector('[data-act=close]'); b && b.click()")
                await asyncio.sleep(.4)
                await ev("var y=document.getElementById('ask-yes'); y && y.click()")
                await asyncio.sleep(1.1)

            await send("Page.enable")
            await send("Runtime.enable")
            await send("Network.enable")
            await send("Network.setBypassServiceWorker", {"bypass": True})
            await send("Network.setCacheDisabled", {"cacheDisabled": True})
            await send("Emulation.setDeviceMetricsOverride",
                       {"width": 430, "height": 932, "deviceScaleFactor": 2, "mobile": True})

            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(2.0)
            await ev(SEED)
            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(2.4)
            await ev("document.getElementById('install').style.display='none'")
            await ev("document.querySelectorAll('.tab')[4].click()")
            await asyncio.sleep(.8)

            print("=== 結案之前 ===")
            s = await ev(STATE)
            print("  " + json.dumps(s, ensure_ascii=False))
            check("有一張卡", s["卡片數"] == 1)
            check("有結案鈕", s["有結案鈕"] is True)

            print("\n=== 結案之後 ===")
            await close_current()
            s = await ev(STATE)
            print("  " + json.dumps(s, ensure_ascii=False))
            check("底層還是開了一件新的（App 隨時要握著一個案件）", s["案件數"] == 2, s["案件數"])
            check("剛結案那件標記為已結案", s["已結案數"] == 1)
            check("畫面上只剩結案那一張卡，沒有多出空的那張",
                  s["卡片數"] == 1, s["卡片"])
            check("空的目前案件改用空白狀態表示", s["有空白狀態"] is True)
            check("沒有結案鈕可以按（空案件沒東西可結）", s["有結案鈕"] is False)
            check("沒有「開始新案件」（目前這件已經是空的）", s["有開始新案件"] is False)

            print("\n=== 再按三次結案（v56 以前每按一次就多一件空案件）===")
            for _ in range(3):
                await close_current()
            s = await ev(STATE)
            print("  " + json.dumps(s, ensure_ascii=False))
            check("案件數沒有增加", s["案件數"] == 2, s["案件數"])

            print("\n=== 切換到已結案那件 ===")
            await ev("var b=document.querySelector('#case-box [data-go]'); b && b.click()")
            await asyncio.sleep(1.2)
            s = await ev(STATE)
            print("  " + json.dumps(s, ensure_ascii=False))
            check("已結案的案件切過去之後不會消失", s["卡片數"] == 2, s["卡片"])
            check("切走之後那件空的就露出來（它是真的、切得回去）",
                  s["有空白狀態"] is False)
    finally:
        proc.terminate()

    print("\n" + ("全部通過（0 項未通過）" if not fails
                  else "未通過 %d 項：%s" % (len(fails), "、".join(fails))))
    sys.exit(1 if fails else 0)


asyncio.run(main())
