#!/usr/bin/env python3
"""事故案件（2.1）測試：舊資料遷移、案件隔離、照片歸屬、刪除。

重點在「舊版使用者升上來不能掉資料」——這是唯一改壞就救不回來的地方。
"""
import asyncio, json, subprocess, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9337
URL = "http://127.0.0.1:8899/index.html"
SEED_PAGE = "http://127.0.0.1:8899/manifest.json"   # 同源、不載入 App

# 模擬 v26 使用者：8 個舊 key 都有資料
SEED_OLD = r"""
(function(){
  localStorage.clear();
  localStorage.setItem('aa.site.v1', JSON.stringify(
    {lat:25.03746, lon:121.56497, acc:12, at:1700000000000, addr:'台北市信義區市府路45號'}));
  localStorage.setItem('aa.timeline.v1', JSON.stringify({0:true,1:true}));
  localStorage.setItem('aa.other.v1', JSON.stringify({plate:'ABC-1234', name:'王小明'}));
  localStorage.setItem('aa.comp.v1', JSON.stringify({med:'12000'}));
  localStorage.setItem('aa.claim.v1', JSON.stringify({2:true}));
  localStorage.setItem('aa.photos.v1', JSON.stringify({0:true}));
  localStorage.setItem('aa.compdoc.v1', JSON.stringify({1:true}));
  localStorage.setItem('aa.todo.v1', JSON.stringify({3:true}));
  return 'seeded';
})()
"""

# 用舊的 schema（version 1、沒有 case 欄位）塞一張照片
SEED_OLD_PHOTO = r"""
new Promise(function(res,rej){
  var del = indexedDB.deleteDatabase('aa-photos');
  del.onblocked = function(){ rej(new Error('deleteDatabase blocked：還有頁面開著連線')); };
  del.onsuccess = function(){
    var r = indexedDB.open('aa-photos', 1);
    r.onupgradeneeded = function(){
      var s = r.result.createObjectStore('photos',{keyPath:'id',autoIncrement:true});
      s.createIndex('slot','slot');
    };
    r.onsuccess = function(){
      var d = r.result, t = d.transaction('photos','readwrite');
      t.objectStore('photos').add({slot:0, ts:1700000000000, type:'image/jpeg',
        buf:new ArrayBuffer(1024), thumb:'data:,'});
      t.oncomplete = function(){ d.close(); res('old photo added'); };
      t.onerror = function(){ rej(t.error); };
    };
    r.onerror = function(){ rej(r.error); };
  };
})
"""

CHECK_MIGRATION = r"""
(function(){
  var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
  var pack = JSON.parse(localStorage.getItem('aa.case.' + idx.cur));
  return {
    caseCount: idx.list.length,
    curTs: idx.list[0].ts,
    closed: idx.list[0].closed,
    keysInPack: Object.keys(pack).sort(),
    addr: (pack['aa.site.v1']||{}).addr,
    plate: (pack['aa.other.v1']||{}).plate,
    med: (pack['aa.comp.v1']||{}).med,
    oldKeyStillThere: localStorage.getItem('aa.site.v1') !== null,
    locOnScreen: (document.getElementById('loc-addr')||{}).textContent,
    photosLoaded: (window.__t ? 0 : document.querySelectorAll('#ph-body .ph.done').length),
    caseTitle: (document.querySelector('#case-cur .ttl')||{}).textContent,
    caseTag: (document.querySelector('#case-cur .case-tag')||{}).textContent,
    histHidden: document.getElementById('case-hist-blk').hidden
  };
})()
"""


async def run():
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-cases", "--window-size=430,930",
         "about:blank"],
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
                    return {"__error": json.dumps(ex, ensure_ascii=False)[:400]}
                return r.get("result", {}).get("result", {}).get("value")

            async def goto(url, wait=2.2):
                await send("Page.navigate", {"url": url})
                await asyncio.sleep(wait)

            await send("Page.enable")
            await send("Runtime.enable")

            # ---- 1. 在同源但沒有 App 的頁面上塞舊資料 ----
            # 不能在 index.html 上做：頁面開著 aa-photos 的連線，
            # deleteDatabase 會 onblocked 而不是 onsuccess，測試會直接卡死。
            await goto(SEED_PAGE, 1.2)
            print("seed:", await js(SEED_OLD, awaitp=False))
            print("seed photo:", await js(SEED_OLD_PHOTO))

            # ---- 2. 重新載入 = 使用者升級到新版 ----
            await goto(URL, 2.8)
            r = await js(CHECK_MIGRATION, awaitp=False)
            print("\n=== 遷移後 ===")
            print(json.dumps(r, ensure_ascii=False, indent=2))

            print("\n照片是否跟著遷移（應為 1 張，且 case 欄位已回填）:")
            print(await js("""
              (function(){
                return new Promise(function(res){
                  var r = indexedDB.open('aa-photos');
                  r.onsuccess = function(){
                    var d = r.result;
                    d.transaction('photos').objectStore('photos').getAll().onsuccess = function(e){
                      var all = e.target.result;
                      var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                      res({total: all.length, cases: all.map(function(p){return p.case;}),
                           matchesCur: all.every(function(p){ return p.case === idx.cur; }),
                           dbVersion: d.version});
                    };
                  };
                });
              })()
            """))

            # ---- 3. 建立新案件，確認資料隔離 ----
            await js("""
              (function(){
                var b = document.querySelector('#case-cur [data-act="new"]');
                window.confirm = function(){ return true; };
                b.click();
              })()
            """, awaitp=False)
            await asyncio.sleep(1.2)
            print("\n=== 建立新案件後 ===")
            print(json.dumps(await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                return {
                  caseCount: idx.list.length,
                  newPackEmpty: Object.keys(JSON.parse(localStorage.getItem('aa.case.'+idx.cur))).length,
                  locOnScreen: (document.getElementById('loc-addr')||{}).textContent,
                  locCardReady: document.getElementById('loc-card').classList.contains('ready'),
                  tlDone: document.querySelectorAll('#tl .done').length,
                  otherPlate: (document.querySelector('[name=plate],#f-plate')||{}).value,
                  caseTitle: (document.querySelector('#case-cur .ttl')||{}).textContent,
                  histHidden: document.getElementById('case-hist-blk').hidden,
                  histRows: document.querySelectorAll('#case-hist .case-row').length,
                  histTitle: (document.querySelector('#case-hist .ttl')||{}).textContent,
                  photosShown: document.querySelectorAll('#ph-body .ph.done').length
                };
              })()
            """), ensure_ascii=False, indent=2))

            # ---- 4. 切回舊案件，資料要回來 ----
            await js("document.querySelector('#case-hist [data-go]').click()", awaitp=False)
            await asyncio.sleep(1.2)
            print("\n=== 切回第一件 ===")
            print(json.dumps(await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                var pack = JSON.parse(localStorage.getItem('aa.case.'+idx.cur));
                return {
                  addr: (pack['aa.site.v1']||{}).addr,
                  locOnScreen: (document.getElementById('loc-addr')||{}).textContent,
                  locCardReady: document.getElementById('loc-card').classList.contains('ready'),
                  tlDone: document.querySelectorAll('#tl .done').length,
                  photosShown: document.querySelectorAll('#ph-body .ph.done').length,
                  caseTitle: (document.querySelector('#case-cur .ttl')||{}).textContent
                };
              })()
            """), ensure_ascii=False, indent=2))

            # ---- 5. 重新載入，目前案件要記得 ----
            await goto(URL, 2.5)
            print("\n=== 重新載入後 ===")
            print(json.dumps(await js("""
              (function(){
                return {
                  locOnScreen: (document.getElementById('loc-addr')||{}).textContent,
                  caseTitle: (document.querySelector('#case-cur .ttl')||{}).textContent,
                  histRows: document.querySelectorAll('#case-hist .case-row').length
                };
              })()
            """), ensure_ascii=False, indent=2))

            # ---- 6. 結案 ----
            await js("window.confirm=function(){return true;};"
                     "document.querySelector('#case-cur [data-act=\"close\"]').click()", awaitp=False)
            await asyncio.sleep(1.2)
            print("\n=== 結案後 ===")
            print(json.dumps(await js("""
              (function(){
                var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                var closed = idx.list.filter(function(c){ return c.closed; });
                return {
                  caseCount: idx.list.length,
                  closedCount: closed.length,
                  curIsNew: !idx.list.filter(function(c){return c.id===idx.cur;})[0].closed,
                  histRows: document.querySelectorAll('#case-hist .case-row').length,
                  histMetas: [].map.call(document.querySelectorAll('#case-hist .meta'),
                                         function(e){return e.textContent;})
                };
              })()
            """), ensure_ascii=False, indent=2))

            # ---- 7. 刪除「有照片的那一件」，照片必須一起走 ----
            # 刻意挑已結案那件（就是遷移進來、帶著照片的第一件），
            # 隨手刪第一列會刪到空案件，等於什麼都沒驗到。
            await js("""
              window.confirm=function(){return true;};
              (function(){
                var rows = document.querySelectorAll('#case-hist .case-row');
                for (var i=0;i<rows.length;i++){
                  if (rows[i].querySelector('.meta').textContent.indexOf('已結案') >= 0){
                    rows[i].querySelector('[data-del]').click(); return 'deleted closed one';
                  }
                }
                return 'NOT FOUND';
              })()
            """, awaitp=False)
            await asyncio.sleep(1.5)
            print("\n=== 刪除一件後 ===")
            print(json.dumps(await js("""
              (function(){
                return new Promise(function(res){
                  var idx = JSON.parse(localStorage.getItem('aa.cases.v1'));
                  var orphanKeys = Object.keys(localStorage).filter(function(k){
                    return k.indexOf('aa.case.') === 0 &&
                           !idx.list.some(function(c){ return 'aa.case.'+c.id === k; });
                  });
                  var r = indexedDB.open('aa-photos');
                  r.onsuccess = function(){
                    r.result.transaction('photos').objectStore('photos').getAll().onsuccess = function(e){
                      res({ caseCount: idx.list.length,
                            orphanPacks: orphanKeys,
                            photosLeft: e.target.result.length,
                            histRows: document.querySelectorAll('#case-hist .case-row').length });
                    };
                  };
                });
              })()
            """), ensure_ascii=False, indent=2))
    finally:
        proc.terminate()


asyncio.run(run())
