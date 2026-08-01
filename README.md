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

**綁定業務員的功能已於 v43 取消**（理由見 [DEVLOG](DEVLOG.md#被推翻的方向)）。文案中提到業務員的地方統一走 `who()`，但它指的是「使用者自己保單上的那位業務員」—— Guardy 不知道、也不會去問你的業務員是誰。

登入後會問一次身分（一般使用者／保險業務員）。**那是使用者自述、未經驗證的，只影響介面，不帶任何資料權限。**

## 位置

定位後把座標與時間寫進 localStorage（`aa.site.v1`），開啟時復原。**沒有背景定位** —— 只有使用者主動按「重新定位」才會取代，按「關閉」則清除。

卡片上只有一行位置資訊：有地址顯示地址，離線或查詢失敗就退回座標。**離線時不能留白** —— 現場沒訊號是常態，而唸座標給接線員正是這個 App 最核心的用途。

定位失敗會自動展開手動輸入（地下停車場、隧道、室內定位不到是常態）。手動輸入的地點沒有座標，此時地圖改用地址查詢、分享文字省略座標。

地址用 Nominatim 的**結構化欄位**組（縣市 → 鄉鎮市區 → 路 → 號），不是反轉 `display_name`。台灣的欄位對應不直覺：

- 直轄市的「區」在 `suburb`，縣的「鄉鎮」在 `town`
- `city_district` 在直轄市是「里」、在縣是「村」，兩者都是雜訊
- `house_number` 格式不一致：台北回純數字 `"3"`，高雄回完整門牌 `"115號"`。補「號」前要先檢查結尾

地址只查一次，存進位置裡。

## 帳號（M2，預設關閉）

註冊／登入接 Supabase Auth，**直接 `fetch` 打 `/auth/v1/*`，不使用 supabase-js** —— 離線優先、沒有 build step，只為四個 POST 引入 SDK 不划算。專案 URL 與 anon key 在 `index.html` 的 `SUPA`。

> anon key 寫在前端是**設計如此**，安全性完全靠 RLS。不能外流的是 `service_role`，這個專案不使用它。

目前預設關閉：head 腳本裡 `var ON = false`。網址加 `?auth=1` 開啟預覽（會記在本機，`?auth=0` 關掉）。開啟前必須先在 Supabase 後台依序執行 `supabase/001_profiles.sql`、`002_incidents.sql`、`003_role.sql`。

開啟流程**只讀本機旗標 `aa.registered.v1`**，不呼叫任何線上檢查 —— 寫成「先查 session 再決定要不要顯示登入頁」，離線時會卡住。token 過期、續期失敗、離線都不清旗標；只有主動登出才清。

## 事故案件

一次事故 = 一個案件。索引在 `aa.cases.v1`（`{ cur, list:[{id,ts,closed}] }`），案件內容各自存在 `aa.case.<id>`，照片以 IndexedDB 的 `case` 索引區分。

`load()` 與 `save()` 讀寫的是**目前案件**那一包，所以三十幾處呼叫端不必知道案件的存在。只有 `aa.install.dismissed.v1` 與主題設定是跨案件的，列在 `GLOBAL_KEYS` 裡。

在「個人 → 事故案件」切換、結案、刪除。**一件一張卡**，標題是日期（地址可能是空的、可能很長，日期永遠有值），摘要行的地區／照片張數／進度都是即時算出來的。照片張數用 IndexedDB 的 `index('case').count()`，不要用 `getAll().length` —— 後者會把所有 ArrayBuffer 讀進記憶體只為了數幾張。所有案件排成一張列表，目前這件在列表裡以勾選標記與左緣色條標示 —— **切換造成的變化必須發生在使用者正在看的地方**，否則點下去像是什麼都沒發生。結案不會刪任何東西，只是標記並自動開一件新的。任何一件都能刪，包括目前這件與唯一那一件。App 內部隨時握著一個案件（所有分頁都要有東西可以讀寫），但**那是實作需求，不該讓使用者看到** —— 只剩一件而且是空的時候，列表顯示的是空白狀態，不是一列「未記錄地點」。

> 舊版（v26 以前）的資料會在第一次開啟時自動收成第一個案件。**舊 key 刻意保留不刪**，留一條退版的路。

## 存證資料存在哪裡

- **位置與時間**：localStorage
- **對方資料、求償金額、各清單進度**：localStorage
- **照片**：IndexedDB，儲存前縮到長邊 2048、JPEG 品質 0.85（原圖動輒 4MB，縮完約 300–500KB，且仍足以辨識車牌）
- **頭貼**：localStorage（`aa.avatar.v1`），256×256、JPEG 0.82，約 4KB。**刻意不用 IndexedDB** —— 只有一張又小，走 localStorage 才能同步讀到，進頁面不會先閃一個佔位圖再換成照片。上傳後一律進裁切屏（圓形取景框、拖曳、雙指或滑桿縮放），不自動置中裁 —— 自動裁在人臉上幾乎一定是錯的
- **我的資料**（姓名、車牌、保險公司、保單號碼、緊急聯絡人）：localStorage（`aa.me.v1`）。跟頭貼一樣列在 `GLOBAL_KEYS` —— 它們屬於「這個人」而不是「這次事故」，開新案件不該被清掉
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

品牌色是綠松色。**設計稿給的 `#2B9D96` 只能當裝飾** —— 白字在它上面只有 3.30:1，按鈕文字過不了 AA。實際用的是壓深一階的 `#237F79`（`--brand`），原色留在 `--brand-lite` 給插圖。

110 的紅與 119 的琥珀是**語意色，不跟著品牌走**。


淺色與深色的差異全部收在 CSS 變數裡（`:root` 與 `:root[data-theme="dark"]`），元件本身不寫死顏色。要調色只改變數即可。

預設跟隨系統，使用者可在「個人 → 外觀」手動指定。判斷主題的腳本刻意放在 `<style>` 之後、`</head>` 之前，必須在首次繪製前執行，否則深色使用者會看到一閃的白畫面。

## 改版後一定要做的事

**修改任何檔案後，把 `sw.js` 最上面的 `VERSION` 加一。**

```js
var VERSION = 'aa-v4';   // → 'aa-v5'
```

service worker 採 cache-first，版號沒變的話舊快取不會被清掉，已經安裝的使用者會一直看到舊版本。這是唯一一個漏掉就會出事的步驟。

## 上架商店

### 已經備好的

- `privacy.html` — 隱私權政策。**兩邊商店都強制要求一個公開網址**，App 內設定視窗也有入口。聯絡信箱已填 `getnabor@gmail.com`（`terms.html` 同一個）
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

## 檔案結構

```
index.html      主程式，CSS 與 JS 全部內嵌
assets/         歡迎頁插畫 guardy-hero.png（920×1380／1.2MB，在 SW shell 裡）
privacy.html    隱私權政策（商店上架必要）
terms.html      服務條款
supabase/       資料庫 schema 與 RLS，在 Supabase 後台依序執行
manifest.json   PWA manifest
sw.js           service worker，cache-first 快取 app shell
vercel.json     快取標頭設定
icons/          192 / 512 / maskable 512
screenshots/    商店列表與 manifest 用，1080×1920
tests/          CDP 驗證腳本（手動重跑，見 tests/README.md）
```

> 規劃中的帳號制會改變上面幾項：文字資料將同步到雲端，**照片仍然不上傳**。見 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 免責

App 提供的是一般性事故處理資訊，不構成法律或理賠承諾。實際權益依保單條款與主管機關規定為準。
