-- Guardy — M2：使用者個人資料
--
-- 在 Supabase 後台的 SQL Editor 貼上執行。可以重複執行（都有 if not exists／drop if exists）。
--
-- 這個檔案只建 profiles。agents 與 incidents 留到 M4／M3，
-- 一次只上一張表，出問題才知道是哪一步。

-- ─────────────────────────────────────────────
-- profiles：一般使用者。id 直接對應 auth.users
-- ─────────────────────────────────────────────
create table if not exists public.profiles (
  id           uuid primary key references auth.users on delete cascade,
  display_name text,
  phone        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

comment on table public.profiles is
  '一般使用者的個人資料。事故內容不在這裡，也不在任何業務員看得到的地方。';

-- ─────────────────────────────────────────────
-- RLS
--
-- 這一步不能省。anon key 是公開的、會放進前端，
-- 資料庫的安全性**完全**靠 RLS —— 沒開等於整張表對外開放讀寫。
-- ─────────────────────────────────────────────
alter table public.profiles enable row level security;

drop policy if exists "own profile select" on public.profiles;
drop policy if exists "own profile update" on public.profiles;
drop policy if exists "own profile insert" on public.profiles;

-- 拆成三條而不是一條 for all：
-- delete 刻意不開 —— 刪帳號要連 auth.users 一起走（on delete cascade），
-- 只刪 profiles 會留下一個沒有個人資料的殭屍帳號。
create policy "own profile select" on public.profiles
  for select using (auth.uid() = id);

create policy "own profile insert" on public.profiles
  for insert with check (auth.uid() = id);

create policy "own profile update" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

-- ─────────────────────────────────────────────
-- 註冊時自動建立 profile
--
-- 讓前端註冊完再多送一次 insert 也可以，但那多一個「送出失敗就沒有
-- profile」的失敗點。放在觸發器裡，註冊成功就一定有。
--
-- security definer 是必要的：觸發器執行時還沒有 auth.uid()，
-- 過不了上面那條 insert 政策。search_path 一定要鎖死，
-- 否則 security definer 函式會變成提權漏洞。
-- ─────────────────────────────────────────────
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.profiles (id, phone)
  values (new.id, nullif(new.raw_user_meta_data ->> 'phone', ''))
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ─────────────────────────────────────────────
-- updated_at 自動更新
-- ─────────────────────────────────────────────
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch
  before update on public.profiles
  for each row execute function public.touch_updated_at();

-- ─────────────────────────────────────────────
-- 驗證：跑完之後這三個查詢應該分別回傳
--   1) rls_enabled = true
--   2) 三條政策
--   3) 一個觸發器
-- ─────────────────────────────────────────────
-- select relrowsecurity as rls_enabled from pg_class where relname = 'profiles';
-- select policyname, cmd from pg_policies where tablename = 'profiles';
-- select tgname from pg_trigger where tgrelid = 'auth.users'::regclass and not tgisinternal;
