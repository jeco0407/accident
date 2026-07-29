#!/usr/bin/env python3
"""用真實時間驅動 headless Chrome，避開 --virtual-time-budget 的虛擬時鐘假象。

用法: cdp.py <url> <等待秒數> <要求值的 JS 運算式>
"""
import asyncio, json, subprocess, sys, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333


async def main(url, wait_s, expr):
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-profile", "--window-size=500,1000",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = [t for t in tabs if t["type"] == "page"]
                if page:
                    ws_url = page[0]["webSocketDebuggerUrl"]
                    break
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

            await send("Page.enable")
            await send("Runtime.enable")
            await send("Page.navigate", {"url": url})
            await asyncio.sleep(wait_s)          # 真實時間等待
            if expr.startswith("SHOT:"):
                target = expr[5:]
                pre = ""
                if "|||" in target:
                    target, pre = target.split("|||", 1)
                if pre:
                    pr = await send("Runtime.evaluate",
                                    {"expression": pre, "returnByValue": True, "awaitPromise": True})
                    ex = pr.get("result", {}).get("exceptionDetails")
                    if ex:
                        print("PRE_JS_ERROR:", json.dumps(ex, ensure_ascii=False)[:300])
                    await asyncio.sleep(0.8)
                await send("Emulation.setDeviceMetricsOverride",
                           {"width": 500, "height": 1200, "deviceScaleFactor": 1,
                            "mobile": True})
                await asyncio.sleep(0.5)
                shot = await send("Page.captureScreenshot",
                                  {"format": "png", "captureBeyondViewport": True})
                import base64
                open(target, "wb").write(base64.b64decode(shot["result"]["data"]))
                print("SHOT_OK " + target)
                return
            r = await send("Runtime.evaluate",
                           {"expression": expr, "returnByValue": True, "awaitPromise": True})
            res = r.get("result", {}).get("result", {})
            if "value" in res:
                print(res["value"])
            else:
                print("EVAL:", json.dumps(res, ensure_ascii=False)[:400])
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], float(sys.argv[2]), sys.argv[3]))
