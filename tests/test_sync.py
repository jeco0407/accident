#!/usr/bin/env python3
"""M3 同步測試。

不連真的資料庫（那需要一個已完成 email 確認的帳號）。改成用
Page.addScriptToEvaluateOnNewDocument 在 App 腳本之前換掉 window.fetch，
攔下每一個請求來檢查。

要驗的是規則，不是能不能連上：
  1. 沒帳號／離線／功能關閉時，一個請求都不該送出
  2. 送出的內容只有文字，**照片絕不出現在任何請求裡**
  3. Last-Write-Wins 比的是 updated_at，本機比較新時不被覆蓋
  4. 刪除送的是墓碑（deleted_at），不是消失
  5. 同步失敗一律靜默：不 toast、不對話框、App 照常可用
"""
import asyncio, json, subprocess, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9357
ORIGIN = "http://127.0.0.1:8899"

# 在 App 之前執行：換掉 fetch，記錄所有呼叫，回傳可控的假回應
STUB = r"""
(function(){
  window.__calls = [];
  // 假回應存在 localStorage：這個 stub 每次導覽都會重跑，
  // 放在 window 上的話一重新載入就沒了 —— 測試會變成「什麼都沒拉到」而假通過。
  window.__pullRows = (function(){
    try{ return JSON.parse(localStorage.getItem('__pull') || '[]'); }catch(e){ return []; }
  })();
  window.__failAll = false;
  var real = window.fetch;
  window.fetch = function(url, init){
    var u = String(url);
    if (u.indexOf('supabase.co') === -1) return real.apply(this, arguments);
    init = init || {};
    var body = null;
    try{ body = init.body ? JSON.parse(init.body) : null; }catch(e){}
    window.__calls.push({ url:u, method:(init.method||'GET'), body:body });

    if (window.__failAll){
      return Promise.resolve(new Response('{"message":"boom"}',
        { status:500, headers:{'Content-Type':'application/json'} }));
    }
    if (u.indexOf('grant_type=refresh_token') !== -1){
      return Promise.resolve(new Response(JSON.stringify({
        access_token:'fresh', refresh_token:'r2', expires_in:3600,
        user:{ id:'11111111-1111-1111-1111-111111111111', email:'a@b.co' }
      }), { status:200, headers:{'Content-Type':'application/json'} }));
    }
    if (u.indexOf('/rest/v1/incidents') !== -1 && (init.method||'GET') === 'GET'){
      return Promise.resolve(new Response(JSON.stringify(window.__pullRows),
        { status:200, headers:{'Content-Type':'application/json'} }));
    }
    return Promise.resolve(new Response('', { status:201 }));
  };
})();
"""

SEED_ACCOUNT = r"""
(function(){
  localStorage.setItem('aa.authpreview.v1','1');
  localStorage.setItem('aa.registered.v1','1');
  localStorage.setItem('aa.session.v1', JSON.stringify({
    access_token:'tok', refresh_token:'r1',
    expires_at: Date.now() + 3600000,
    user:{ id:'11111111-1111-1111-1111-111111111111', email:'a@b.co' }
  }));
  return 'ok';
})()
"""


async def run():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-sync", "--window-size=430,930", "about:blank"],
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

            async def send(method, params=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == n:
                        return msg

            async def js(expr, awaitp=True):
                r = await send("Runtime.evaluate",
                               {"expression": expr, "returnByValue": True, "awaitPromise": awaitp})
                ex = r.get("result", {}).get("exceptionDetails")
                if ex:
                    return {"__error": json.dumps(ex, ensure_ascii=False)[:300]}
                return r.get("result", {}).get("result", {}).get("value")

            def u():
                return ORIGIN + "/index.html?t=%d" % int(time.time() * 1000)

            async def goto(wait=2.6):
                await send("Page.navigate", {"url": u()})
                await asyncio.sleep(wait)

            await send("Page.enable")
            await send("Runtime.enable")
            await send("Page.addScriptToEvaluateOnNewDocument", {"source": STUB})

            # ---- 1. 沒有帳號時不該送任何東西 ----
            await goto()
            await js("localStorage.clear()")
            await goto(3.0)
            print("\n=== 未註冊 ===")
            print("  請求數:", await js("window.__calls.length", awaitp=False))

            # ---- 2. 有帳號、有案件 → 應該推出去 ----
            await js(SEED_ACCOUNT, awaitp=False)
            await js("""
              (function(){
                var A='k1';
                localStorage.setItem('aa.cases.v1', JSON.stringify({cur:A, list:[
                  {id:A, ts:1750000000000, closed:0, up:1750000100000}
                ]}));
                localStorage.setItem('aa.case.'+A, JSON.stringify({
                  'aa.site.v1':{lat:22.63,lon:120.30,addr:'高雄市三民區市中一路2號'},
                  'aa.other.v1':{plate:'ABC-1234'},
                  'aa.comp.v1':{med:'12000'},
                  'aa.timeline.v1':{0:true,1:true}
                }));
              })()
            """, awaitp=False)
            await goto(3.4)
            calls = await js("window.__calls", awaitp=False)
            posts = [c for c in calls if c["method"] == "POST" and "incidents" in c["url"]]
            print("\n=== 有帳號、一筆案件 ===")
            print("  總請求:", [c["method"] + " " + c["url"].split("supabase.co")[1][:40] for c in calls])
            if posts:
                row = posts[0]["body"][0]
                print("  推出去的欄位:", sorted(row.keys()))
                print("  location:", json.dumps(row.get("location"), ensure_ascii=False))
                print("  photo_count:", row.get("photo_count"))
                print("  updated_at:", row.get("updated_at"), "（本機 up=1750000100000）")
            raw = json.dumps(calls, ensure_ascii=False)
            print("  請求內容含 buf/thumb/base64:",
                  any(k in raw for k in ("\"buf\"", "thumb", "data:image")))

            # ---- 3. LWW：伺服器比較舊 → 不覆蓋 ----
            await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                localStorage.setItem('__pull', JSON.stringify([{
                  id: idx.list[0].rid,
                  occurred_at: new Date(1750000000000).toISOString(),
                  location: { addr:'舊的地址（不該出現）' },
                  other_party: {}, claim: {}, progress: {},
                  photo_count: 0, closed_at: null, deleted_at: null,
                  updated_at: new Date(1750000000000).toISOString()
                }]));
                localStorage.removeItem('aa.sync.v1');
              })()
            """, awaitp=False)
            await goto(3.4)
            print("\n=== 拉到比本機舊的資料 ===")
            print(json.dumps(await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                var pack = JSON.parse(localStorage.getItem('aa.case.'+idx.cur));
                return { 地址: (pack['aa.site.v1']||{}).addr };
              })()
            """, awaitp=False), ensure_ascii=False))

            # ---- 4. LWW：伺服器比較新 → 覆蓋 ----
            await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                localStorage.setItem('__pull', JSON.stringify([{
                  id: idx.list[0].rid,
                  occurred_at: new Date(1750000000000).toISOString(),
                  location: { addr:'新的地址（另一台裝置改的）' },
                  other_party: { plate:'XYZ-9999' }, claim: {}, progress: {},
                  photo_count: 3, closed_at: null, deleted_at: null,
                  updated_at: new Date(Date.now()).toISOString()
                }]));
                localStorage.removeItem('aa.sync.v1');
              })()
            """, awaitp=False)
            await goto(3.4)
            print("\n=== 拉到比本機新的資料 ===")
            print(json.dumps(await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                var pack = JSON.parse(localStorage.getItem('aa.case.'+idx.cur));
                return { 地址: (pack['aa.site.v1']||{}).addr,
                         車牌: (pack['aa.other.v1']||{}).plate };
              })()
            """, awaitp=False), ensure_ascii=False))

            # ---- 5. 拉到刪除 → 本機也要刪 ----
            await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                localStorage.setItem('__pull', JSON.stringify([{
                  id: idx.list[0].rid,
                  occurred_at: new Date(1750000000000).toISOString(),
                  deleted_at: new Date(Date.now()+1000).toISOString(),
                  updated_at: new Date(Date.now()+1000).toISOString()
                }]));
                localStorage.removeItem('aa.sync.v1');
              })()
            """, awaitp=False)
            await goto(3.4)
            print("\n=== 拉到「已刪除」===")
            print(json.dumps(await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                return { 案件數: idx.list.length,
                         空白狀態: !!document.querySelector('.case-empty') };
              })()
            """, awaitp=False), ensure_ascii=False))

            # ---- 6. 本機刪除 → 送出墓碑 ----
            await js("""
              (function(){
                var A='k9';
                localStorage.setItem('aa.cases.v1', JSON.stringify({cur:A, list:[
                  {id:A, ts:1750000000000, closed:0, up:1750000100000,
                   rid:'22222222-2222-2222-2222-222222222222', sy:1750000100000}
                ]}));
                localStorage.setItem('aa.case.'+A, JSON.stringify({'aa.other.v1':{plate:'DEL-1'}}));
                localStorage.setItem('__pull','[]');
                localStorage.removeItem('aa.sync.v1');
              })()
            """, awaitp=False)
            await goto(3.0)
            await js("""
              (function(){
                document.querySelector('.btn-settings').click();
                var d = document.querySelector('#case-box [data-del]');
                if (!d) return 'no delete button';
                d.click();
                document.getElementById('ask-yes').click();
                return 'deleted';
              })()
            """, awaitp=False)
            await asyncio.sleep(4.0)
            calls = await js("window.__calls", awaitp=False)
            tomb = None
            for c in calls:
                if c["method"] == "POST" and isinstance(c.get("body"), list):
                    for r0 in c["body"]:
                        if r0.get("deleted_at"):
                            tomb = r0
            print("\n=== 本機刪除之後送出的墓碑 ===")
            print("  ", json.dumps(tomb, ensure_ascii=False) if tomb else "沒有送出墓碑")

            # ---- 7. 同步整個失敗，必須靜默 ----
            await js("""
              (function(){
                var A='kf';
                localStorage.setItem('aa.cases.v1', JSON.stringify({cur:A, list:[
                  {id:A, ts:1750000000000, closed:0, up:Date.now()}
                ]}));
                localStorage.setItem('aa.case.'+A, JSON.stringify({'aa.other.v1':{plate:'FAIL-1'}}));
              })()
            """, awaitp=False)
            await send("Page.addScriptToEvaluateOnNewDocument",
                       {"source": STUB + "\nwindow.__failAll = true;"})
            await goto(4.0)
            print("\n=== 伺服器整個掛掉（500）===")
            print(json.dumps(await js("""
              (function(){
                return {
                  有跳對話框: document.getElementById('ask').classList.contains('open'),
                  有跳toast: document.getElementById('toast').classList.contains('show'),
                  現場頁正常: document.getElementById('v-scene').classList.contains('on'),
                  緊急電話還在: !!document.querySelector('a[href="tel:110"]'),
                  資料還在: !!localStorage.getItem('aa.case.kf'),
                  仍然登入著: localStorage.getItem('aa.registered.v1')
                };
              })()
            """, awaitp=False), ensure_ascii=False, indent=2))
    finally:
        proc.terminate()


asyncio.run(run())
