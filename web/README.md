# Nument Leads: web app

The team workspace for the Nument lead engine. Every morning the engine (GitHub Actions, see `../engine`) researches businesses, scores them and writes a first WhatsApp message for the best ones. This app is where the team reads that evidence, sends the messages in one tap, moves leads through the pipeline and tunes the engine.

It reads and writes the same Supabase database as the engine and the Google Sheet sync. It never scrapes, never calls data sources and never sends WhatsApp messages itself: it only opens WhatsApp with the message ready.

## What is in it

| Page | Who | What it does |
|---|---|---|
| **Today** `/` | everyone | KPI tiles, the send list (new A and B leads, best first) and the day 3 and day 7 follow-ups. Opening WhatsApp Web or the WhatsApp app marks the lead as contacted in the same tap, with an Undo. Skip hides a lead for 7 days; Wrong contact puts the number on Do not contact. |
| **Leads** `/leads` | everyone | Server-side filters (segment, country, city, grade, signal, stage, pitch mode, mobile, overdue, owner, date added), search, sorting and pagination, all in the URL. Saved views (own and shared), column chooser, bulk stage change, CSV export. |
| **Lead** `/leads/[id]` | everyone | Why this lead (score bars, reasons, judge note), contact card, message editor with the engine's lint, follow-ups, signals with evidence links, verified facts, website and tech check, timeline with sources, notes, feedback. Admins also get the deal value and proposal uploads. |
| **Pipeline** `/pipeline` | everyone | Kanban board. Drag with a mouse, press and hold on a phone, or use the keyboard (arrow keys between columns). |
| **Insights** `/insights` | everyone | Funnel, what works by segment, country, signal, pitch mode, angle or test group, lead quality. Admins also see spend per day against the cap and unit costs. |
| **Engine** `/engine` | admin | Segment switches and daily quotas, the daily cap with a spend meter, source kill switches and health, recent runs, manual runs on GitHub Actions, the custom search queue. |
| **Inbox** `/inbox` | admin | Paste a public post where someone asks for help. The engine works from the pasted text and never opens LinkedIn or X. |
| **Settings** `/settings` | everyone | Name, password, sign out other devices. Admins also manage users and roles and the Do not contact list. |

### Product tour

A short tour opens by itself on a user's first visit, once any forced password change is done. It walks through the pages that user's role can open (callers never get Engine, Inbox, users, Do not contact or the deal card), highlights each part and docks to the screen edge on a phone. Where a part is missing, for example with no leads yet, it shows a centred card that says what will appear there. Skip, Esc or Done closes it for good: the time is saved as `tour_completed_at` in the user's own `user_metadata` (harmless if a user edits it, it only hides the tour) and mirrored in localStorage so it never flashes back. The help button in the top bar and **Take the tour** in the account menu replay it. Steps and copy live in `src/lib/tour.ts`; the component is `src/components/tour/product-tour.tsx`; pages mark what it highlights with `data-tour="..."`.

### Roles

| | Admin | Caller | Viewer |
|---|---|---|---|
| Read leads, evidence, timeline | yes | yes | yes |
| Send, change stage, edit messages and notes | yes | yes | no |
| See or change money (deal value) | yes | **never** | **never** |
| Engine, Inbox, users, Do not contact list | yes | no | no |

Pages a role cannot open are not in its menu, the page itself checks the role, every Server Action checks it again, and Row Level Security checks it a third time in the database.

## How it is built

- **Next.js 16** (App Router, React 19, strict TypeScript) with **Cache Components**: each page's frame is prerendered and served instantly, and everything that depends on the signed-in user streams in behind `Suspense`.
- **Supabase** for auth (email and password, sign-up off) and Postgres, through `@supabase/ssr` cookie sessions.
- **Tailwind CSS 4** themed with the Nument design kit tokens (`src/styles/tokens.css`): Newsreader, Figtree and DM Mono through `next/font`, kit colours only, pill buttons, hairline cards.
- Radix primitives (dialog, menu, switch), TanStack Table, dnd-kit, Recharts, zod, sonner.

### Security model

- `src/proxy.ts` refreshes the session on every request (`getClaims()`, verified locally against the project's signing keys), sends visitors to `/login?next=...`, and sends anyone with a temporary password to `/settings?change_password=1`.
- `src/lib/auth.ts` is the data access layer: `getSessionUser()` verifies the user with the Auth server (a disabled user loses access at once) and reads the role from `profiles`. `requireRole([...])` guards pages and actions.
- Every query runs as the signed-in user (`src/lib/supabase/server.ts`), so Row Level Security applies. The service-role client (`src/lib/supabase/admin.ts`, `server-only`) is used only after a role check, for the few writes an app user cannot make: auth admin calls, the deal value, lifting a just-made wrong-contact mark, and reading teammates' names.
- **Money never reaches callers.** Lists and pages read `v_leads_caller`, which has no money column. Admins get deal values from `v_leads_admin` in a separate query. `deal_value_inr` has no column grant for app users and is written only by an admin action with the service role. The timeline records that a deal value changed, never the amount, because callers can read the timeline. The CSV export has a deal value column only for admins.
- Public sign-up is off in Supabase. Admins create users in **Settings, Users and roles** with a 16 character temporary password shown once; the user must choose their own password at first sign in. Admins can reset a password the same way, change roles and disable accounts. The temporary-password flag lives in `app_metadata`, which only the service role can change (a user can edit their own `user_metadata`, so a flag there could be skipped). It is cleared on the server only after the user's own password change succeeds.
- Security headers on every response (no framing, no sniffing, strict referrer, HSTS, `noindex`).

### Speed

- **One session check per request.** `getClaims()` (verified locally) and `getSessionUser()` (one `getUser` and one profile read) are cached per request with React `cache()`, however many components ask.
- **No waterfalls.** Queries that run as the user start together with the session check (`early()` in `src/lib/auth.ts`); money and admin-only reads follow the role check. The lead page reads the business, contacts, signals, facts, score and pages in one request through PostgREST embedding.
- **Cached for everyone, updated on change.** Segments, team names, the budget settings and the last sheet sync are read with the service role after the session check and cached with `use cache` (`src/lib/cache-tags.ts`). The Server Actions that change them call `updateTag`. Nothing per user and nothing money-related is cached.
- **Instant navigation.** Links prefetch each page's prerendered shell; every route has a `loading.tsx` with the page's own skeleton, so the sidebar never repaints and the new page frame shows at once. Recharts loads after the page is interactive.
- **Measuring.** `next dev`, or any build with `PERF_LOG=1`, prints one `[perf]` line per Supabase call with its time. `pnpm build`, then `PERF_OUT=/abs/path/result.json pnpm exec playwright test -c playwright.perf.config.ts` signs in as a temporary e2e admin and records TTFB, content ready, load, JS size and Supabase calls for every page, plus sidebar navigation. `tests/e2e/navigation.spec.ts` fails if moving between pages loads a new document.

### Data rules worth knowing

- Database triggers write the `lead_created`, `stage_change`, `grade_change` and `message_edited` activities. The app never inserts those four, so nothing is logged twice. It logs its own kinds (`sent`, `followup_sent`, `skip`, `wrong_contact`, `note`, `edit`, `feedback`, `regen_request`, `proposal_upload`, `undo`) with `source = 'app'` (`src/lib/activity.ts`).
- When a stage or contact date changes, the app recomputes `next_step` and `due_at` with the same rule as the sheet and the engine (`src/lib/next-step.ts`, plan 13.5.4).
- Message edits are checked with the engine's lint (`src/lib/lint.ts`, plan 12.5). Save stays blocked until the lint passes, and the Server Action checks it again.
- WhatsApp links are built when shown (`src/lib/whatsapp.ts`) and only for mobile numbers; landlines get Call.
- All times are stored in UTC and shown in India time (`src/lib/dates.ts`).

## Getting started

Requirements: Node 22.12 or newer (Render uses 24) and pnpm 11 (`corepack enable` picks the version in `package.json`).

```bash
cd web
cp .env.example .env.local   # fill in the values (see below)
pnpm install
pnpm dev                     # http://localhost:3000
```

### Environment variables

| Name | Where | Notes |
|---|---|---|
| `APP_ENV` | server | `dev` or `prod`. `dev` shows a DEV badge in the top bar. |
| `NEXT_PUBLIC_SUPABASE_URL` | browser and server | Project URL. Baked in at build time. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | browser and server | Public key, protected by RLS. Baked in at build time. |
| `NEXT_PUBLIC_APP_URL` | server | Public URL of the app, used in password reset links. |
| `SUPABASE_URL` | server | Same project URL, for the service-role client. |
| `SUPABASE_SERVICE_ROLE_KEY` | server only | Bypasses RLS. Never `NEXT_PUBLIC_`, never sent to the browser. |
| `GH_REPO` | server | `with-nument/nument-lead`, for manual runs from the Engine page. |
| `GH_DISPATCH_REF` | server | Branch the runs start on, `main`. |
| `GH_DISPATCH_TOKEN` | server only | Fine-grained token with Actions read and write on this repository only. Without it the Run buttons explain how to turn them on. |

### Scripts

| Command | What it does |
|---|---|
| `pnpm dev` | Development server |
| `pnpm build` | Production build (standalone output) plus static assets copied next to `server.js` |
| `pnpm start` | Runs the standalone server (`node .next/standalone/server.js`) |
| `pnpm lint` | ESLint with zero warnings allowed |
| `pnpm typecheck` | Route types plus `tsc --noEmit` |
| `pnpm test` | Unit tests (Vitest) |
| `pnpm e2e` | End-to-end tests (Playwright), see below |
| `pnpm db:types` | Regenerates `src/lib/database.types.ts` from the live project. Needs `SUPABASE_ACCESS_TOKEN` and `SUPABASE_PROJECT_REF`. Run it after every migration. |

## Tests

**Unit tests** (`tests/unit`) cover the message lint, WhatsApp links, the stage contract, password rules and temporary passwords, CSV escaping and the formula guard, India-time dates, the next step rule, URL filters and phone formatting.

**End-to-end tests** (`tests/e2e`) run against the **dev** project only (they refuse `APP_ENV=prod`). Build first, then `pnpm e2e`; Playwright starts the standalone server. Set `PW_CHANNEL=chrome` to use the installed Google Chrome.

| Spec | Needs | Checks |
|---|---|---|
| `public.spec.ts` | nothing | Health, redirects to sign in with `next`, the same message for a wrong email or password, the same reset answer for an unknown email, no sign-up, security headers |
| `founder.spec.ts` | `E2E_FOUNDER_EMAIL`, `E2E_FOUNDER_PASSWORD` | Sign in with a temporary password lands on the forced password change, other pages send you back, log out. It never submits a new password. |
| `app.spec.ts` | `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD` (a dev test admin without a temporary password) | Seeds five clearly marked test leads and deletes them after: mark sent and undo (one `stage_change` row, written by the trigger), stage change on the lead page and the board, lint blocking save, axe checks (WCAG 2 A and AA), the admin deal value. With `E2E_ALLOW_USER_CREATION=1` it also creates a temporary caller through the UI, checks the caller never sees money (page, `/engine`, CSV, direct queries) and deletes the caller. |
| `mobile.spec.ts` | the admin above for the signed-in part | iPhone 14 size: sign in and Today with the WhatsApp app button first and no sideways scroll |
| `tour.spec.ts` | the temporary tour users | The tour opens on a first visit with the right steps for a caller and an admin, finishing or skipping sticks across reloads and browsers, replay from the help button and the account menu, arrow keys, Esc and the focus trap, axe on the card, and no tour until a temporary password is changed |

Screenshots for a visual review: `SHOTS_DIR=/abs/path pnpm exec playwright test -c playwright.screens.config.ts` captures every page and every tour step as admin and caller, desktop and phone. Add `E2E_FIXTURE_LEADS=0 SHOTS_TAG=empty` to see the app with no leads at all.

## Deploy on Render

`../render.yaml` is a Render Blueprint: one web service in Singapore on Node 24, free plan, `rootDir: web`, health check `/api/health` (no database call), standalone server on `0.0.0.0` (Render sets `PORT`). Builds only run when `web/**` changes.

1. Render, **New**, **Blueprint**, pick this repository.
2. Fill every `sync: false` value: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_APP_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GH_DISPATCH_TOKEN`. `APP_ENV`, `NODE_VERSION`, `HOSTNAME`, `NEXT_TELEMETRY_DISABLED`, `GH_REPO` and `GH_DISPATCH_REF` come from the file. `NEXT_PUBLIC_*` values are baked into the build: change them, then redeploy.
3. Apply, wait for the build, open `/api/health`.
4. In Supabase, **Authentication, URL Configuration**: set the Site URL to the app URL and add `<app URL>/**` to the redirect URLs.
5. Optional, for reset links that also work in another browser: in the **Reset password** email template, link to `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=recovery&next=/reset-password/update`. `/auth/confirm` accepts both this and the default link.

The free plan sleeps after 15 idle minutes, so the first visit after a quiet spell takes up to a minute. Move to the starter plan at go-live.

**Custom domain** `leads.nument.in`: add it under the service's Custom Domains, create a `CNAME` named `leads` pointing to the `onrender.com` host at the DNS provider, wait for the certificate, then update `NEXT_PUBLIC_APP_URL` and the Supabase URLs and redeploy.

Password reset emails use Supabase's built-in mailer, which has a low hourly limit and needs a real mailbox. Until custom SMTP is set up, an admin resets passwords from **Settings, Users and roles**.

## Project layout

```
web/
  src/
    proxy.ts                  session refresh and routing rules
    app/
      (auth)/                 sign in, reset password (static, kit auth layout)
      (app)/                  the signed-in app: Today, Leads, Lead, Pipeline, Insights, Engine, Inbox, Settings
        actions.ts            Today actions (mark sent, skip, wrong contact, undo, follow-ups)
      auth/confirm/           email link landing (token_hash or PKCE code)
      api/health/             Render health check
    components/               ui (kit primitives), shell, today, leads, lead, pipeline, insights, engine, settings
    lib/
      supabase/               server (as the user), admin (service role), proxy
      queries/                one read module per page, all server-only
      auth.ts, roles.ts       session and role checks
      database.types.ts       generated, do not edit
    styles/tokens.css         Nument kit tokens
  tests/unit, tests/e2e
```

## Notes for later

- A Content Security Policy needs per-request nonces, which would turn the prerendered page frames dynamic. Worth adding if the app ever loads third-party scripts.
- Supabase Realtime is not needed for two or three users; pages refresh quietly at most every 5 minutes while visible, and when someone comes back after 5 minutes away, never while they type or have a dialog open.
- Two-factor sign-in (TOTP) can be added when the team grows (plan 15.3.9).
