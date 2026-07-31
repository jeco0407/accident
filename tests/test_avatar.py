#!/usr/bin/env python3
"""頭貼：上傳 → 裁切 → 存檔。

走真實的 <input type=file>，用 CDP 的 DOM.setFileInputFiles 塞檔案。
不用 DataTransfer 假造 —— 那條路在部分 Chrome 版本上 files 是唯讀的，
而且測到的不是使用者真正走的那段程式碼。

裁切那一段要驗的重點是**夾限**：不論怎麼拖、怎麼縮，圖片都不能
被拖出取景框露出黑邊。那是這種介面唯一會真的出錯的地方。
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
            await asyncio.sleep(1.5)

            print("\n=== 先進裁切屏，不直接存檔 ===")
            r = await js("""
              (function(){
                return { 裁切屏開著: document.getElementById('crop').classList.contains('open'),
                         已經偷存了: localStorage.getItem('aa.avatar.v1'),
                         取景框: (function(){var b=document.getElementById('crop-box').getBoundingClientRect();
                                   return Math.round(b.width)+'x'+Math.round(b.height);})(),
                         滑桿: document.getElementById('crop-zoom').value };
              })()
            """)
            print("  " + json.dumps(r, ensure_ascii=False))
            bad += ok("上傳後先進裁切屏", r.get("裁切屏開著") is True)
            bad += ok("按下完成之前不存檔", r.get("已經偷存了") is None)
            bad += ok("取景框是正方形", r.get("取景框", "x").split("x")[0] == r.get("取景框", "x").split("x")[1])
            # 取景框要真的依畫面大小算出來。v46 開發時這裡量到 200（下限），
            # 原因是還沒 display 就去量 .crop-stage 的高度，量到 0。
            bad += ok("取景框有依畫面放大（> 下限 200）",
                      int(r.get("取景框", "0x0").split("x")[0]) > 200)

            print("\n=== 夾限：拖不出黑邊 ===")
            # 用力往各個方向拖，然後量圖片實際蓋住的範圍有沒有涵蓋整個取景框。
            r = await js("""
              (function(){
                var box=document.getElementById('crop-box');
                var img=document.getElementById('crop-img');
                function drag(dx,dy){
                  var b=box.getBoundingClientRect();
                  var x=b.left+b.width/2, y=b.top+b.height/2;
                  box.dispatchEvent(new PointerEvent('pointerdown',{pointerId:1,clientX:x,clientY:y,bubbles:true}));
                  box.dispatchEvent(new PointerEvent('pointermove',{pointerId:1,clientX:x+dx,clientY:y+dy,bubbles:true}));
                  box.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,clientX:x+dx,clientY:y+dy,bubbles:true}));
                }
                function covers(){
                  var b=box.getBoundingClientRect(), i=img.getBoundingClientRect();
                  return i.left<=b.left+0.6 && i.top<=b.top+0.6 &&
                         i.right>=b.right-0.6 && i.bottom>=b.bottom-0.6;
                }
                var res={};
                [[900,0,'往右'],[-1800,0,'往左'],[0,900,'往下'],[0,-1800,'往上']].forEach(function(d){
                  drag(d[0],d[1]); res[d[2]]=covers();
                });
                // 縮到最小仍要蓋滿
                var z=document.getElementById('crop-zoom');
                z.value=100; z.dispatchEvent(new Event('input',{bubbles:true}));
                res['縮到最小']=covers();
                z.value=300; z.dispatchEvent(new Event('input',{bubbles:true}));
                drag(-2000,-2000);
                res['放到最大再拖']=covers();
                z.value=100; z.dispatchEvent(new Event('input',{bubbles:true}));
                return res;
              })()
            """)
            print("  " + json.dumps(r, ensure_ascii=False))
            for k, v in r.items():
                bad += ok("拖曳後仍蓋滿取景框：" + k, v is True)

            print("\n=== 取消不留痕跡 ===")
            r = await js("""
              (function(){
                document.getElementById('crop-cancel').click();
                return { 關掉了: !document.getElementById('crop').classList.contains('open'),
                         沒有存檔: localStorage.getItem('aa.avatar.v1') };
              })()
            """)
            print("  " + json.dumps(r, ensure_ascii=False))
            bad += ok("取消會關掉裁切屏", r.get("關掉了") is True)
            bad += ok("取消不留下任何頭貼", r.get("沒有存檔") is None)

            print("\n=== 重新上傳並按完成 ===")
            doc = await send("DOM.getDocument")
            root = doc["result"]["root"]["nodeId"]
            q = await send("DOM.querySelector", {"nodeId": root, "selector": "#av-picker"})
            node = q["result"]["nodeId"]
            await send("DOM.setFileInputFiles", {"nodeId": node, "files": [IMG]})
            await js("document.getElementById('av-picker').dispatchEvent(new Event('change',{bubbles:true}))")
            await asyncio.sleep(1.5)
            await js("document.getElementById('crop-ok').click()")
            await asyncio.sleep(1.0)

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

            print("\n=== 頭貼塞滿圓框 ===")
            # v46 之前這裡是壞的：全域的 button 重置沒有歸零 padding，
            # UA 預設的 1px 6px 把圖擠成長方形，底下的圓形底色從兩側露出來。
            r = await js("""
              (function(){
                var b=document.getElementById('prof-av').getBoundingClientRect();
                var i=document.getElementById('prof-img').getBoundingClientRect();
                var cs=getComputedStyle(document.getElementById('prof-av'));
                return { 按鈕: Math.round(b.width)+'x'+Math.round(b.height),
                         圖: Math.round(i.width)+'x'+Math.round(i.height),
                         padding: cs.padding,
                         塞滿: Math.abs(i.width-b.width)<0.6 && Math.abs(i.height-b.height)<0.6 };
              })()
            """)
            print("  " + json.dumps(r, ensure_ascii=False))
            bad += ok("圖片尺寸等於圓框，沒有露出底色", r.get("塞滿") is True)

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
