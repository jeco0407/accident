# Guardy

車禍緊急助手。

事故現場的處理助手。定位、報案、拍照存證、出險流程，一步一步帶著走。

純 HTML/CSS/JS，**沒有框架、沒有 build step、沒有後端**。核心功能（定位、撥號、現場流程、拍照清單、出險專線）在完全離線的情況下都能使用 —— 車禍現場常常沒有訊號，這是設計上的第一原則。

- [DEVLOG.md](DEVLOG.md) —— 開發歷程、重大決策與被推翻的方向
- [ROADMAP.md](ROADMAP.md) —— 待辦、優化與未解的問題
- [ARCHITECTURE.md](ARCHITECTURE.md) —— 帳號制與雲端同步的架構設計（設計中，尚未實作）

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

## 位置

定位後把座標與時間寫進 localStorage（`aa.site.v1`），開啟時復原。**沒有背景定位** —— 只有使用者主動按「重新定位」才會取代，按「關閉」則清除。

卡片上只有一行位置資訊：有地址顯示地址，離線或查詢失敗就退回座標。**離線時不能留白** —— 現場沒訊號是常態，而唸座標給接線員正是這個 App 最核心的用途。

定位失敗會自動展開手動輸入（地下停車場、隧道、室內定位不到是常態）。手動輸入的地點沒有座標，此時地圖改用地址查詢、分享文字省略座標。

地址用 Nominatim 的**結構化欄位**組（縣市 → 鄉鎮市區 → 路 → 號），不是反轉 `display_name`。台灣的欄位對應不直覺：

- 直轄市的「區」在 `suburb`，縣的「鄉鎮」在 `town`
- `city_district` 在直轄市是「里」、在縣是「村」，兩者都是雜訊
- `house_number` 格式不一致：台北回純數字 `"3"`，高雄回完整門牌 `"115號"`。補「號」前要先檢查結尾

地址只查一次，存進位置裡。

## 存證資料存在哪裡

- **位置與時間**：localStorage
- **對方資料、求償金額、各清單進度**：localStorage
- **照片**：IndexedDB，儲存前縮到長邊 2048、JPEG 品質 0.85（原圖動輒 4MB，縮完約 300–500KB，且仍足以辨識車牌）
- 第一次存照片時會呼叫 `navigator.storage.persist()`，降低瀏覽器清空儲存的機率

目前**只存在使用者自己的手機裡，不會上傳任何地方**。也因此它們會隨「清除瀏覽器資料」一起消失 —— App 內有提示使用者用「分享」把照片再備份一份到相簿。

## 出險專線清單

在 `index.html` 的 `INSURERS` 陣列：

```js
{ n:'富邦產險', tel:'0800-009-888', note:'' },
```

`note` 是選填的補充說明，填了會顯示在該公司的詳情頁。顯示用的號碼保留連字號，撥號時程式會自動去掉。

> 號碼可能異動，上線前與定期都建議重新查證。

## 主題

淺色與深色的差異全部收在 CSS 變數裡（`:root` 與 `:root[data-theme="dark"]`），元件本身不寫死顏色。要調色只改變數即可。

預設跟隨系統，使用者可在「我的 → 外觀」手動指定。判斷主題的腳本刻意放在 `<style>` 之後、`</head>` 之前，必須在首次繪製前執行，否則深色使用者會看到一閃的白畫面。

## 改版後一定要做的事

**修改任何檔案後，把 `sw.js` 最上面的 `VERSION` 加一。**

```js
var VERSION = 'aa-v4';   // → 'aa-v5'
```

service worker 採 cache-first，版號沒變的話舊快取不會被清掉，已經安裝的使用者會一直看到舊版本。這是唯一一個漏掉就會出事的步驟。

## 上架商店

### 已經備好的

- `privacy.html` — 隱私權政策。**兩邊商店都強制要求一個公開網址**，App 內「我的 → 關於」也有入口。上架前務必把裡面的 `PLACEHOLDER_EMAIL` 換成真實聯絡信箱
- `manifest.json` — 已有 `id`、`description`、`categories`、`screenshots`、`shortcuts`，Bubblewrap 與 PWABuilder 需要的欄位都齊了
- `screenshots/` — 1080×1920，manifest 與商店列表共用。**不放進 service worker 快取**，那會為了離線用不到的東西多塞 1MB

### Google Play：可行，用 TWA

用 [Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap) 或 PWABuilder 把這個 PWA 包成 Trusted Web Activity。順序：

1. 綁自己的網域並上 HTTPS（TWA 的網域驗證不能用 `*.vercel.app`）
2. `bubblewrap init --manifest https://你的網域/manifest.json`
3. 把它產生的簽章 SHA-256 指紋寫進 `/.well-known/assetlinks.json` 並部署。**指紋沒對上，App 開起來會多一條網址列**，這是最常見的失敗點
4. Play Console 開發者帳號（一次性 25 美元）、填 Data safety 表單、內容分級

Data safety 照實填即可：不蒐集、不分享任何資料。唯一要揭露的是查詢地址時會把座標送給 OpenStreetMap。

### App Store：有實質的被拒風險

Apple 的審查指南 **4.2 Minimum Functionality** 明文排除「把網站包起來」的 App。純 WKWebView 殼被拒是常態，要過審通常得補上網頁做不到的原生能力。上架前先評估這件事值不值得，不要先付了 99 美元年費才發現。

Google Play 也有類似條款，但對 TWA 的容忍度高很多，因為 TWA 本身就是 Google 推的方案。

### 上架前還要處理

- **Vercel Hobby 方案禁止商業用途**，若這個 App 會帶來任何商業利益，要升級到 Pro
- 10 支出險專線重新查證一次
- 換掉隱私權政策裡的聯絡信箱

## 檔案結構

```
index.html      主程式，CSS 與 JS 全部內嵌
privacy.html    隱私權政策（商店上架必要）
manifest.json   PWA manifest
sw.js           service worker，cache-first 快取 app shell
vercel.json     快取標頭設定
icons/          192 / 512 / maskable 512
screenshots/    商店列表與 manifest 用，1080×1920
```

> 規劃中的帳號制會改變上面幾項：文字資料將同步到雲端，**照片仍然不上傳**。見 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 免責

App 提供的是一般性事故處理資訊，不構成法律或理賠承諾。實際權益依保單條款與主管機關規定為準。
