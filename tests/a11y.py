#!/usr/bin/env python3
"""無障礙稽核：對比度、觸控面積、可存取名稱。

v54 之前這支只走五個分頁。問題是這個 App 有十一個覆蓋層（各種 sheet、
裁切屏、照片檢視、註冊登入四屏），**一個都沒被掃過** —— 而歷史上出過的
兩次問題都在那裡面（v34 的 .sheet-close 只有 40×38，v46 的裁切取景框）。
腳本沒報錯不等於沒問題，只等於它沒走到那裡。

現在每一個覆蓋層都會被打開來量，而且**淺色與深色各量一次** ——
對比度正是深色模式最容易破的地方。

輸出只印有問題的畫面，最後給一份總表。要看全部（包含乾淨的）加 -v。

用法：先在專案根目錄開 `python3 -m http.server 8899`，再跑這支。
"""
import asyncio, json, os, subprocess, sys, time, urllib.request, websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9481
ORIGIN = "http://127.0.0.1:8899"
IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture-avatar.jpg")
VERBOSE = "-v" in sys.argv

AUDIT = r"""
(function(ROOT){
  function lum(c){
    var m=c.match(/[\d.]+/g).map(Number);
    var f=m.slice(0,3).map(function(v){v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4);});
    return .2126*f[0]+.7152*f[1]+.0722*f[2];
  }
  function ratio(a,b){var l1=lum(a),l2=lum(b);return (Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);}
  function rgba(c){
    var m=(c||'').match(/[\d.]+/g);
    if(!m) return null;
    return [+m[0],+m[1],+m[2], m.length>3 ? +m[3] : 1];
  }
  /* 半透明的底要跟下層合成，不能當成不透明色。
     這個 App 的 --inset 是 rgba(255,255,255,.05) —— 只取前三個數字的話，
     深色卡片上那層 5% 白會被讀成純白，整批誤報成對比 1.9:1。 */
  function bgOf(el){
    var stack=[];
    while(el && el!==document.documentElement){
      var c=rgba(getComputedStyle(el).backgroundColor);
      if(c && c[3]>0){ stack.push(c); if(c[3]>=1) break; }
      el=el.parentElement;
    }
    if(!stack.length || stack[stack.length-1][3]<1){
      var b=rgba(getComputedStyle(document.body).backgroundColor);
      if(b && b[3]>0) stack.push(b);
    }
    if(!stack.length) return 'rgb(255,255,255)';
    // 由下往上合成
    var out=stack[stack.length-1].slice(0,3);
    for(var i=stack.length-2;i>=0;i--){
      var t=stack[i], a=t[3];
      out=[0,1,2].map(function(k){ return t[k]*a + out[k]*(1-a); });
    }
    return 'rgb('+out.map(function(v){return Math.round(v)}).join(', ')+')';
  }
  var contrast=[], small=[], noName=[];
  /* 只掃指定的根。覆蓋層打開時，底下那一頁在 DOM 裡仍然是 display:block ——
     不限範圍的話每一屏都會把整個 App 再量一次，重複幾百項，而且標籤會騙人。 */
  var scope = document.querySelector(ROOT);
  if (!scope) return JSON.stringify({找不到根:ROOT});
  scope.querySelectorAll('*').forEach(function(el){
    var cs=getComputedStyle(el), r=el.getBoundingClientRect();
    var visible = r.width>0 && r.height>0 && cs.visibility!=='hidden' && cs.display!=='none';
    if(!visible) return;
    // aria-hidden 的子樹是刻意不給輔助科技看的，量它只會製造雜訊
    if(el.closest('[aria-hidden="true"]')) return;

    // 只看直接含文字的葉節點
    var ownText = [].filter.call(el.childNodes,function(n){return n.nodeType===3 && n.textContent.trim();}).length>0;
    if(ownText){
      var size=parseFloat(cs.fontSize), w=cs.fontWeight;
      var large = size>=24 || (size>=18.66 && (w>=700||w==='bold'));
      var need = large?3:4.5;
      try{
        var cr=ratio(cs.color,bgOf(el));
        if(cr<need) contrast.push({t:el.textContent.trim().slice(0,22),s:size,r:+cr.toFixed(2),need:need,sel:el.className||el.tagName});
      }catch(e){}
    }

    // 可點擊元素的觸控面積
    var tag=el.tagName;
    if(tag==='BUTTON'||tag==='A'||tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT'){
      // 偽元素可以把可點區域撐大而不改變外觀（例如勾選框用 ::after{inset:-10px}）。
      // 只量元素本身會誤報 —— 量到的是視覺尺寸，不是實際可點範圍。
      var ew=r.width, eh=r.height;
      ['::after','::before'].forEach(function(pe){
        var p=getComputedStyle(el,pe);
        if(p.content==='none') return;
        var pw=parseFloat(p.width), ph=parseFloat(p.height);
        if(!isNaN(pw)) ew=Math.max(ew,pw);
        if(!isNaN(ph)) eh=Math.max(eh,ph);
      });
      if(ew<44||eh<44) small.push({tag:tag,id:el.id,cls:el.className,w:+ew.toFixed(1),h:+eh.toFixed(1),t:(el.textContent||'').trim().slice(0,14)});

      var lab = el.id ? document.querySelector('label[for="'+el.id+'"]') : null;
      var name=(el.textContent||'').trim()||el.getAttribute('aria-label')||
               el.getAttribute('title')||el.getAttribute('placeholder')||
               (el.getAttribute('aria-labelledby') ? 'labelledby' : '')||
               (lab ? lab.textContent.trim() : '');
      if(!name) noName.push({tag:tag,id:el.id,cls:el.className});
    }
  });
  return JSON.stringify({對比不足:contrast, 觸控過小:small, 沒有名稱:noName});
})(ROOT_SEL)
"""

# 讓各屏有東西可以量。空的表單量不出對比問題 —— 沒有文字就沒有前景色。
SEED = """
(function(){
  var id='a11y';
  localStorage.setItem('aa.cases.v1', JSON.stringify({cur:id, list:[
    {id:id, ts:Date.now(), closed:false},
    {id:id+'2', ts:Date.now()-86400000, closed:true}
  ]}));
  localStorage.setItem('aa.case.'+id, JSON.stringify({
    'aa.comp.v1':{med:'48250',rehab:'12000',trans:'3400',work:'86000',car:'157800',prop:'6900'},
    'aa.other.v1':{plate:'ABC-1234',name:'王小明',tel:'0912345678',insurer:'國泰產險'},
    'aa.site.v1':{lat:25.04776,lon:121.51706,at:Date.now(),addr:'臺北市中正區北平西路3號'}
  }));
  localStorage.setItem('aa.case.'+id+'2', JSON.stringify({}));
  localStorage.setItem('aa.me.v1', JSON.stringify({name:'陳大文',plate:'XYZ-5678',
    ins:'富邦產險',policy:'FB-2026-001234',ecName:'林小美',ecTel:'0987654321'}));
})()
"""

report = []      # (畫面, 主題, 分類, 內容)
screens = 0      # 掃過幾個畫面


async def main():
    p = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--user-data-dir=/tmp/cdp-a11y", "--hide-scrollbars", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        u = None
        for _ in range(80):
            try:
                t = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                q = [x for x in t if x["type"] == "page"]
                if q:
                    u = q[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            await asyncio.sleep(.25)

        async with websockets.connect(u, max_size=60 * 1024 * 1024) as ws:
            n = 0

            async def send(m, pr=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": m, "params": pr or {}}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == n:
                        return r

            async def ev(e):
                r = await send("Runtime.evaluate",
                               {"expression": e, "returnByValue": True, "awaitPromise": True})
                res = r.get("result", {}).get("result", {})
                if r.get("result", {}).get("exceptionDetails"):
                    return "ERR " + json.dumps(r["result"]["exceptionDetails"], ensure_ascii=False)[:160]
                return res.get("value")

            # 切主題會觸發 background/border 的過渡（最長的是 #loc-card 的 0.45s）。
            # 不處理的話量到的是動畫中途的顏色 —— 深色模式下會量到還沒變暗的白底，
            # 整批誤報成對比 1.9:1。等時間不可靠（改了 CSS 就要跟著改等待），
            # 直接把全站的過渡與動畫關掉：過渡只影響中間狀態，最終計算值一模一樣。
            FREEZE = ("(function(){if(document.getElementById('a11y-freeze'))return;"
                      "var s=document.createElement('style');s.id='a11y-freeze';"
                      "s.textContent='*,*::before,*::after{transition:none!important;"
                      "animation:none!important}';document.head.appendChild(s)})()")

            async def theme(t):
                await ev(FREEZE)
                await ev("document.documentElement.dataset.theme=%r" % t)
                await asyncio.sleep(.12)

            async def audit(label, root="body"):
                """同一個畫面淺色深色各量一次。開一次、量兩次，不必重跑動線。"""
                global screens
                screens += 1
                clean = True
                js = AUDIT.replace("ROOT_SEL", json.dumps(root))
                for th in ("light", "dark"):
                    await theme(th)
                    raw = await ev(js)
                    if not isinstance(raw, str) or raw.startswith("ERR"):
                        report.append((label, th, "稽核失敗", raw))
                        clean = False
                        continue
                    d = json.loads(raw)
                    if "找不到根" in d:
                        report.append((label, th, "找不到根", d["找不到根"]))
                        clean = False
                        continue
                    for k in ("對比不足", "觸控過小", "沒有名稱"):
                        if d[k]:
                            report.append((label, th, k, d[k]))
                            clean = False
                await theme("light")
                if VERBOSE and clean:
                    print("  乾淨　" + label)
                elif not clean:
                    print("  有問題　" + label)

            async def upload(selector):
                doc = await send("DOM.getDocument")
                root = doc["result"]["root"]["nodeId"]
                q = await send("DOM.querySelector", {"nodeId": root, "selector": selector})
                node = q["result"].get("nodeId")
                if not node:
                    return False
                await send("DOM.setFileInputFiles", {"nodeId": node, "files": [IMG]})
                # setFileInputFiles 不會觸發 change，自己補一個
                await ev("document.querySelector('%s')"
                         ".dispatchEvent(new Event('change',{bubbles:true}))" % selector)
                await asyncio.sleep(1.6)
                return True

            await send("Page.enable")
            await send("Runtime.enable")
            await send("DOM.enable")
            await send("Network.enable")
            # cache-first 的 service worker 不繞過的話，永遠稽核到上一版
            await send("Network.setBypassServiceWorker", {"bypass": True})
            await send("Network.setCacheDisabled", {"cacheDisabled": True})
            await send("Browser.grantPermissions",
                       {"origin": ORIGIN, "permissions": ["geolocation"]})
            await send("Emulation.setGeolocationOverride",
                       {"latitude": 25.0479, "longitude": 121.5171, "accuracy": 10})
            await send("Emulation.setDeviceMetricsOverride",
                       {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True})

            url = ORIGIN + "/index.html?a11y=%d" % int(time.time() * 1000)
            await send("Page.navigate", {"url": url})
            await asyncio.sleep(2.5)
            await ev(SEED)
            await send("Page.navigate", {"url": url})
            await asyncio.sleep(2.5)

            print("── 覆蓋層（過去從來沒有被掃過的部分）──")
            # 加入主畫面的提示是預設就在畫面上的，先量它再收起來
            await audit("加入主畫面 #install", "#install")
            await ev("document.getElementById('install').style.display='none'")

            print("\n── 五個分頁 ──")
            await ev("document.getElementById('loc-btn').click()")
            await asyncio.sleep(3)
            for i, name in enumerate(['現場', '存證', '出險', '求償', '個人']):
                await ev("document.querySelectorAll('.tab')[%d].click()" % i)
                await asyncio.sleep(.7)
                await audit(name, ".view.on")
            await audit("分頁列 .tabbar", ".tabbar")

            print("\n── 各個 sheet ──")
            steps = [
                # (標籤, 根, 開啟, 關閉)
                ("設定 #set-sheet", "#set-sheet",
                 "document.querySelector('.btn-settings').click()",
                 "document.getElementById('set-close').click()"),
                ("對方資料 #other-sheet", "#other-sheet",
                 "document.querySelectorAll('.tab')[0].click();"
                 "setTimeout(function(){document.getElementById('other-open').click()},250)",
                 "document.getElementById('other-close') && document.getElementById('other-close').click()"),
                ("引導模式 #sheet", "#sheet",
                 "document.querySelectorAll('.tab')[0].click();"
                 "setTimeout(function(){document.getElementById('guide-open').click()},250)",
                 "document.getElementById('sheet').classList.remove('open')"),
                ("出險詳情 #ins-sheet", "#ins-sheet",
                 "document.querySelectorAll('.tab')[2].click();"
                 "setTimeout(function(){document.querySelector('.ins').click()},250)",
                 "document.getElementById('ins-close').click()"),
                ("請求明細 #cdoc-sheet", "#cdoc-sheet",
                 "document.querySelectorAll('.tab')[3].click();"
                 "setTimeout(function(){document.getElementById('cdoc-open').click()},250)",
                 "document.getElementById('cdoc-close').click()"),
                ("個人資料 #me-sheet", "#me-sheet",
                 "document.querySelectorAll('.tab')[4].click();"
                 "setTimeout(function(){document.getElementById('prof-edit').click()},250)",
                 "document.getElementById('me-close').click()"),
                ("確認對話框 #ask", "#ask",
                 "document.querySelectorAll('.tab')[4].click();"
                 "setTimeout(function(){var b=document.querySelector('[data-del]');b&&b.click()},300)",
                 "document.getElementById('ask-no').click()"),
            ]
            for label, root, op, cl in steps:
                await ev(op)
                await asyncio.sleep(1.0)
                await audit(label, root)
                await ev(cl)
                await asyncio.sleep(.5)

            print("\n── 需要真的檔案的兩屏 ──")
            await ev("document.querySelectorAll('.tab')[4].click()")
            await asyncio.sleep(.5)
            if await upload("#av-picker"):
                await audit("裁切頭貼 #crop", "#crop")
                await ev("var b=document.getElementById('crop-cancel'); b && b.click()")
                await asyncio.sleep(.5)
            else:
                report.append(("裁切頭貼 #crop", "-", "無法開啟", "找不到 #av-picker"))

            await ev("document.querySelectorAll('.tab')[1].click()")
            await asyncio.sleep(.6)
            # picker 的 change 處理器會檢查 pickSlot，沒有先按「拍照」就直接 return
            await ev("document.querySelector('.view.on .shoot').click()")
            await asyncio.sleep(.4)
            if await upload("#picker"):
                await asyncio.sleep(1.5)
                opened = await ev(
                    "(function(){var t=document.querySelector('.view.on img[data-id]');"
                    "if(!t) return false; t.click(); return true})()")
                await asyncio.sleep(.8)
                if opened is True and await ev(
                        "document.getElementById('viewer').classList.contains('open')"):
                    await audit("照片檢視 #viewer", "#viewer")
                    await ev("document.getElementById('viewer').classList.remove('open')")
                else:
                    report.append(("照片檢視 #viewer", "-", "無法開啟", "照片縮圖點不開"))
            else:
                report.append(("照片檢視 #viewer", "-", "無法開啟", "找不到 #picker"))

            print("\n── 註冊／登入四屏 ──")
            await send("Page.navigate", {"url": ORIGIN + "/index.html?auth=1"})
            await asyncio.sleep(2.0)
            await ev("localStorage.removeItem('aa.registered.v1');"
                     "localStorage.removeItem('aa.role.v1')")
            await send("Page.navigate", {"url": ORIGIN + "/index.html"})
            await asyncio.sleep(2.5)
            if await ev("document.documentElement.getAttribute('data-auth')") == "need":
                await audit("歡迎屏 #auth-welcome", "#auth-welcome")
                await ev("document.querySelector('[data-go=up]').click()")
                await asyncio.sleep(.6)
                await audit("建立帳號 #auth-pane", "#auth-pane")
                await ev("document.getElementById('auth-switch-b').click()")
                await asyncio.sleep(.6)
                await audit("登入 #auth-pane", "#auth-pane")
                await ev("document.documentElement.setAttribute('data-auth','role')")
                await asyncio.sleep(.6)
                await audit("身分選擇 #auth-role", "#auth-role")
            else:
                report.append(("註冊／登入四屏", "-", "無法開啟", "?auth=1 沒有生效"))
    finally:
        p.terminate()

    print("\n" + "=" * 56)
    if not report:
        print("全部乾淨（%d 個畫面 × 淺深兩色）" % screens)
        return
    for label, th, kind, data in report:
        print("\n▼ %s（%s）— %s" % (label, th, kind))
        print(json.dumps(data, ensure_ascii=False, indent=1)[:1800])
    print("\n" + "=" * 56)
    print("掃了 %d 個畫面 × 淺深兩色，共 %d 項問題，分布在 %d 個畫面：" % (
        screens, len(report), len({r[0] for r in report})))
    for lab in dict.fromkeys(r[0] for r in report):
        kinds = "、".join(dict.fromkeys(r[2] for r in report if r[0] == lab))
        print("  " + lab + " — " + kinds)


asyncio.run(main())
