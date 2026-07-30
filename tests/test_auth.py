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

            async def goto(u, wait=2.4):
                await send("Page.navigate", {"url": u})
                await asyncio.sleep(wait)

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

            # ---- 3. 正確填寫 ----
            r = await js("""
              (function(){
                document.getElementById('auth-email').value = 'user@example.com';
                document.getElementById('auth-pw').value = 'hunter2hunter2';
                document.getElementById('auth-tel').value = '0912345678';
                document.getElementById('auth-go').click();
                return {
                  authShown: getComputedStyle(document.getElementById('auth')).display !== 'none',
                  registered: localStorage.getItem('aa.registered.v1'),
                  account: localStorage.getItem('aa.account.v1')
                };
              })()
            """)
            print("\n=== 建立帳號 ===")
            print(json.dumps(r, ensure_ascii=False, indent=2))

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

            # ---- 5. 開啟過程有沒有偷連線 ----
            reqs.clear()
            await goto(url(), 2.0)
            outside = [u for u in reqs if not u.startswith(ORIGIN) and not u.startswith("data:")]
            print("\n=== 開啟時的對外請求（應為空）===")
            print("  ", outside or "（無）")

            await send("Network.emulateNetworkConditions",
                       {"offline": False, "latency": 0,
                        "downloadThroughput": -1, "uploadThroughput": -1})

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
            await asyncio.sleep(0.6)
            NET = ("(function(){ return { onLine: navigator.onLine,"
                   " foot: document.getElementById('auth-foot').textContent,"
                   " goDisabled: document.getElementById('auth-go').disabled }; })()")
            print("\n=== 未註冊 + 離線（載入後套用）===")
            print(json.dumps(await js(NET), ensure_ascii=False, indent=2))

            await send("Network.emulateNetworkConditions",
                       {"offline": False, "latency": 0,
                        "downloadThroughput": -1, "uploadThroughput": -1})
            await asyncio.sleep(0.8)
            print("\n=== 停在這一頁，網路恢復 ===")
            print(json.dumps(await js(NET), ensure_ascii=False, indent=2))

            await send("Network.emulateNetworkConditions",
                       {"offline": True, "latency": 0,
                        "downloadThroughput": 0, "uploadThroughput": 0})
            await asyncio.sleep(0.8)
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
                document.getElementById('auth-email').value='x@y.com';
                document.getElementById('auth-pw').value='12345678';
                document.getElementById('auth-go').click();
              })()
            """)
            await asyncio.sleep(0.6)
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
