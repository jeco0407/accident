#!/usr/bin/env python3
"""刪除之後案件又回來？逐步檢查每一個可能讓它復活的環節。

每一步都同時看三個地方：畫面上的列、記憶體裡的索引、localStorage 實際內容。
只看畫面會漏掉「畫面對了但存檔沒寫進去」這種情況。
"""
import asyncio, json, subprocess, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9343
BASE = "http://127.0.0.1:8899/index.html"
SEED_PAGE = "http://127.0.0.1:8899/manifest.json"

SEED = r"""
(function(){
  localStorage.clear();
  var L = [['ca1','甲地址'],['cb2','乙地址'],['cc3','丙地址']];
  localStorage.setItem('aa.cases.v1', JSON.stringify({cur:'ca1', list:
    L.map(function(x,i){ return {id:x[0], ts:Date.now()-i*86400000, closed:0}; })}));
  L.forEach(function(x){
    localStorage.setItem('aa.case.'+x[0], JSON.stringify(
      {'aa.site.v1':{lat:25.03,lon:121.56,at:Date.now(),addr:x[1]},
       'aa.other.v1':{plate:x[1]}}));
  });
  return 'seeded 3';
})()
"""

SNAP = r"""
(function(){
  var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
  return {
    domTitles: [].map.call(document.querySelectorAll('#case-box .case-card .cc-meta'),
                           function(e){ return e.textContent; }),
    idxIds:    idx.list.map(function(c){ return c.id; }),
    cur:       idx.cur,
    packKeys:  Object.keys(localStorage).filter(function(k){
                 return k.indexOf('aa.case.') === 0; }).sort()
  };
})()
"""


async def run():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-del2", "--window-size=430,930", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                pages = [t for t in tabs if t["type"] == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]; break
            except Exception:
                pass
            await asyncio.sleep(0.25)
        if not ws_url:
            print("CHROME_START_FAILED"); return

        import websockets
        async with websockets.connect(ws_url, max_size=40 * 1024 * 1024) as ws:
            n = 0
            errs = []

            async def send(method, params=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == n:
                        return msg
                    if msg.get("method") == "Runtime.exceptionThrown":
                        errs.append(msg["params"]["exceptionDetails"].get("text"))

            async def js(expr, awaitp=True):
                r = await send("Runtime.evaluate",
                               {"expression": expr, "returnByValue": True, "awaitPromise": awaitp})
                ex = r.get("result", {}).get("exceptionDetails")
                if ex:
                    return {"__error": json.dumps(ex, ensure_ascii=False)[:300]}
                return r.get("result", {}).get("result", {}).get("value")

            def url():
                return "%s?t=%d" % (BASE, int(time.time() * 1000))

            async def goto(u, wait=2.6):
                await send("Page.navigate", {"url": u})
                await asyncio.sleep(wait)

            async def snap(label):
                s = await js(SNAP, awaitp=False)
                print("\n--- %s ---" % label)
                print(json.dumps(s, ensure_ascii=False, indent=2))
                return s

            async def delete_by_title(word):
                """真的走一次使用者的路徑：點該列的刪除，再按對話框的『刪除』"""
                r = await js("""
                  (function(){
                    var rows = document.querySelectorAll('#case-box .case-card');
                    for (var i=0;i<rows.length;i++){
                      if (rows[i].querySelector('.cc-meta').textContent.indexOf('%s') >= 0){
                        rows[i].querySelector('[data-del]').click();
                        var ask = document.getElementById('ask');
                        if (!ask.classList.contains('open')) return 'DIALOG DID NOT OPEN';
                        document.getElementById('ask-yes').click();
                        return 'ok';
                      }
                    }
                    return 'ROW NOT FOUND';
                  })()
                """ % word, awaitp=False)
                print("\n刪除「%s」→ %s" % (word, r))
                await asyncio.sleep(1.0)

            await send("Page.enable")
            await send("Runtime.enable")

            await goto(SEED_PAGE, 1.2)
            print("seed:", await js(SEED, awaitp=False))
            await goto(url())

            await snap("初始（目前是甲）")

            # 1. 刪掉不是目前的那一件
            await delete_by_title("乙")
            await snap("刪掉乙之後（立即）")
            await goto(url())
            await snap("刪掉乙之後（重新載入）")

            # 2. 刪掉目前這件
            await delete_by_title("甲")
            await snap("刪掉甲（目前這件）之後（立即）")
            await goto(url())
            await snap("刪掉甲之後（重新載入）")

            # 3. 刪掉最後一件
            await delete_by_title("丙")
            await snap("刪掉最後一件之後（立即）")
            await goto(url())
            await snap("刪掉最後一件之後（重新載入）")

            print("\n=== 未捕捉的例外 ===")
            print(errs or "（無）")
    finally:
        proc.terminate()


asyncio.run(run())
