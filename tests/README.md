# 測試腳本

不是自動化測試套件（見 ROADMAP 5.2），是**驗證用的腳本**：改到相關的地方時手動重跑。

全部靠 Chrome DevTools Protocol 驅動 headless Chrome，**用真實牆鐘時間**。不要改用 `--virtual-time-budget` —— 它會快轉 `setTimeout`，但真實的圖片解碼 I/O 根本還沒完成，製造出「卡在處理中」這種假失敗。

## 先起一個伺服器

```sh
cd 專案根目錄
python3 -m http.server 8899
```

**一定要從專案根目錄起。** 從別的目錄起會拿到 404 頁面，而那個頁面沒有 viewport meta，Chrome 會回報 `innerWidth: 980`，看起來很像裝置模擬壞掉。

## 腳本

| 檔案 | 用途 |
|---|---|
| `cdp.py` | 通用驅動：`cdp.py <url> <等待秒數> <JS 運算式>`。`SHOT:路徑\|\|\|前置JS` 可截圖 |
| `test_cases.py` | 事故案件：舊資料遷移、案件隔離、切換、結案、刪除時照片一起走 |
| `test_delete_trace.py` | 刪除案件的三條路徑，每一步同時比對畫面／記憶體索引／localStorage，並各自重新載入再驗一次 |
| `test_auth.py` | M1 帳號骨架：旗標、驗證、**真實離線重開十次**、開啟時零對外請求 |
| `test_role.py` | 身分（一般／業務員）：閘門順序、離線不再問、登出一起清，外加**靜態檢查 role 沒有變成權限** |
| `test_avatar.py` | 頭貼：走真實 `<input type=file>` 上傳、**裁切屏的夾限（拖不出黑邊）**、取消不留痕跡、塞滿圓框、重開仍在、**不出現在會同步的資料裡**、移除 |
| `test_sync.py` | M3 同步：攔截 fetch 驗 LWW、墓碑、照片不外流、失敗靜默 |
| `a11y.py` | 無障礙稽核：五個分頁的對比度與觸控面積，實際量測而非目測 |

需要 `websockets`：`pip3 install websockets`。

## 兩個會浪費時間的坑

**service worker 會送舊快取。** 改了 CSS 卻沒生效多半是這個，不是你改錯了。網址加 `?bust=1` 之類的 query 就會繞過。

**在 `index.html` 上呼叫 `deleteDatabase` 會卡死。** 頁面本身開著 IndexedDB 連線，觸發的是 `onblocked` 而不是 `onsuccess`。要清 DB 就到同源但不載入 App 的頁面上做（例如 `manifest.json`）。

**不要用 `| tail` 看還在跑的腳本。** `tail` 會把輸出全部憋到程式結束才吐 —— 卡住的程式看起來就像完全沒有輸出，會把你引到錯誤的方向。導到檔案再讀。

## 離線測試的兩個陷阱

**CDP 的 `Network.emulateNetworkConditions` 會在每次導覽後被重置。** 只在開頭設一次，之後整段都是在連線狀態下跑的 —— 測試會全過，而且看不出破綻。每次 `Page.navigate` 之後要重新套用，並逐次確認 `navigator.onLine === false`。

**離線測試不能用帶 query 的網址。** service worker 是 cache-first、按**完整網址**比對，`index.html?t=123` 讀不到 `index.html` 的快取，真的離線時連頁面都載不進來。要測離線就用乾淨網址（`?auth=1` 這類開關已改成寫進 localStorage，就是為了這件事）。

## 假回應要跨導覽存活

`test_sync.py` 用 `Page.addScriptToEvaluateOnNewDocument` 換掉 `window.fetch`。這段腳本**每次導覽都會重跑**，所以假回應不能放在 `window` 上 —— 一重新載入就被重設成空的，測試會變成「什麼都沒拉到」而假通過。放進 localStorage。

## 塞檔案給 `<input type=file>`

用 CDP 的 `DOM.setFileInputFiles`，不要在 JS 裡造 `DataTransfer` —— 後者在部分 Chrome 版本上 `files` 是唯讀的，而且測到的不是使用者真正走的那段程式碼。

**`setFileInputFiles` 不會觸發 `change`**，要自己補一個 `dispatchEvent(new Event('change',{bubbles:true}))`，否則什麼都不會發生。

## 量還沒顯示的東西，量到的是 0

`display:none` 的元素 `getBoundingClientRect()` 全是 0。v46 的裁切取景框因此永遠掉到 200px 的下限 —— 程式在 `.crop` 還沒加上 `.open` 之前就去量 `.crop-stage` 的高度。**先開屏再量。**

這種錯不會壞掉、不會報錯，只會安靜地一直用 fallback 值，所以測試要斷言「大於 fallback」而不只是「有值」。

## 兩個量錯的方式

**整個 App 包在一個 IIFE 裡。** `openSettings()`、`myRole()` 這些函式**都不是全域的**，`Runtime.evaluate` 拿不到，會得到 ReferenceError。測試只能走真實路徑（按齒輪、按按鈕），這本來就比較好 —— 但第一次撞到時很容易誤判成「功能壞了」。

**有 transition 的屬性不能點完馬上量。** `.role-opt` 的 background 與 border-color 有 120ms 過渡，click 之後同一個 tick 讀 `getComputedStyle`，拿到的是**動畫起點**，也就是還沒選中的顏色。看起來就像 CSS 規則沒生效 —— 我為此去翻了特異性、`!important`、UA 樣式，全都不是。量之前先 `setTimeout` 個 300～500ms。同一張卡上沒有宣告 transition 的 `.tick` 當下就正確，那個不一致就是線索。

## 稽核的盲點

`a11y.py` 只走五個**分頁**，不會打開 sheet（設定、引導模式、對方資料、出險詳情）。v34 就是在手動量設定視窗時，才發現共用的 `.sheet-close` 只有 40×38。**腳本沒報錯不等於沒問題，只等於它沒走到那裡。**

## 確認對話框

App 從 v30 起不用瀏覽器的 `confirm()`（在 PWA 殼裡可能被無聲吃掉），改用自己畫的 `#ask`。所以**覆寫 `window.confirm` 已經沒有作用**，測試要改按 `#ask-yes`：`test_cases.py` 裡的 `confirming()` 就是做這件事。

如果哪天又要測真的 `confirm()`：它會**凍住 renderer**，`Runtime.evaluate` 的回應要等對話框被處理才回來。`await` 它就是死鎖，必須 fire-and-forget 之後再去處理對話框。
