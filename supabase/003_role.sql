-- Guardy — 身分：一般使用者／保險業務員
--
-- 在 Supabase 後台的 SQL Editor 執行，順序在 001_profiles.sql 之後。
-- 可以重複執行。
--
-- ★ 這個欄位是使用者自己宣告的，沒有經過任何驗證。★
--
-- 任何人都可以在 App 裡點「保險業務員」。所以它只能決定
-- 「使用者看到什麼介面」，**絕對不能出現在任何 RLS 政策裡**。
-- 一旦有一條政策長成 `using (role = 'agent')`，等於把那張表
-- 開放給所有願意點兩下的人。
--
-- 本檔案不新增、不修改任何政策。incidents 與 profiles 的權限
-- 到目前為止仍然只有一條判準：auth.uid() = 本人。

alter table public.profiles
  add column if not exists role text not null default 'user';

-- 白名單而不是自由文字。少了這條，前端一個打錯的字串就會
-- 悄悄存進去，之後對照 UI 時完全查不出來為什麼沒生效。
alter table public.profiles
  drop constraint if exists profiles_role_check;
alter table public.profiles
  add constraint profiles_role_check check (role in ('user', 'agent'));

comment on column public.profiles.role is
  '使用者自述的身分，未驗證。只影響介面，不得用於任何權限判斷。';

-- ─────────────────────────────────────────────
-- 註冊觸發器
--
-- 身分是在**登入成功之後**才問的，註冊當下還不知道，
-- 所以這裡不去讀 raw_user_meta_data，一律用預設值 'user'，
-- 之後由前端 PATCH 更新。
--
-- 順帶把 phone 拿掉：那個欄位原本的用途是「業務員需要時聯絡得到你」，
-- 綁定功能取消之後就沒有任何地方會讀它。蒐集了卻用不到的個資
-- 是純粹的負擔，不留。
-- ─────────────────────────────────────────────
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.profiles (id)
  values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$;

-- 既有的 phone 欄位先留著不 drop —— 萬一要退版，資料還在。
-- 確認新版穩定之後再執行下面這行：
--   alter table public.profiles drop column if exists phone;

-- ─────────────────────────────────────────────
-- 驗證
-- ─────────────────────────────────────────────
-- select column_name, column_default, is_nullable
--   from information_schema.columns
--  where table_name = 'profiles' and column_name = 'role';
--
-- 這一句應該回傳 0 列 —— 沒有任何政策提到 role：
-- select policyname, tablename from pg_policies
--  where qual like '%role%' or with_check like '%role%';
