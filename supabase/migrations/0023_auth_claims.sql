-- 0023_auth_claims.sql : the role and name travel in the sign-in token (web speed, 15 Nov 2026)
--
-- Every page used to ask the Auth server who the user is (getUser) and then read their profile: two round
-- trips (60 ms or more each, Render in Singapore to Supabase in Mumbai) before any data. With this hook,
-- Supabase Auth writes the user's role and name from public.profiles into every access token it issues, as
-- the claims `user_role` and `full_name`. The app reads them from the token it already verifies locally
-- (getClaims), so a page render needs no Auth call and no profile read.
--
-- Nothing else trusts the claim. Row Level Security keeps reading public.profiles through auth_role(), so the
-- database decides what each person can see, whatever the token says. Actions that matter (users, money,
-- passwords) still ask the Auth server first. A role or name change reaches the token at its next refresh
-- (the app refreshes the session itself when someone changes their own name or password).
--
-- MANUAL STEP after applying (once per project, dev and prod):
--   Supabase Dashboard > Authentication > Hooks > Add hook > "Customize Access Token (JWT) Claims" >
--   Postgres > schema public > function custom_access_token_hook > Create.
--   Or with the Management API: PATCH /v1/projects/{ref}/config/auth
--     { "hook_custom_access_token_enabled": true,
--       "hook_custom_access_token_uri": "pg-functions://postgres/public/custom_access_token_hook" }
-- Until the hook is on, tokens carry no `user_role` and the app reads the profile as before, so applying this
-- migration on its own changes nothing. Tokens issued before the hook was switched on pick the claims up at
-- their next refresh (within the access token lifetime, one hour by default).
--
-- Also here: public.revoke_user_sessions(uuid) for Settings > Users > Disable. A ban stops new sign-ins and
-- token refreshes but ends no session that already exists, and page renders no longer ask the Auth server, so
-- the app now deletes the user's sessions (and with them every refresh token) when it disables someone, the
-- same thing the Auth server's own sign-out does. An access token already handed out still verifies until it
-- expires (one hour by default; Dashboard > Project Settings > JWT Keys sets the expiry), after which the
-- refresh fails and the person is signed out.

-- 1. The hook ------------------------------------------------------------------------------------------------
-- Supabase Auth calls it as supabase_auth_admin with {"user_id", "claims", "authentication_method"} and uses
-- the "claims" it returns. It must never fail (a failing hook blocks every sign-in), so any error returns the
-- event unchanged and the app falls back to reading the profile.
create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  claims jsonb := coalesce(event -> 'claims', '{}'::jsonb);
  v_role text;
  v_name text;
begin
  begin
    select p.role, nullif(btrim(p.full_name), '')
      into v_role, v_name
      from public.profiles p
     where p.user_id = (event ->> 'user_id')::uuid;
  exception when others then
    return event;
  end;
  if v_role is null then
    -- No profile (yet): no claim at all, so the app reads the profile instead of trusting a guess.
    claims := claims - 'user_role' - 'full_name';
  else
    claims := claims || jsonb_build_object('user_role', v_role, 'full_name', v_name);
  end if;
  return jsonb_set(event, '{claims}', claims);
end;
$$;

-- Only the Auth server may run it (Supabase docs, Custom Access Token Hook).
grant usage on schema public to supabase_auth_admin;
grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function public.custom_access_token_hook(jsonb) from authenticated, anon, public;

-- The hook runs as supabase_auth_admin (security invoker), which needs to read three profile columns. Row Level
-- Security stays on for everyone else; this policy is for the Auth server's role only.
grant select (user_id, role, full_name) on table public.profiles to supabase_auth_admin;
create policy profiles_auth_admin_read on public.profiles as permissive for select to supabase_auth_admin
  using (true);

-- 2. Ending a disabled user's sessions -------------------------------------------------------------------------
-- Deletes every session of the user (their refresh tokens go with them, by foreign key; the legacy rows without
-- a session are deleted too). Returns how many sessions were ended. The service role only: the app calls it
-- from the admin-only Disable action after the ban. Local and CI Postgres have no auth.sessions: returns 0.
create or replace function public.revoke_user_sessions(target_user uuid)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  ended integer := 0;
begin
  if target_user is null or to_regclass('auth.sessions') is null then
    return 0;
  end if;
  delete from auth.sessions s where s.user_id = target_user;
  get diagnostics ended = row_count;
  if to_regclass('auth.refresh_tokens') is not null then
    delete from auth.refresh_tokens t where t.user_id = target_user::text;
  end if;
  return ended;
end;
$$;

revoke all on function public.revoke_user_sessions(uuid) from public, anon, authenticated;
grant execute on function public.revoke_user_sessions(uuid) to service_role;
