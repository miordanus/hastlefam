# Vercel deploy runbook

Procedure for shipping the FastAPI dashboard (`/finance/report` and friends) to Vercel. The Telegram bot stays on the worker process; only the **web** service deploys here.

## Architecture quick-recall

- Vercel runs `api/index.py` → `from app.main import app` → FastAPI app
- FastAPI talks to **Supabase via PostgREST** (HTTPS only; no Postgres socket needed because Vercel lambdas can't reach Supabase's IPv6-only direct host and the project's transaction pooler is broken)
- `vercel.json` sets `APP_ENV=vercel`; `app/infrastructure/db/session.py` uses `NullPool` in that mode (only used by routes that still touch SQLAlchemy)

## Prerequisites

- Vercel CLI logged in (`vercel login`)
- Supabase project `sfzyqdpckgyznuhunygj` with:
  - `hastlefam` listed in **Settings → API → Exposed schemas** (alongside `public, graphql_public`)
  - `service_role` granted USAGE+ALL on `hastlefam` schema (already applied via migration)
  - RPC `hastlefam.monthly_totals` exists (already applied via migration)
- Local `.env` has working `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`
- BotFather domain link (one-time): `/setdomain` → pick your bot → send the bare prod hostname, e.g. `hastlefam.vercel.app`. Required so the Telegram Login Widget will redirect back to this app.
- `hastlefam.users` table contains a row for every person who should be able to log in, with the correct numeric `telegram_id` and `is_active=true`. The numeric Telegram user ID can be obtained by DM-ing `@userinfobot`.

## Required production env vars

| Variable | Value | Notes |
|---|---|---|
| `SUPABASE_URL` | `https://sfzyqdpckgyznuhunygj.supabase.co` | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | (paste JWT from Supabase Dashboard → Settings → API → service_role) | **Never commit**. Server-only — never sent to browser. |
| `TELEGRAM_BOT_TOKEN` | (same token the bot worker uses) | The web service uses it **only** to verify Telegram Login Widget HMAC signatures. The bot itself is **not** run on Vercel. |
| `TELEGRAM_BOT_USERNAME` | (bot's username, **no** `@` prefix) | Embedded in the `/login` widget script. |
| `SESSION_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` | Random ≥32 bytes. HMAC key for the `hf_session` cookie. Rotate to force everyone to re-login. |
| `DATABASE_URL` | (set, but currently unused by REST path) | Kept for tests / fallback. Can be a placeholder like `postgresql+psycopg://noop` since `/finance/report` uses REST. |

Already-present env vars (`APP_ENV=vercel`, etc.) stay as-is. **Remove** `DASHBOARD_PASSWORD` if it's still set — Basic Auth has been deleted; the only auth path now is Telegram Login.

## Deploy procedure

```bash
# From repo root with a clean working tree
vercel env add SUPABASE_URL production
# paste: https://sfzyqdpckgyznuhunygj.supabase.co

vercel env add SUPABASE_SERVICE_ROLE_KEY production
# paste the service_role JWT (long, eyJ...)

vercel env add TELEGRAM_BOT_TOKEN production
# paste the bot token (same one the worker uses)

vercel env add TELEGRAM_BOT_USERNAME production
# paste your bot's username, no @

vercel env add SESSION_SECRET production
# paste output of: python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Remove the old basic-auth secret if it still exists
vercel env rm DASHBOARD_PASSWORD production

vercel --prod
```

The build will print a URL like `https://hastlefam-<hash>-miordanus-projects.vercel.app` and alias `https://hastlefam.vercel.app`.

## Post-deploy verification

```bash
# Health (no auth)
curl https://hastlefam.vercel.app/health
# → {"status":"ok"}

# Login page (no auth required)
curl -I https://hastlefam.vercel.app/login
# → 200; HTML contains the telegram-widget.js script tag

# Protected endpoint without cookie → 302 to /login (HTML) or 401 (JSON)
curl -i https://hastlefam.vercel.app/finance/report/data?household_id=ed36b994-81e3-4fa0-b860-205381ba4681
# → HTTP/2 302  location: /login

curl -i -H "Accept: application/json" \
  https://hastlefam.vercel.app/finance/report/data?household_id=ed36b994-81e3-4fa0-b860-205381ba4681
# → HTTP/2 401
```

Then in a browser:

1. Open `https://hastlefam.vercel.app/login`
2. Click "Log in with Telegram", confirm in your Telegram app
3. Land on `/finance/report?household_id=...` — dashboard renders, Cashflow tab works
4. DevTools → Application → Cookies — confirm `hf_session` has `HttpOnly`, `Secure`, `SameSite=Lax`

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 500 on /finance/report | Missing `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` env vars on Vercel | `vercel env ls production`; add and redeploy |
| 500 with `Invalid schema: hastlefam` | Schema not exposed | Supabase Dashboard → Settings → API → Exposed schemas → add `hastlefam` → save → wait ~10s → `NOTIFY pgrst, 'reload config';` via SQL editor |
| 500 with `permission denied for schema hastlefam` | service_role grants missing | Re-run the grants migration (see `migrations/`) |
| 500 with `Could not find function hastlefam.monthly_totals` | RPC not applied to this project | Re-run the `monthly_totals` migration via Supabase MCP `apply_migration` |
| 302 → /login on every request, even after logging in | `SESSION_SECRET` mismatch between deployments, or cookie blocked because Vercel preview deployment uses a different hostname than the BotFather-registered domain | Confirm `SESSION_SECRET` is set in the active environment; log in via the exact production domain registered with BotFather |
| Telegram widget shows "Bot domain invalid" | BotFather `/setdomain` not done, or done for wrong hostname | `/setdomain` in @BotFather; send the bare hostname (no `https://`, no path) |
| `/auth/telegram/callback` → 403 "user not allowed" | No matching active row in `hastlefam.users` for that `telegram_id` | Insert a row with the correct numeric `telegram_id` and `is_active=true` |
| `/auth/telegram/callback` → 401 "invalid telegram signature" | `TELEGRAM_BOT_TOKEN` on Vercel doesn't match the bot serving the widget | Re-add the same token used by the bot worker |
| Hero balance shows 0 | Snapshot date filter excludes start-of-month snapshots — see app/application/services/finance_service.py:monthly_report_via_rest snapshot filter | Should be `lt.{start_dt + 1 day}` |
| Slow first request | Vercel cold start (Python lambda) | First hit takes 2–4s; subsequent hits <500ms within the same instance lifetime |

## Rolling back

```bash
vercel ls           # list deployments
vercel promote <prev-deployment-url> --scope=miordanus-projects
```

Or just `vercel --prod` again from a known-good commit.

## What's NOT covered by this deploy

- Telegram bot — still runs locally / on Railway (different service, different Procfile entry)
- Alembic migrations — apply via Supabase MCP or `manual_apply.sql` in Supabase SQL editor, not via Vercel
- Cron / scheduled jobs (recurring reminders, daily digest) — those need a process runner; Vercel cron is an alternative but not configured here

## Future hardening

- Add `vercel.json` `headers` block for `Cache-Control` on the dashboard route (currently fresh on every load)
- Consider a custom domain (`vercel domains add yourdomain.com`)
- Add Vercel logs alerting on 5xx
