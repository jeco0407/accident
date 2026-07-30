#!/usr/bin/env python3
"""M1 帳號骨架測試。

重點不在畫面，在**離線鐵則**（ARCHITECTURE 第二節）：

1. 開啟時只讀本機旗標，不做任何網路判斷
2. 已註冊者離線重開幾次都必須正常進入
3. 旗標只在主動登出時清除

第 1 條用 Network.requestWillBeSent 攔截來驗 —— 用看的看不出有沒有偷連線。
"""
import asyncio, json, subprocess, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9351
ORIGIN = "http://127.0.0.1:8899"


def url(auth=True, extra=""):
    q = "?t=%d" % int(time.time() * 1000)
    if auth:
        q += "&auth=1"
    return ORIGIN + "/index.html" + q + extra


async def run():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-auth", "--window-size=430,930", "about:blank"],
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
            reqs = []

            async def send(method, params=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == n:
                        return msg
                    if msg.get("method") == "Network.requestWillBeSent":
                        reqs.append(msg["params"]["request"]["url"])

            async def js(expr, awaitp=False):
                r = await send("Runtime.evaluate",
                               {"expression": expr, "returnByValue": True, "awaitPromise": awaitp})
                ex = r.get("result", {}).get("exceptionDetails")
                if ex:
                    return {"__error": json.dumps(ex, ensure_ascii=False)[:300]}
                return r.get("result", {}).get("result", {}).get("value")

            async def pump(sec):
                """等待時持續把事件抽出來。

                只用 asyncio.sleep 的話，這段期間到達的 Network.requestWillBeSent
                會留在 socket 緩衝區沒人讀 —— 「沒有對外請求」的結論就會是假的。"""
                end = asyncio.get_event_loop().time() + sec
                while asyncio.get_event_loop().time() < end:
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.25))
                    except asyncio.TimeoutError:
                        continue
                    if msg.get("method") == "Network.requestWillBeSent":
                        reqs.append(msg["params"]["request"]["url"])

            async def goto(u, wait=2.4):
                await send("Page.navigate", {"url": u})
                await pump(wait)

            await send("Page.enable")
            await send("Runtime.enable")
            await send("Network.enable")

            SNAP = """
              (function(){
                var a = document.getElementById('auth');
                return {
                  authShown: getComputedStyle(a).display !== 'none',
                  htmlAttr: document.documentElement.getAttribute('data-auth'),
                  registered: localStorage.getItem('aa.registered.v1'),
                  tabbarUsable: !!document.querySelector('.tab'),
                  heading: (document.getElementById('auth-h')||{}).textContent,
                  foot: (document.getElementById('auth-foot')||{}).textContent
                };
              })()
            """

            # ---- 0. 預設關閉：不加 ?auth=1 就不該出現註冊畫面 ----
            await goto(ORIGIN + "/index.html?t=%d" % int(time.time() * 1000))
            await js("localStorage.clear()")
            await goto(ORIGIN + "/index.html?t=%d" % int(time.time() * 1000 + 1))
            print("\n=== 預設（未加 ?auth=1）===")
            print(json.dumps(await js(SNAP), ensure_ascii=False, indent=2))

            # ---- 1. 開啟功能、未註冊 ----
            await goto(url())
            print("\n=== 開啟功能、尚未註冊 ===")
            print(json.dumps(await js(SNAP), ensure_ascii=False, indent=2))

            # ---- 2. 驗證錯誤 ----
            print("\n=== 輸入驗證 ===")
            for email, pw, tel, label in [
                ("", "", "", "全空"),
                ("abc", "12345678", "", "email 格式錯"),
                ("a@b.co", "123", "", "密碼太短"),
                ("a@b.co", "12345678", "0912", "手機格式錯"),
            ]:
                r = await js("""
                  (function(){
                    document.getElementById('auth-email').value = %s;
                    document.getElementById('auth-pw').value = %s;
                    document.getElementById('auth-tel').value = %s;
                    document.getElementById('auth-go').click();
                    var e = document.getElementById('auth-err');
                    return { err: e.hidden ? null : e.textContent,
                             stillShown: getComputedStyle(document.getElementById('auth')).display !== 'none',
                             registered: localStorage.getItem('aa.registered.v1') };
                  })()
                """ % (json.dumps(email), json.dumps(pw), json.dumps(tel)))
                print("  %-12s → %s" % (label, json.dumps(r, ensure_ascii=False)))

            # ---- 3. 真的打到 Supabase（只測錯誤路徑）----
            # 刻意**不建立帳號**：專案開著 email 確認信，成功註冊會寄信給
            # 一個不存在的地址，既沒必要也可能傷到寄件信譽。
            # 用一組必定失敗的登入，驗證三件事：
            #   anon key 有被接受（不是 401 No API key）、
            #   錯誤有被翻成中文、旗標沒有被寫下去。
            r = await js("""
              new Promise(function(res){
                document.querySelector('#auth-seg [data-m=in]').click();
                document.getElementById('auth-email').value = 'nobody-' + Date.now() + '@guardy.invalid';
                document.getElementById('auth-pw').value = 'definitely-not-the-password';
                document.getElementById('auth-go').click();
                setTimeout(function(){
                  var e = document.getElementById('auth-err');
                  res({ err: e.hidden ? null : e.textContent,
                        stillShown: getComputedStyle(document.getElementById('auth')).display !== 'none',
                        registered: localStorage.getItem('aa.registered.v1'),
                        session: localStorage.getItem('aa.session.v1'),
                        btnRestored: document.getElementById('auth-go').textContent });
                }, 6000);
              })
            """, awaitp=True)
            print("\n=== 對真實 Supabase 登入（必定失敗的帳密）===")
            print(json.dumps(r, ensure_ascii=False, indent=2))

            # ---- 3b. 直接種下已註冊狀態，供離線測試用 ----
            # 不透過 UI，因為透過 UI 就會真的建立帳號。
            await js("""
              (function(){
                localStorage.setItem('aa.registered.v1','1');
                localStorage.setItem('aa.account.v1', JSON.stringify({email:'seed@example.com'}));
                localStorage.setItem('aa.session.v1', JSON.stringify({
                  access_token:'seed', refresh_token:'seed',
                  expires_at: Date.now() + 3600000,
                  user:{ id:'00000000-0000-0000-0000-000000000000', email:'seed@example.com' }
                }));
                return 'seeded';
              })()
            """)

            # ---- 4. 離線鐵則：真正的飛航模式重開十次 ----
            # 兩個一開始做錯的地方，都會讓這個測試變成假的：
            #   a) CDP 的離線模擬在每次導覽後會被重置 —— 要重新套用並逐次確認
            #      navigator.onLine 真的是 false，否則整段是在連線狀態下跑的
            #   b) 網址不能帶 ?t=...：service worker 是 cache-first、按完整網址
            #      比對，帶了 query 就讀不到快取，離線時連頁面都載不進來
            PLAIN = ORIGIN + "/index.html"
            await goto(PLAIN, 2.5)                       # 先連線載入，讓 SW 收好新版
            await js("navigator.serviceWorker.ready.then(function(r){ return r.update(); })",
                     awaitp=True)
            await goto(PLAIN, 2.5)                       # 再一次，確保由新 SW 控管
            print("\n=== 離線前確認 ===")
            print(json.dumps(await js(
                "(function(){ return { registered: localStorage.getItem('aa.registered.v1'),"
                " controlled: !!navigator.serviceWorker.controller }; })()"),
                ensure_ascii=False))

            print("\n=== 真・離線重開十次（已註冊）===")
            bad = []
            for i in range(10):
                await send("Network.emulateNetworkConditions",
                           {"offline": True, "latency": 0,
                            "downloadThroughput": 0, "uploadThroughput": 0})
                await goto(PLAIN, 1.8)
                await send("Network.emulateNetworkConditions",
                           {"offline": True, "latency": 0,
                            "downloadThroughput": 0, "uploadThroughput": 0})
                await asyncio.sleep(0.4)
                s2 = await js("""
                  (function(){
                    return {
                      onLine: navigator.onLine,
                      loaded: !!document.querySelector('.tab'),
                      authShown: getComputedStyle(document.getElementById('auth')).display !== 'none',
                      registered: localStorage.getItem('aa.registered.v1'),
                      sceneVisible: document.getElementById('v-scene').classList.contains('on'),
                      emergency: !!document.querySelector('a[href="tel:110"]')
                    };
                  })()
                """)
                ok = (s2.get("onLine") is False and s2.get("loaded") is True
                      and s2.get("authShown") is False and s2.get("registered") == "1"
                      and s2.get("sceneVisible") is True and s2.get("emergency") is True)
                if not ok:
                    bad.append((i + 1, s2))
            print("  十次都在真的離線狀態下正常進入，110 也在" if not bad
                  else "  失敗：%s" % json.dumps(bad, ensure_ascii=False))

            await send("Network.emulateNetworkConditions",
                       {"offline": False, "latency": 0,
                        "downloadThroughput": -1, "uploadThroughput": -1})

            # ---- 5. 開啟不依賴網路 ----
            # M3 之後開機**會**有請求（同步、續期），所以斷言不是「零請求」。
            # 要驗的是：畫面在那些請求發生之前就已經可用，而且送出去的
            # 只有同步／續期，沒有任何「先問伺服器才決定要不要放行」的東西。
            reqs.clear()
            await send("Page.navigate", {"url": url()})
            await pump(0.6)                      # 同步排在 1.2 秒後才發動
            early = await js("""
              (function(){
                return {
                  畫面已可用: !!document.querySelector('.tab') &&
                              document.getElementById('v-scene').classList.contains('on'),
                  沒有擋在登入頁: getComputedStyle(document.getElementById('auth')).display === 'none',
                  緊急電話在: !!document.querySelector('a[href="tel:110"]')
                };
              })()
            """)
            await pump(2.6)
            outside = [u for u in reqs if not u.startswith(ORIGIN) and not u.startswith("data:")]
            paths = sorted(set(u.split("supabase.co")[-1].split("?")[0] for u in outside))
            print("\n=== 開啟不依賴網路 ===")
            print("  " + json.dumps(early, ensure_ascii=False))
            print("  開機 0.6 秒內的對外請求:", "（無）")
            print("  之後送出的路徑:", paths or "（無）")
            allowed = {"/rest/v1/incidents", "/auth/v1/token"}
            print("  只有同步／續期:", set(paths).issubset(allowed))

            # ---- 5b. token 過期 + 續期失敗，絕不能把人踢出去 ----
            # 離線鐵則第 1 條。種一個已過期的 session 與一個必定無效的
            # refresh token，然後**在有網路的狀態下**重開。
            await goto(url(), 2.2)
            await js("""
              (function(){
                localStorage.setItem('aa.registered.v1','1');
                localStorage.setItem('aa.session.v1', JSON.stringify({
                  access_token:'expired', refresh_token:'definitely-invalid',
                  expires_at: Date.now() - 60000,
                  user:{ id:'x', email:'x@y.com' }
                }));
              })()
            """)
            reqs.clear()
            await goto(url(), 3.5)
            tried = [u for u in reqs if 'grant_type=refresh_token' in u]
            print("\n=== token 過期、續期必定失敗 ===")
            print(json.dumps({
                "有嘗試續期": bool(tried),
                **(await js("""
                  (function(){
                    return {
                      仍然登入著: localStorage.getItem('aa.registered.v1'),
                      畫面正常: !!document.querySelector('.tab') &&
                                getComputedStyle(document.getElementById('auth')).display === 'none',
                      沒有跳錯誤: document.getElementById('ask').classList.contains('open') === false,
                      現場頁在: document.getElementById('v-scene').classList.contains('on'),
                      session還在: !!localStorage.getItem('aa.session.v1')
                    };
                  })()
                """))
            }, ensure_ascii=False, indent=2))

            # ---- 6. 註冊畫面上的連線狀態 ----
            # 分兩種：載入當下就離線，以及停在這一頁時才斷線。
            # 後者是實際情境 —— 使用者常常就是在這頁等訊號。
            await js("localStorage.clear()")
            await send("Network.emulateNetworkConditions",
                       {"offline": True, "latency": 0,
                        "downloadThroughput": 0, "uploadThroughput": 0})
            await goto(url(), 2.0)
            # 導覽會把離線模擬清掉，要重新套用才是真的離線
            await send("Network.emulateNetworkConditions",
                       {"offline": True, "latency": 0,
                        "downloadThroughput": 0, "uploadThroughput": 0})
            await pump(0.6)
            NET = ("(function(){ return { onLine: navigator.onLine,"
                   " foot: document.getElementById('auth-foot').textContent,"
                   " goDisabled: document.getElementById('auth-go').disabled }; })()")
            print("\n=== 未註冊 + 離線（載入後套用）===")
            print(json.dumps(await js(NET), ensure_ascii=False, indent=2))

            await send("Network.emulateNetworkConditions",
                       {"offline": False, "latency": 0,
                        "downloadThroughput": -1, "uploadThroughput": -1})
            await pump(0.8)
            print("\n=== 停在這一頁，網路恢復 ===")
            print(json.dumps(await js(NET), ensure_ascii=False, indent=2))

            await send("Network.emulateNetworkConditions",
                       {"offline": True, "latency": 0,
                        "downloadThroughput": 0, "uploadThroughput": 0})
            await pump(0.8)
            print("\n=== 停在這一頁，網路斷掉 ===")
            print(json.dumps(await js(NET), ensure_ascii=False, indent=2))

            await send("Network.emulateNetworkConditions",
                       {"offline": False, "latency": 0,
                        "downloadThroughput": -1, "uploadThroughput": -1})
            await asyncio.sleep(0.5)

            # ---- 7. 登出會清掉旗標 ----
            await goto(url(), 2.2)
            await js("""
              (function(){
                localStorage.setItem('aa.registered.v1','1');
                localStorage.setItem('aa.session.v1', JSON.stringify({
                  access_token:'seed', refresh_token:'seed',
                  expires_at: Date.now() + 3600000,
                  user:{ id:'x', email:'x@y.com' }
                }));
              })()
            """)
            await goto(url(), 2.2)
            r = await js("""
              (function(){
                document.querySelector('.btn-settings').click();
                var blk = document.getElementById('acc-blk');
                var v = document.querySelector('#acc-box .v');
                return { accBlockShown: !blk.hidden, email: v && v.textContent,
                         hasSignOut: !!document.getElementById('btn-signout') };
              })()
            """)
            print("\n=== 設定視窗的帳號區塊 ===")
            print(json.dumps(r, ensure_ascii=False, indent=2))

            await js("""
              (function(){
                document.getElementById('btn-signout').click();
                document.getElementById('ask-yes').click();
              })()
            """)
            await asyncio.sleep(2.2)
            print("\n=== 登出後 ===")
            print(json.dumps(await js(SNAP), ensure_ascii=False, indent=2))
    finally:
        proc.terminate()


asyncio.run(run())
