#!/usr/bin/env python3
"""損害賠償請求明細（求償分頁 → 匯出請求明細）

驗證重點：
  1. 一筆都沒填時按鈕停用，填了才開
  2. 只列出 > 0 的項目 —— 填 0 跟沒填在這張表上是同一件事
  3. 合計等於各項相加
  4. 缺的欄位顯示「未填寫」而不是留白
  5. 使用者輸入會被跳脫，不會變成 HTML（明細與現場的對方資料卡都測）
  6. 列印時 body 底下只剩這張表
  7. 慰撫金不在表裡（那是刻意的，不是漏掉）

用法：先在專案根目錄開 `python3 -m http.server 8899`，再跑這支。
"""
import asyncio, json, subprocess, sys, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9362
URL = "http://localhost:8899/index.html"

CASE = {
    "aa.comp.v1": {"med": "48250", "rehab": "12000", "care": "0",
                   "trans": "3400", "work": "86000", "car": "157800", "prop": "6900"},
    "aa.other.v1": {"plate": "ABC-1234", "name": "<img src=x onerror=alert(1)>",
                    "tel": "0912345678", "insurer": ""},
    "aa.site.v1": {"lat": 25.04776, "lon": 121.51706, "addr": "臺北市中正區北平西路3號"},
}
ME = {"name": "陳大文", "plate": "XYZ-5678", "ins": "富邦產險",
      "policy": "FB-2026-001234", "ecName": "", "ecTel": ""}

EXPECT_TOTAL = 48250 + 12000 + 3400 + 86000 + 157800 + 6900   # care 是 0，不算

fails = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("　" + str(detail)) if detail else ""))
    if not ok:
        fails.append(name)


async def main():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-test-cdoc", "about:blank"],
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

            await send("Page.enable")
            await send("Runtime.enable")
            await send("Network.enable")
            # service worker 是 cache-first，不繞過的話永遠測到上一版
            await send("Network.setBypassServiceWorker", {"bypass": True})
            await send("Network.setCacheDisabled", {"cacheDisabled": True})
            await send("Emulation.setDeviceMetricsOverride",
                       {"width": 430, "height": 932, "deviceScaleFactor": 2, "mobile": True})

            print("=== 沒有任何金額 ===")
            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(2.0)
            await ev("localStorage.clear()")
            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(2.0)
            check("一筆都沒填時匯出鍵停用",
                  await ev("document.getElementById('cdoc-open').disabled") is True)

            print("\n=== 填入資料 ===")
            seed = (
                "(function(){var id='t';"
                "localStorage.setItem('aa.cases.v1',JSON.stringify({cur:id,"
                "list:[{id:id,ts:Date.now(),closed:false}]}));"
                "localStorage.setItem('aa.case.'+id," + json.dumps(json.dumps(CASE, ensure_ascii=False)) + ");"
                "localStorage.setItem('aa.me.v1'," + json.dumps(json.dumps(ME, ensure_ascii=False)) + ");})()"
            )
            await ev(seed)
            await send("Page.navigate", {"url": URL})
            await asyncio.sleep(2.2)

            check("小計卡顯示合計",
                  (await ev("document.getElementById('comp-total').textContent"))
                  == "$" + format(EXPECT_TOTAL, ","),
                  await ev("document.getElementById('comp-total').textContent"))
            check("匯出鍵可按",
                  await ev("document.getElementById('cdoc-open').disabled") is False)

            await ev("document.getElementById('cdoc-open').click()")
            await asyncio.sleep(.6)
            check("文件打得開",
                  await ev("document.getElementById('cdoc-sheet').classList.contains('open')") is True)

            txt = await ev("document.getElementById('cdoc-body').innerText")
            rows = await ev("document.querySelectorAll('#cdoc-body tbody tr:not(.grp):not(.sum)').length")

            check("只列出大於 0 的項目（7 欄填了 6 筆，看護費 0 不算）", rows == 6, rows)
            check("看護費用沒有出現在表裡", "看護費用" not in txt)
            check("合計正確", ("$" + format(EXPECT_TOTAL, ",")) in txt)
            check("空的欄位寫「未填寫」而不是留白", "未填寫" in txt)
            check("慰撫金不在表裡，但有說明為什麼",
                  "精神慰撫金" in txt and "不列入本表" in txt)
            check("標題不是「報價單」", "報價單" not in txt and "請求明細" in txt)

            html = await ev("document.getElementById('cdoc-body').innerHTML")
            check("使用者輸入有跳脫，沒有變成真的 <img>",
                  "<img src=x" not in html and "&lt;img src=x" in html)
            check("有簽名欄", "請求人簽名" in txt)

            print("\n=== 列印樣式 ===")
            await send("Emulation.setEmulatedMedia", {"media": "print"})
            await asyncio.sleep(.5)
            vis = await ev(
                "Array.prototype.filter.call(document.body.children,"
                "function(e){return getComputedStyle(e).display!=='none'})"
                ".map(function(e){return e.id||e.className}).join(',')")
            check("列印時 body 底下只剩這張表", vis == "cdoc-sheet", vis)
            check("列印時動作按鈕收起來",
                  await ev("getComputedStyle(document.querySelector"
                           "('#cdoc-sheet .cdoc-print-hide')).display") == "none")
            await send("Emulation.setEmulatedMedia", {"media": "screen"})

            print("\n=== 現場分頁的對方資料卡（v54 修掉的 XSS）===")
            html = await ev("document.getElementById('other-card').innerHTML")
            check("對方姓名有跳脫，沒有變成真的 <img>",
                  "<img src=x" not in html and "&lt;img src=x" in html)
            check("這一頁沒有跳出 alert（跳了的話上面早就卡住）",
                  await ev("1 + 1") == 2)

            print("\n=== 沒有波及 App 本體 ===")
            await ev("document.getElementById('cdoc-close').click()")
            await asyncio.sleep(.4)
            check("關得掉",
                  await ev("document.getElementById('cdoc-sheet').classList.contains('open')") is False)
            check("五個分頁還在",
                  await ev("document.querySelectorAll('.view').length") == 5)
    finally:
        proc.terminate()

    print("\n" + ("全部通過（0 項未通過）" if not fails
                  else "未通過 %d 項：%s" % (len(fails), "、".join(fails))))
    sys.exit(1 if fails else 0)


asyncio.run(main())
