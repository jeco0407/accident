# 車禍緊急助手

事故現場的處理助手。定位、報案、拍照存證、出險流程，一步一步帶著走。

純 HTML/CSS/JS，**沒有框架、沒有 build step、沒有後端**。核心功能（定位、撥號、現場流程、拍照清單、出險專線）在完全離線的情況下都能使用 —— 車禍現場常常沒有訊號，這是設計上的第一原則。

## 部署

整包是靜態檔案，Vercel 匯入這個 repo 即可，不需要任何建置設定：

- Framework Preset：**Other**
- Build Command：留空
- Output Directory：留空（根目錄）

`vercel.json` 已經設好快取標頭 —— 重點是 `sw.js` 與 `index.html` 必須每次重新驗證，否則使用者會永遠停在舊版。

## 設定你的資訊

打開 `index.html`，找到 JS 最上方的 `CONFIG`（搜尋「部署設定」），改這七行就好：

```js
var CONFIG = {
  agentLine:  'https://line.me/R/ti/p/@PLACEHOLDER',  // 你的 LINE（必填）
  agentName:  '',   // 例：'王小明'，留空顯示「聯繫你的業務員」
  agentOrg:   '',   // 例：'○○產物保險'，顯示在頁尾
  agentSay:   '',   // 例：'我陪你完成後續理賠。'
  agentTel:   '',   // 填了才會多一顆電話按鈕
  towTel:     '',   // 道路救援，填了才會出現該按鈕
  aiLine:     ''    // 專屬 AI bot LINE，留空則整個 AI 區塊隱藏
};
```

留空的項目會自動隱藏，不會留下空按鈕或死連結。

每位業務員部署自己的一份，改這裡就好。換電話或換 LINE 就改設定重新部署，使用者下次開啟就是新的。

## 出險專線清單

在 `index.html` 的 `INSURERS` 陣列：

```js
{ n:'富邦產險', tel:'0800-009-888', note:'' },
```

`note` 是選填的補充說明，填了會顯示在該公司的詳情頁。顯示用的號碼保留連字號，撥號時程式會自動去掉。

> 號碼可能異動，上線前與定期都建議重新查證。

## 改版後一定要做的事

**修改任何檔案後，把 `sw.js` 最上面的 `VERSION` 加一。**

```js
var VERSION = 'aa-v4';   // → 'aa-v5'
```

service worker 採 cache-first，版號沒變的話舊快取不會被清掉，已經安裝的使用者會一直看到舊版本。這是唯一一個漏掉就會出事的步驟。

## 檔案結構

```
index.html      主程式，CSS 與 JS 全部內嵌
manifest.json   PWA manifest
sw.js           service worker，cache-first 快取 app shell
vercel.json     快取標頭設定
icons/          192 / 512 / maskable 512
```

## 免責

App 提供的是一般性事故處理資訊，不構成法律或理賠承諾。實際權益依保單條款與主管機關規定為準。
