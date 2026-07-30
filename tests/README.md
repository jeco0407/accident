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
| `a11y.py` | 無障礙稽核：五個分頁的對比度與觸控面積，實際量測而非目測 |

需要 `websockets`：`pip3 install websockets`。

## 兩個會浪費時間的坑

**service worker 會送舊快取。** 改了 CSS 卻沒生效多半是這個，不是你改錯了。網址加 `?bust=1` 之類的 query 就會繞過。

**在 `index.html` 上呼叫 `deleteDatabase` 會卡死。** 頁面本身開著 IndexedDB 連線，觸發的是 `onblocked` 而不是 `onsuccess`。要清 DB 就到同源但不載入 App 的頁面上做（例如 `manifest.json`）。

**不要用 `| tail` 看還在跑的腳本。** `tail` 會把輸出全部憋到程式結束才吐 —— 卡住的程式看起來就像完全沒有輸出，會把你引到錯誤的方向。導到檔案再讀。

## 稽核的盲點

`a11y.py` 只走五個**分頁**，不會打開 sheet（設定、引導模式、對方資料、出險詳情）。v34 就是在手動量設定視窗時，才發現共用的 `.sheet-close` 只有 40×38。**腳本沒報錯不等於沒問題，只等於它沒走到那裡。**

## 確認對話框

App 從 v30 起不用瀏覽器的 `confirm()`（在 PWA 殼裡可能被無聲吃掉），改用自己畫的 `#ask`。所以**覆寫 `window.confirm` 已經沒有作用**，測試要改按 `#ask-yes`：`test_cases.py` 裡的 `confirming()` 就是做這件事。

如果哪天又要測真的 `confirm()`：它會**凍住 renderer**，`Runtime.evaluate` 的回應要等對話框被處理才回來。`await` 它就是死鎖，必須 fire-and-forget 之後再去處理對話框。
