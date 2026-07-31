#!/usr/bin/env python3
"""頭貼上傳：走真實的 <input type=file>，用 CDP 的 DOM.setFileInputFiles 塞檔案。

不用 DataTransfer 假造 —— 那條路在部分 Chrome 版本上 files 是唯讀的，
而且測到的不是使用者真正走的那段程式碼。
"""
import asyncio, json, os, subprocess, sys, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9361
ORIGIN = "http://127.0.0.1:8899"
IMG = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "fixture-avatar.jpg")


def ok(label, cond):
    print("  %s %s" % ("PASS" if cond else "FAIL", label))
    return 0 if cond else 1


async def run():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-av", "--window-size=430,930", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bad = 0
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
            print("CHROME_START_FAILED"); return 1

        import websockets
        async with websockets.connect(ws_url, max_size=60 * 1024 * 1024) as ws:
            n = 0

            async def send(method, params=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == n:
                        return msg

            async def js(expr, awaitp=False):
                r = await send("Runtime.evaluate",
                               {"expression": expr, "returnByValue": True, "awaitPromise": awaitp})
                ex = r.get("result", {}).get("exceptionDetails")
                if ex:
                    return {"__error": json.dumps(ex, ensure_ascii=False)[:300]}
                return r.get("result", {}).get("result", {}).get("value")

            await send("Page.enable"); await send("Runtime.enable"); await send("DOM.enable")

            await send("Page.navigate", {"url": ORIGIN + "/index.html?t=%d" % int(time.time()*1000)})
            await asyncio.sleep(3)
            await js("localStorage.clear()")
            await send("Page.navigate", {"url": ORIGIN + "/index.html?t=%d" % (int(time.time()*1000)+1)})
            await asyncio.sleep(3)
            await js("document.querySelector('.tab[data-v=me]').click()")
            await asyncio.sleep(0.4)

            print("\n=== 上傳頭貼 ===")
            doc = await send("DOM.getDocument")
            root = doc["result"]["root"]["nodeId"]
            q = await send("DOM.querySelector", {"nodeId": root, "selector": "#av-picker"})
            node = q["result"]["nodeId"]
            await send("DOM.setFileInputFiles", {"nodeId": node, "files": [IMG]})
            # setFileInputFiles 不會觸發 change，自己補一個 —— 使用者真的選檔時是會有的
            await js("document.getElementById('av-picker').dispatchEvent(new Event('change',{bubbles:true}))")
            await asyncio.sleep(2.0)

            r = await js("""
              (function(){
                var img=document.getElementById('prof-img');
                var raw=localStorage.getItem('aa.avatar.v1');
                var o=raw?JSON.parse(raw):null;
                return {
                  圖顯示: !img.hidden && !!img.getAttribute('src'),
                  佔位隱藏: document.getElementById('prof-ini').hidden,
                  是jpeg: !!(o && /^data:image\\/jpeg;base64,/.test(o.src)),
                  存檔KB: o ? Math.round(o.src.length/1024) : 0,
                  寬: img.naturalWidth, 高: img.naturalHeight
                };
              })()
            """)
            print("  " + json.dumps(r, ensure_ascii=False))
            bad += ok("圖有顯示出來", r.get("圖顯示") is True)
            bad += ok("佔位圖示收起", r.get("佔位隱藏") is True)
            bad += ok("存成 JPEG data URL", r.get("是jpeg") is True)
            bad += ok("裁成正方形 256", r.get("寬") == 256 and r.get("高") == 256)
            bad += ok("大小合理（< 60KB）", 0 < r.get("存檔KB", 0) < 60)

            print("\n=== 重新載入後還在 ===")
            await send("Page.navigate", {"url": ORIGIN + "/index.html?t=%d" % (int(time.time()*1000)+2)})
            await asyncio.sleep(3)
            r = await js("""
              (function(){
                document.querySelector('.tab[data-v=me]').click();
                var img=document.getElementById('prof-img');
                return { 圖還在: !img.hidden && !!img.getAttribute('src') };
              })()
            """)
            print("  " + json.dumps(r, ensure_ascii=False))
            bad += ok("重開之後頭貼還在", r.get("圖還在") is True)

            print("\n=== 頭貼不上傳 ===")
            # 頭貼不能出現在任何同步 payload 裡。直接翻同步用的那個組包函式的產物：
            # 拿目前所有 localStorage 裡會被送上去的東西比對。
            r = await js("""
              (function(){
                var av = JSON.parse(localStorage.getItem('aa.avatar.v1')).src;
                var cases = localStorage.getItem('aa.cases.v1') || '';
                var pack = '';
                for (var i=0;i<localStorage.length;i++){
                  var k = localStorage.key(i);
                  if (k.indexOf('aa.case.') === 0) pack += localStorage.getItem(k);
                }
                return { 頭貼在案件包裡: pack.indexOf(av.slice(0,80)) >= 0,
                         頭貼在案件索引裡: cases.indexOf(av.slice(0,80)) >= 0,
                         個人資料在案件包裡: pack.indexOf('aa.me') >= 0 };
              })()
            """)
            print("  " + json.dumps(r, ensure_ascii=False))
            bad += ok("頭貼不在會同步的案件包裡", r.get("頭貼在案件包裡") is False)
            bad += ok("頭貼不在案件索引裡", r.get("頭貼在案件索引裡") is False)

            print("\n=== 移除頭貼 ===")
            r = await js("""
              new Promise(function(res){
                document.getElementById('prof-edit').click();
                setTimeout(function(){
                  var del = document.getElementById('me-av-del');
                  if (!del) return res({err:'沒有移除鍵'});
                  del.click();
                  document.getElementById('ask-yes').click();
                  setTimeout(function(){
                    res({ 本機已清: localStorage.getItem('aa.avatar.v1'),
                          回到佔位: !document.getElementById('prof-ini').hidden });
                  }, 400);
                }, 400);
              })
            """, awaitp=True)
            print("  " + json.dumps(r, ensure_ascii=False))
            bad += ok("localStorage 清掉", r.get("本機已清") is None)
            bad += ok("畫面回到佔位圖示", r.get("回到佔位") is True)
    finally:
        proc.terminate()
    print("\n%s（%d 項未通過）" % ("全部通過" if not bad else "有失敗", bad))
    return bad


sys.exit(1 if asyncio.run(run()) else 0)
