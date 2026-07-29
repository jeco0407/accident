# Guardy 帳號架構設計

從「純本機、無後端」轉為「帳號制 + 雲端同步」的設計文件。寫在動工之前，因為這一步改錯的成本最高。

> 狀態：**設計中，尚未實作。** 目前線上版本仍是純本機的 v21。

---

## 目錄

- [一、決策前提](#一決策前提)
- [二、離線鐵則](#二離線鐵則)
- [三、系統組成](#三系統組成)
- [四、資料模型](#四資料模型)
- [五、權限規則](#五權限規則)
- [六、登入與 session](#六登入與-session)
- [七、同步策略](#七同步策略)
- [八、業務員綁定](#八業務員綁定)
- [九、訂閱與金流](#九訂閱與金流)
- [十、既有資料的遷移](#十既有資料的遷移)
- [十一、法遵與文件變更](#十一法遵與文件變更)
- [十二、實作階段](#十二實作階段)
- [十三、風險](#十三風險)

---

## 一、決策前提

已拍板的四件事：

| 決策 | 內容 |
|---|---|
| **註冊是強制的** | 一般客戶必須註冊才能使用 |
| **照片不上雲** | 只同步文字資料，照片留在裝置的 IndexedDB |
| **帳號要支援三件事** | 綁定業務員、跨裝置同步、收費與權限 |
| **技術選型** | Supabase（Postgres + Auth + RLS） |

### 為什麼強制註冊不會毀掉離線優先

原本的疑慮是「事故現場沒訊號，登入頁會把人擋在外面」。但這個疑慮有一個前提錯誤：

> **使用者不可能在沒有網路的情況下「下載」這個 App。能把它裝起來，當下就有網路可以註冊。**

所以註冊發生的時間點幾乎必然是「在家裡、有 Wi-Fi、還沒出事」的時候。真正出事那一刻，App 早就是登入狀態了。

剩下的風險只有一種：**已註冊的使用者，在離線時被系統踢出登入狀態。** 那才是要嚴防的事，見下一節。

---

## 二、離線鐵則

**這一節的每一條都不可協商。違反任何一條，都等於讓人在事故現場打不開 App。**

1. **登入狀態存本機，離線時絕不失效。** token 過期不等於登出。續期失敗就沉默重試，不跳登入頁。
2. **「曾經註冊過」是一個本機旗標。** 一旦為真，App 永遠正常開啟，不再檢查任何線上狀態。
3. **現場、存證、出險、110／119 不得依賴任何網路請求。** 這四項的程式路徑裡不能出現 `await` 任何 API。
4. **同步失敗一律靜默。** 最多在「我的」頁顯示「上次同步：⋯」，絕不用錯誤對話框打斷使用者。
5. **訂閱狀態過期不影響核心功能。** 付費的是業務員，不是事故當事人。客戶端不因任何權限問題降級。

實作上的具體要求：

```js
// Supabase client 初始化
createClient(URL, ANON_KEY, {
  auth: {
    persistSession: true,        // session 寫進 localStorage
    autoRefreshToken: true,
    detectSessionInUrl: false
  }
});

// App 開啟時的判斷 —— 只看本機旗標，不等待網路
var registered = localStorage.getItem('aa.registered.v1') === '1';
if (!registered) showAuthScreen();
else bootApp();                  // 不管有沒有網路、token 是否過期
```

**絕對不要寫成**「先 `getSession()` 再決定要不要顯示登入頁」—— 那在離線時會卡住或失敗。

---

## 三、系統組成

三個獨立的東西，不要混在一起：

| 元件 | 使用者 | 形態 | 部署 |
|---|---|---|---|
| **消費者 App** | 事故當事人 | 現有 PWA + 帳號層 | Vercel |
| **業務員後台** | 保險業務員 | 網頁（另一個獨立頁面／子網域） | Vercel |
| **後端** | — | Supabase 託管 | Supabase |

業務員後台**不要塞進 App 裡**。理由有二：

1. 消費者 App 的每一 KB 都要離線快取，塞進用不到的後台程式碼是浪費
2. 訂閱付費在網頁上進行，可以完全避開 Google Play 的抽成（見第九節）

---

## 四、資料模型

### 設計原則

**照著現在 localStorage 的形狀走，用 JSONB 收納細節。** 事故的進度、對方資料、求償金額都是「整包讀、整包寫」，拆成關聯式表格只會增加同步的複雜度而沒有查詢上的好處。

順帶好處：這一步**同時解決了 ROADMAP 2.1「事故案件的概念」**。有了 `incidents` 表，多筆事故、可結案、保留歷史全部自然成立。

### 表格

```sql
-- 一般使用者的個人資料。id 對應 auth.users
create table profiles (
  id          uuid primary key references auth.users on delete cascade,
  display_name text,
  phone       text,
  agent_id    uuid references agents(id) on delete set null,
  bound_at    timestamptz,
  created_at  timestamptz not null default now()
);

-- 業務員。也是一個 auth.users，但走不同的註冊入口
create table agents (
  id            uuid primary key references auth.users on delete cascade,
  name          text not null,
  company       text,
  phone         text,
  line_url      text,
  invite_code   text unique not null,       -- 短碼，給客戶輸入或掃描
  active        boolean not null default true,
  sub_status    text not null default 'trial',   -- trial / active / past_due / canceled
  sub_until     timestamptz,
  created_at    timestamptz not null default now()
);

-- 一起事故 = 一筆。取代現在全域單一份的 localStorage
create table incidents (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users on delete cascade,
  occurred_at  timestamptz not null,
  location     jsonb,        -- { lat, lon, addr, manual }
  other_party  jsonb,        -- 對方資料七欄
  claim        jsonb,        -- 求償金額七項
  progress     jsonb,        -- 各清單的勾選狀態
  photo_count  int not null default 0,   -- 只存數量，照片本身不上傳
  closed_at    timestamptz,
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz
);

create index on incidents (user_id, occurred_at desc);
```

### 刻意不做的事

- **照片不建表。** 只在 `photo_count` 記數量，讓使用者換手機時知道「原本有 12 張，這台裝置上沒有」。
- **不記錄使用者位置軌跡。** 只有事故當下那一個點。
- **不做軟性分析事件表。** 要看使用數據就用 Supabase 內建的統計，不要自己蒐集行為軌跡 —— 那會讓隱私權政策的揭露範圍大幅擴張。

---

## 五、權限規則

用 Postgres 的 Row Level Security，**不要在前端做權限判斷**。

```sql
alter table incidents enable row level security;

-- 使用者只能碰自己的事故
create policy "own incidents" on incidents
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter table profiles enable row level security;

create policy "own profile" on profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

-- 業務員資料所有人可讀（客戶要顯示綁定的業務員），但只有本人能改
alter table agents enable row level security;

create policy "agents readable" on agents for select using (active = true);
create policy "agent self update" on agents for update using (auth.uid() = id);
```

### 最重要的一條權限

**業務員看不到客戶的事故內容。**

業務員能查到的只有「綁定了幾位客戶」這個數字。事故地點、對方資料、求償金額、照片，一律不開放 —— 即使那是他自己的客戶。

理由：客戶願意用這個 App 記錄事故細節，前提是那些資料只屬於他自己。如果業務員看得到，這個 App 就從「幫你的工具」變成「監看你的工具」，而且會直接違反現在對使用者的承諾。

要讓業務員知道細節，走**客戶主動分享**（現有的「複製」「分享」按鈕），不要走後台查詢。

---

## 六、登入與 session

### 註冊方式

**Email + 密碼** 作為基準：

- 零邊際成本（手機簡訊 OTP 每則要錢）
- 不依賴任何第三方登入供應商
- Supabase 內建，不必自己處理雜湊與重設流程

若之後要降低註冊摩擦，再加 Google 登入。**注意**：iOS 上只要提供了任一第三方社群登入，Apple 就要求同時提供 Sign in with Apple。這是加社群登入前要先知道的事。

### 註冊時要不要收手機號碼

建議**選填**。收了才能在業務員需要時聯繫，但那是可以之後補的。強制填會增加註冊流失，而且多一項個資就多一分保管責任。

### 開啟流程

```
App 啟動
  │
  ├─ 本機旗標 aa.registered.v1 == '1' ？
  │     │
  │     ├─ 是 → 直接進入 App（不檢查網路、不檢查 token）
  │     │        └─ 背景嘗試同步，失敗就算了
  │     │
  │     └─ 否 → 顯示註冊／登入畫面
  │              └─ 成功後寫入旗標，永久生效
```

**旗標只在使用者主動登出時清除。** token 過期、續期失敗、離線，都不清除。

---

## 七、同步策略

### 策略：Last-Write-Wins，以 `updated_at` 為準

不做欄位級合併，不做衝突解決 UI。理由是這個 App 的使用情境是**單人、單一事故、幾乎不會多裝置同時編輯**，為了理論上的正確性引入合併邏輯不划算。

### 離線佇列

寫入一律先寫本機（維持現在的行為），再排進待同步佇列：

```js
// 本機永遠是唯一真相來源，雲端是備份
function saveIncident(data){
  save(LS.incident, data);        // 立刻生效，不等網路
  queueSync(data);                // 進佇列
}
```

佇列存在 IndexedDB。時機：有網路時、App 回到前景時、成功登入後。**失敗就留在佇列裡，不重試到爆、不跳錯誤。**

### 同步狀態的呈現

「我的」頁一行小字：`上次同步 14:32` 或 `尚未同步（離線中）`。就這樣，不要更多。

---

## 八、業務員綁定

這一節終於實作 ROADMAP 4.1，而且用的是 DEVLOG 裡那個關鍵洞察：**存代碼，不要存資料。**

### 流程

```
業務員在後台產生邀請連結
        https://guardy.app/j/AB12CD
                  │
        分享給客戶（LINE、QR、名片）
                  │
客戶開啟 → 註冊／登入 → profiles.agent_id = 該業務員
                  │
客戶的「我的」頁出現業務員卡片，資料即時來自 agents 表
```

### 為什麼這樣就解決了之前推翻的問題

先前「邀請碼自帶資料」被推翻，是因為業務員換電話、換公司、離職之後，客戶手機裡那份資料**永遠是錯的且無法更新**。

現在客戶的 `profiles` 只存 `agent_id` 這一個外鍵，**業務員資料的擁有權留在業務員自己手上**，他在後台改一次，所有綁定客戶下次連線就看到新的。

### 離線時怎麼辦

業務員的姓名、電話、LINE 在綁定成功時**快取一份到本機**，離線時顯示快取值。有網路時背景更新。

這不違反「存代碼不存資料」—— 差別在於快取有明確的來源可以刷新，而自帶資料的代碼沒有。

### 沒有綁定業務員的使用者

必須完全正常運作。「我的」頁顯示「尚未綁定業務員」加一個輸入邀請碼的入口，不強迫、不擋任何功能。

---

## 九、訂閱與金流

### 賣在網頁後台，不要賣在 App 裡

Google Play 對「App 內販售數位商品」強制走 Google Play Billing，抽成 15–30%。

但 Guardy 的付費方是**業務員，不是消費者**。業務員在網頁後台刷卡訂閱，完全不經過 App，Play 的規則就管不到。

**消費者 App 裡連提都不要提付費**，也不要放任何指向付費頁的連結 —— Play 的規則對「引導站外付費」也有限制，最乾淨的做法是消費者端完全不出現商業訊息。

### 金流

台灣本地用**藍新**或**綠界**，兩家都支援定期定額。若之後有海外業務員再考慮 Stripe。

### 訂閱狀態的影響範圍

| 狀態 | 業務員後台 | 已綁定的客戶 |
|---|---|---|
| `trial` / `active` | 完整功能 | 正常顯示業務員 |
| `past_due` | 唯讀，提示付款 | **正常顯示業務員** |
| `canceled` | 只能匯出資料 | 顯示「業務員資訊暫不可用」，其餘功能不受影響 |

**客戶端永遠不因為業務員欠費而失去核心功能。** 客戶沒有義務承擔業務員的付款問題。

---

## 十、既有資料的遷移

目前所有資料在 localStorage 與 IndexedDB。加上帳號後：

1. 首次登入成功時，檢查本機是否有既有資料
2. 有的話，包成**一筆 incident** 上傳，`occurred_at` 用既有的事故時間
3. 照片留在原地不動，只寫入 `photo_count`
4. 遷移完成後標記，不重複執行

因為**目前還沒有正式使用者**，遷移的實際風險接近零。這也是現在做這件事最划算的時機 —— 上線後再改，每一個使用者的資料都要處理。

---

## 十一、法遵與文件變更

改成帳號制之後，以下文件會變成**不實陳述**，必須同步修改：

### `privacy.html` 要整份重寫

現在寫的（會失效的部分）：

| 現在的說法 | 改成帳號制後 |
|---|---|
| 「Guardy 沒有伺服器，也沒有帳號」 | ❌ 不再成立 |
| 「不蒐集任何個人資料」 | ❌ 會蒐集 Email、選填手機 |
| 「資料不會上傳到任何地方」 | ⚠️ 部分成立：**照片仍然不上傳**，文字資料會 |
| 「不會在裝置之間同步」 | ❌ 反了 |

新版必須明確交代：蒐集哪些欄位、存放位置與期間、如何刪除帳號與資料、委外處理者（Supabase）是誰、資料存放在哪個區域。

**照片不上傳這一點要寫得很醒目** —— 那是相較同類產品最有說服力的隱私承諾，別把它埋在條文裡。

### Google Play Data safety

從「不蒐集任何資料」改為「蒐集並傳輸：帳號資訊、位置資訊」。要申報加密傳輸與刪除管道。

### 個資法義務

蒐集個資後開始適用告知、保存、刪除等義務。**具體條文與特定目的代號【待查證】** —— 這部分建議直接諮詢律師，不要照網路資料填。

App 內必須提供**刪除帳號**的功能，且要真的刪掉資料（`on delete cascade` 已經設好）。

### 服務條款

現在沒有。有了帳號就需要一份，界定使用規範與責任邊界。

---

## 十二、實作階段

每個階段都可獨立上線，不要一次改完才部署。

### M1 — 帳號骨架（不接真後端）

- 註冊／登入畫面 UI
- 本機 `aa.registered.v1` 旗標與開啟流程
- **驗證離線鐵則**：飛航模式下重開 App 十次，每次都能正常進入

> 這階段就要把離線行為測到滿意。後面接了真後端只會更難測。

### M2 — 接上 Supabase Auth

- Email + 密碼註冊、登入、忘記密碼
- session 持久化與靜默續期
- 刪除帳號

### M3 — 事故資料上雲

- `incidents` 表與 RLS
- 離線佇列與 LWW 同步
- 既有 localStorage 資料遷移
- ~~順勢完成 ROADMAP 2.1~~ —— **事故案件已於 v27 先行完成**（多筆事故、可結案、歷史紀錄、案件層級的照片隔離）。M3 只剩把 `aa.case.<id>` 那一包同步上雲，本機這一側不必再動

### M4 — 業務員綁定

- `agents` 表、邀請碼與連結
- 客戶端綁定流程與業務員卡片（含離線快取）
- `who()` 函式接回真實資料 —— 這個接縫從一開始就留好了

### M5 — 業務員後台

- 獨立網頁：註冊、編輯自己的資料、產生邀請連結與 QR、看綁定客戶數
- **QR 產生器已經寫好且驗證過**（見 DEVLOG「被推翻的方向」），終於有用武之地

### M6 — 訂閱與金流

- 藍新／綠界定期定額
- 訂閱狀態與後台權限
- 客戶端**完全不受影響**

---

## 十三、風險

| 風險 | 嚴重性 | 對策 |
|---|---|---|
| **離線被登出** | 致命 | 第二節的鐵則；M1 就要把離線情境測透 |
| **強制註冊造成流失** | 高 | 註冊欄位越少越好；Email + 密碼兩欄，手機選填 |
| **個資外洩** | 高 | 照片不上雲已排除最敏感的一塊；RLS 全開；不自建行為分析 |
| **Supabase 免費額度用完** | 中 | 只同步文字，用量極小；到量再升級 |
| **業務員不願付費** | 中 | M5 做完就能驗證，不必等到 M6 |
| **政策文件沒同步改** | 中 | 列入上線檢查清單，見 ROADMAP |
| **供應商鎖定** | 低 | Supabase 是 Postgres + 開源，要搬走不難 |

---

## 附註：這份設計刻意保留的東西

即使加了帳號，以下原則**不變**：

1. 核心功能離線可用
2. 首屏只有位置 + 110／119
3. 照片只存在使用者手機
4. 不編造電話號碼、法條、統計數字
5. 業務員看不到客戶的事故內容

第 5 點是這次新增的。前四點從第一天就在。
