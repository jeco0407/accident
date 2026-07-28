# 車禍緊急助手

事故現場的處理助手。定位、報案、拍照存證、出險流程，一步一步帶著走。

純 HTML/CSS/JS，**沒有框架、沒有 build step、沒有後端**。核心功能（定位、撥號、現場流程、拍照清單、出險專線）在完全離線的情況下都能使用 —— 車禍現場常常沒有訊號，這是設計上的第一原則。

## 部署

整包是靜態檔案，Vercel 匯入這個 repo 即可，不需要任何建置設定：

- Framework Preset：**Other**
- Build Command：留空
- Output Directory：留空（根目錄）

`vercel.json` 已經設好快取標頭 —— 重點是 `sw.js` 與 `index.html` 必須每次重新驗證，否則使用者會永遠停在舊版。

## 設定

打開 `index.html`，找到 JS 最上方的 `CONFIG`（搜尋「部署設定」）：

```js
var CONFIG = {
  towTel: ''   // 道路救援電話。留空則「現場」分頁不顯示該按鈕
};
```

聯絡業務員的功能目前已移除，待多租戶架構確定後再接回。文案中提到業務員的地方統一走 `who()` 這個函式，屆時只需改它，UI 不必變動。

## 存證資料存在哪裡

- **對方資料**：localStorage
- **照片**：IndexedDB，儲存前縮到長邊 2048、JPEG 品質 0.85（原圖動輒 4MB，縮完約 300–500KB，且仍足以辨識車牌）
- 第一次存照片時會呼叫 `navigator.storage.persist()`，降低瀏覽器清空儲存的機率

兩者都**只存在使用者自己的手機裡，不會上傳任何地方**。也因此它們會隨「清除瀏覽器資料」一起消失 —— App 內有提示使用者用「分享」把照片再備份一份到相簿。

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
