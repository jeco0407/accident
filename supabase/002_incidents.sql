-- Guardy — M3：事故資料上雲
--
-- 在 Supabase 後台的 SQL Editor 執行，順序在 001_profiles.sql 之後。
-- 可以重複執行。
--
-- 只同步**文字**。照片永遠不上傳 —— 這裡只留一個 photo_count，
-- 讓使用者換手機時知道「原本有 12 張，這台裝置上沒有」。

create table if not exists public.incidents (
  -- id 由前端產生（crypto.randomUUID）。這樣離線時就能先建好本機紀錄，
  -- 之後補送，不必等伺服器回一個 id 才能開始用。
  id           uuid primary key,
  user_id      uuid not null references auth.users on delete cascade,

  occurred_at  timestamptz not null,
  location     jsonb,        -- { lat, lon, addr, manual, at }
  other_party  jsonb,        -- 對方資料四欄
  claim        jsonb,        -- 求償金額七項
  progress     jsonb,        -- 各清單的勾選狀態

  photo_count  int not null default 0,

  closed_at    timestamptz,
  -- 軟刪除。硬刪除會讓其他裝置永遠不知道這筆被刪了 ——
  -- 它只會看到「這筆沒出現在拉取結果裡」，跟「還沒同步到」分不出來。
  deleted_at   timestamptz,

  updated_at   timestamptz not null default now(),
  created_at   timestamptz not null default now()
);

comment on table public.incidents is
  '一起事故一筆。只存文字，照片不上傳，只記數量。';

-- 拉取時固定是「我的、比上次新的」，這個索引直接對應那個查詢
create index if not exists incidents_user_updated
  on public.incidents (user_id, updated_at desc);

-- ─────────────────────────────────────────────
-- RLS
--
-- 最重要的一條權限（ARCHITECTURE 第五節）：**業務員看不到客戶的事故內容。**
-- 這裡沒有任何給業務員的政策，而且以後也不會加。
-- 要讓業務員知道細節，走客戶主動分享，不要走後台查詢。
-- ─────────────────────────────────────────────
alter table public.incidents enable row level security;

drop policy if exists "own incidents select" on public.incidents;
drop policy if exists "own incidents insert" on public.incidents;
drop policy if exists "own incidents update" on public.incidents;

create policy "own incidents select" on public.incidents
  for select using (auth.uid() = user_id);

create policy "own incidents insert" on public.incidents
  for insert with check (auth.uid() = user_id);

create policy "own incidents update" on public.incidents
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- delete 不開：刪除走 deleted_at 軟刪除。

-- ─────────────────────────────────────────────
-- updated_at
--
-- **不用資料庫的 now() 覆蓋前端送來的值。**
-- 同步用 Last-Write-Wins 比對 updated_at，如果伺服器每次都改寫成
-- 自己的時間，那「誰比較新」比的就是「誰比較晚送達」，不是「誰比較晚編輯」——
-- 離線幾天後才補送的舊資料會蓋掉新的。
--
-- 只在前端沒帶 updated_at 時補一個。
-- ─────────────────────────────────────────────
create or replace function public.incidents_default_updated_at()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  if new.updated_at is null then
    new.updated_at = now();
  end if;
  return new;
end;
$$;

drop trigger if exists incidents_touch on public.incidents;
create trigger incidents_touch
  before insert or update on public.incidents
  for each row execute function public.incidents_default_updated_at();

-- ─────────────────────────────────────────────
-- 驗證
-- ─────────────────────────────────────────────
-- select relrowsecurity from pg_class where relname = 'incidents';
-- select policyname, cmd from pg_policies where tablename = 'incidents';
