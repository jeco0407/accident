#!/usr/bin/env python3
"""身分選擇（一般使用者／保險業務員）。

這個功能唯一的風險不在畫面，在**它有沒有偷偷變成權限**。
所以除了流程，最後一段直接掃 App 原始碼，確認 role 沒有出現在
任何同步／查詢的條件裡；SQL 那邊則由 003_role.sql 的驗證查詢負責。

流程本身要驗四件事：
  1. 已註冊但沒選過身分 → 停在身分屏（不是歡迎屏、也不是直接放行）
  2. 沒選之前「繼續」是停用的
  3. 選完之後放行，重開不再問
  4. 登出會把身分一起清掉 —— 否則下一個人會繼承上一個人的身分
"""
import asyncio, json, re, subprocess, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9357
ORIGIN = "http://127.0.0.1:8899"
PLAIN = ORIGIN + "/index.html"


def url():
    return ORIGIN + "/index.html?t=%d&auth=1" % int(time.time() * 1000)


SNAP = """
  (function(){
    var a = document.getElementById('auth');
    var go = document.getElementById('role-go');
    return {
      data_auth: document.documentElement.getAttribute('data-auth'),
      全螢幕層顯示: getComputedStyle(a).display !== 'none',
      歡迎屏顯示: getComputedStyle(document.getElementById('auth-welcome')).display !== 'none',
      身分屏顯示: getComputedStyle(document.getElementById('auth-role')).display !== 'none',
      繼續鍵停用: go.disabled,
      已選: (document.querySelector('.role-opt[aria-pressed=true]')||{dataset:{}}).dataset.role || null,
      本機身分: localStorage.getItem('aa.role.v1'),
      /* 「App 可用」= 全螢幕層沒有蓋著。分頁列與 v-scene 在身分屏底下
         其實一直都在（.auth 是 position:fixed 的不透明整頁），
         拿它們當判準會永遠是 true —— 第一版就是這樣寫，因此漏測。 */
      App可用: getComputedStyle(document.getElementById('auth')).display === 'none' &&
               !!document.querySelector('.tab') &&
               document.getElementById('v-scene').classList.contains('on')
    };
  })()
"""

SEED = """
  (function(){
    localStorage.setItem('aa.registered.v1','1');
    localStorage.setItem('aa.account.v1', JSON.stringify({email:'seed@example.com'}));
    localStorage.setItem('aa.session.v1', JSON.stringify({
      access_token:'seed', refresh_token:'seed',
      expires_at: Date.now() + 3600000,
      user:{ id:'00000000-0000-0000-0000-000000000000', email:'seed@example.com' }
    }));
    localStorage.removeItem('aa.role.v1');
    return 'seeded';
  })()
"""


def ok(label, cond):
    print("  %s %s" % ("PASS" if cond else "FAIL", label))
    return cond


async def run():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-role", "--window-size=430,930", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fails = []
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
                    return {"__error": json.dumps(ex, ensure_ascii=False)[:400]}
                return r.get("result", {}).get("result", {}).get("value")

            async def pump(sec):
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

            # ---- 1. 已註冊、未選身分 ----
            await goto(url())
            await js("localStorage.clear()")
            await js(SEED)
            await goto(url())
            s = await js(SNAP)
            print("\n=== 已註冊、還沒選身分 ===")
            print(json.dumps(s, ensure_ascii=False, indent=2))
            fails += [x for x in [
                None if ok("停在身分屏", s.get("data_auth") == "role") else 1,
                None if ok("不是歡迎屏", s.get("歡迎屏顯示") is False) else 1,
                None if ok("沒選之前繼續鍵停用", s.get("繼續鍵停用") is True) else 1,
                None if ok("還沒放行", s.get("App可用") is False) else 1,
            ] if x]

            # ---- 2. 選「保險業務員」 ----
            print("\n=== 選保險業務員 ===")
            await js("document.querySelector('.role-opt[data-role=agent]').click()")
            s = await js(SNAP)
            fails += [x for x in [
                None if ok("選中狀態有反映", s.get("已選") == "agent") else 1,
                None if ok("繼續鍵解除停用", s.get("繼續鍵停用") is False) else 1,
                None if ok("按下去之前不寫入本機", s.get("本機身分") is None) else 1,
            ] if x]

            await js("document.getElementById('role-go').click()")
            await pump(0.6)
            s = await js(SNAP)
            print(json.dumps(s, ensure_ascii=False, indent=2))
            fails += [x for x in [
                None if ok("放行進入 App", s.get("App可用") is True) else 1,
                None if ok("全螢幕層收起", s.get("全螢幕層顯示") is False) else 1,
                None if ok("身分寫進本機", s.get("本機身分") == "agent") else 1,
            ] if x]

            # ---- 3. 重開不再問 ----
            await goto(url())
            s = await js(SNAP)
            print("\n=== 重開 ===")
            fails += [x for x in [
                None if ok("不再問身分", s.get("data_auth") is None) else 1,
                None if ok("直接進入 App", s.get("App可用") is True) else 1,
                None if ok("身分還在", s.get("本機身分") == "agent") else 1,
            ] if x]

            # ---- 3b. 離線重開也不問 ----
            # 身分只讀 localStorage。萬一哪天改成先去雲端撈，這一段會抓到。
            await goto(PLAIN, 2.5)
            await js("navigator.serviceWorker.ready.then(function(r){ return r.update(); })",
                     awaitp=True)
            await goto(PLAIN, 2.5)
            await send("Network.emulateNetworkConditions",
                       {"offline": True, "latency": 0,
                        "downloadThroughput": 0, "uploadThroughput": 0})
            await goto(PLAIN, 2.0)
            await send("Network.emulateNetworkConditions",
                       {"offline": True, "latency": 0,
                        "downloadThroughput": 0, "uploadThroughput": 0})
            await asyncio.sleep(0.4)
            s = await js(SNAP)
            offline = await js("navigator.onLine")
            print("\n=== 離線重開 ===")
            fails += [x for x in [
                None if ok("真的離線", offline is False) else 1,
                None if ok("沒有被身分屏擋住", s.get("data_auth") is None) else 1,
                None if ok("App 可用", s.get("App可用") is True) else 1,
            ] if x]
            await send("Network.emulateNetworkConditions",
                       {"offline": False, "latency": 0,
                        "downloadThroughput": -1, "uploadThroughput": -1})

            # ---- 4. 設定裡改身分 ----
            await goto(url())
            print("\n=== 從設定改身分 ===")
            # 整個 App 包在一個 IIFE 裡，外面拿不到 openSettings 之類的函式。
            # 只能走真實路徑：按頁首的齒輪。
            r = await js("""
              (function(){
                document.querySelector('.btn-settings, [aria-label=設定]').click();
                var b = document.getElementById('btn-role');
                if (!b) return { err:'設定裡沒有身分列' };
                var label = b.querySelector('.rv').textContent;
                b.click();
                return { 設定顯示的身分: label,
                         叫出身分屏: document.documentElement.getAttribute('data-auth'),
                         帶著目前選擇: (document.querySelector('.role-opt[aria-pressed=true]')||
                                        {dataset:{}}).dataset.role };
              })()
            """)
            print("  " + json.dumps(r, ensure_ascii=False))
            fails += [x for x in [
                None if ok("設定裡看得到身分", r.get("設定顯示的身分") == "保險業務員") else 1,
                None if ok("點下去叫出身分屏", r.get("叫出身分屏") == "role") else 1,
                None if ok("帶著目前的選擇進來", r.get("帶著目前選擇") == "agent") else 1,
            ] if x]

            await js("""
              (function(){
                document.querySelector('.role-opt[data-role=user]').click();
                document.getElementById('role-go').click();
              })()
            """)
            await pump(0.5)
            s = await js(SNAP)
            fails += [x for x in [
                None if ok("改成一般使用者", s.get("本機身分") == "user") else 1,
                None if ok("改完回到 App", s.get("App可用") is True) else 1,
            ] if x]

            # ---- 5. 登出要把身分一起清掉 ----
            print("\n=== 登出 ===")
            await js("""
              (function(){
                document.querySelector('.btn-settings, [aria-label=設定]').click();
                document.getElementById('btn-signout').click();
                document.getElementById('ask-yes').click();
              })()
            """)
            await pump(2.5)
            left = await js("""
              (function(){
                return { registered: localStorage.getItem('aa.registered.v1'),
                         role: localStorage.getItem('aa.role.v1'),
                         session: localStorage.getItem('aa.session.v1') };
              })()
            """)
            print("  " + json.dumps(left, ensure_ascii=False))
            fails += [x for x in [
                None if ok("旗標清掉", left.get("registered") is None) else 1,
                None if ok("身分也清掉", left.get("role") is None) else 1,
            ] if x]

    finally:
        proc.terminate()

    # ---- 6. 靜態檢查：role 不准變成權限 ----
    # 前面五段驗的是「現在的行為」。這一段驗的是「以後也不准」——
    # 身分是使用者自己勾的、沒有驗證，一旦被拿去當查詢或同步的條件，
    # 任何人點兩下就能拿到不該拿的東西。
    print("\n=== 靜態檢查：role 沒有變成權限 ===")
    src = open("../index.html", encoding="utf-8").read()
    bad = []
    for m in re.finditer(r"^.*\brole\b.*$", src, re.M):
        line = m.group(0)
        if "/rest/v1/" in line and "profiles" not in line:
            bad.append(line.strip())
        if re.search(r"role\s*(===?|!==?)\s*['\"]agent['\"]", line) and "ico(" not in line:
            bad.append(line.strip())
    fails += [x for x in [
        None if ok("role 沒有出現在 profiles 以外的 REST 查詢裡", not bad) else 1,
    ] if x]
    if bad:
        for b in bad:
            print("     " + b[:120])

    sql = open("../supabase/003_role.sql", encoding="utf-8").read()
    fails += [x for x in [
        None if ok("003_role.sql 沒有建立任何政策",
                   "create policy" not in sql.lower()) else 1,
    ] if x]

    print("\n%s（%d 項未通過）" % ("全部通過" if not fails else "有失敗", len(fails)))


asyncio.run(run())
