import asyncio, json, subprocess, time, urllib.request, websockets
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9481; ORIGIN="http://127.0.0.1:8899"

AUDIT = r"""
(function(){
  function lum(c){
    var m=c.match(/[\d.]+/g).map(Number);
    var f=m.slice(0,3).map(function(v){v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4);});
    return .2126*f[0]+.7152*f[1]+.0722*f[2];
  }
  function ratio(a,b){var l1=lum(a),l2=lum(b);return (Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);}
  function bgOf(el){
    while(el && el!==document.documentElement){
      var b=getComputedStyle(el).backgroundColor;
      if(b && !/rgba\(0, 0, 0, 0\)|transparent/.test(b)) return b;
      el=el.parentElement;
    }
    return getComputedStyle(document.body).backgroundColor;
  }
  var contrast=[], small=[], noName=[];
  document.querySelectorAll('*').forEach(function(el){
    var cs=getComputedStyle(el), r=el.getBoundingClientRect();
    var visible = r.width>0 && r.height>0 && cs.visibility!=='hidden' && cs.display!=='none';
    if(!visible) return;

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
        var ps=getComputedStyle(el,pe);
        if(!ps || ps.content==='none') return;
        function px(v){ var n=parseFloat(v); return isNaN(n)?0:n; }
        var grow = -(px(ps.top)+px(ps.bottom));
        var growX = -(px(ps.left)+px(ps.right));
        if(ps.position==='absolute'){
          if(grow>0) eh=Math.max(eh, r.height+grow);
          if(growX>0) ew=Math.max(ew, r.width+growX);
        }
      });
      if(eh<44||ew<44) small.push({t:(el.textContent||el.getAttribute('aria-label')||el.id||tag).trim().slice(0,22),w:Math.round(ew),h:Math.round(eh)});

      // label[for] 也是合法的可讀名稱，別漏了它
      var lab = el.id ? document.querySelector('label[for="'+el.id+'"]') : null;
      var name=(el.textContent||'').trim()||el.getAttribute('aria-label')||
               el.getAttribute('title')||el.getAttribute('placeholder')||
               (el.getAttribute('aria-labelledby') ? 'labelledby' : '')||
               (lab ? lab.textContent.trim() : '');
      if(!name) noName.push({tag:tag,id:el.id,cls:el.className});
    }
  });
  return JSON.stringify({對比不足:contrast, 觸控過小:small, 沒有名稱:noName}, null, 1);
})()
"""

async def main():
    p=subprocess.Popen([CHROME,"--headless=new","--disable-gpu",f"--remote-debugging-port={PORT}",
        "--no-first-run","--user-data-dir=/tmp/cdp-a11y","--hide-scrollbars","about:blank"],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        u=None
        for _ in range(80):
            try:
                t=json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                q=[x for x in t if x["type"]=="page"]
                if q: u=q[0]["webSocketDebuggerUrl"]; break
            except Exception: pass
            await asyncio.sleep(.25)
        async with websockets.connect(u,max_size=60*1024*1024) as ws:
            n=0
            async def send(m,pr=None):
                nonlocal n; n+=1
                await ws.send(json.dumps({"id":n,"method":m,"params":pr or {}}))
                while True:
                    r=json.loads(await ws.recv())
                    if r.get("id")==n: return r
            async def ev(e):
                r=await send("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
                res=r.get("result",{}).get("result",{})
                return res.get("value", "ERR "+json.dumps(res,ensure_ascii=False)[:200])
            await send("Page.enable"); await send("Runtime.enable")
            await send("Browser.grantPermissions",{"origin":ORIGIN,"permissions":["geolocation"]})
            await send("Emulation.setGeolocationOverride",{"latitude":25.0479,"longitude":121.5171,"accuracy":10})
            await send("Emulation.setDeviceMetricsOverride",{"width":390,"height":844,"deviceScaleFactor":2,"mobile":True})
            await send("Page.navigate",{"url":ORIGIN+"/index.html?a11y=%d" % int(time.time()*1000)})
            await asyncio.sleep(2.5)
            await ev("document.getElementById('install').style.display='none';document.getElementById('loc-btn').click()")
            await asyncio.sleep(3)
            for i,name in enumerate(['現場','存證','出險','求償','我的']):
                await ev(f"document.querySelectorAll('.tab')[{i}].click()")
                await asyncio.sleep(.7)
                print('─'*8, name, '─'*8)
                print(await ev(AUDIT))
    finally: p.terminate()
asyncio.run(main())
