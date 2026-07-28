/* 事故救援助手 — service worker
   策略：app shell 一律 cache-first，確保車禍現場沒有網路時也能開啟。
   改版時把 VERSION 加一，舊快取會在 activate 時清掉。 */

var VERSION = 'aa-v5';
var SHELL = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png'
];

self.addEventListener('install', function(e){
  e.waitUntil(
    caches.open(VERSION).then(function(c){
      // 個別加入，單一檔案失敗不會讓整個安裝失敗
      return Promise.all(SHELL.map(function(u){
        return c.add(new Request(u, { cache:'reload' })).catch(function(){});
      }));
    }).then(function(){ return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function(e){
  e.waitUntil(
    caches.keys().then(function(keys){
      return Promise.all(keys.map(function(k){
        return k === VERSION ? null : caches.delete(k);
      }));
    }).then(function(){ return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function(e){
  var req = e.request;

  if (req.method !== 'GET') return;

  var url = new URL(req.url);

  // 跨網域（Nominatim 地址查詢、Google Maps、LINE）一律走網路，不快取
  if (url.origin !== self.location.origin) return;

  // 導覽請求：先看快取，離線時回落到 index.html
  if (req.mode === 'navigate'){
    e.respondWith(
      caches.match('./index.html').then(function(hit){
        return hit || fetch(req).catch(function(){ return caches.match('./'); });
      })
    );
    return;
  }

  // 其餘同源資源：cache-first，背景補回快取
  e.respondWith(
    caches.match(req).then(function(hit){
      if (hit) return hit;
      return fetch(req).then(function(res){
        if (res && res.ok && res.type === 'basic'){
          var copy = res.clone();
          caches.open(VERSION).then(function(c){ c.put(req, copy); });
        }
        return res;
      });
    })
  );
});
