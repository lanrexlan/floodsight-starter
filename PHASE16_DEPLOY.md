# Phase 16 Deployment — Resident SMS Alerts

All code is written and registered. This guide activates the live
infrastructure (Supabase database, Twilio SMS, Render env vars, cron job).
Estimated time: **30–45 minutes**.

---

## Step 1 — Supabase: create project and apply schema

1. Go to **https://supabase.com** → New project.
   - Name: `floodsight-pilot`
   - Region: **West Europe (eu-west-1)** — lowest latency to Nigeria from free-tier options.
   - Password: save it somewhere; you won't need it directly.
   - Free tier (500 MB, 2 CPU) is sufficient for the pilot.

2. Wait ~2 minutes for the project to initialise.

3. In the Supabase dashboard → **SQL Editor** → New query.  
   Paste the contents of **`scripts/sql/01_subscribers.sql`** → Run.  
   You should see: `CREATE TABLE`, `CREATE UNIQUE INDEX`, `ALTER TABLE` — all success.

4. **Dashboard → Settings → API** — copy:
   - **Project URL** → `SUPABASE_URL`
   - **service_role** secret key → `SUPABASE_KEY`  
     ⚠️ Use `service_role`, NOT the `anon` key. The service role bypasses RLS so
     the API can write subscriber rows and log alerts.

---

## Step 2 — Africa's Talking: create account and get API key

Africa's Talking has direct connections to MTN, Airtel, Glo, and 9mobile —
~10× cheaper than Twilio for Nigerian SMS (~₦5–15/SMS vs ~₦160 with Twilio).

1. Sign up at **https://account.africastalking.com** (free; sandbox is instant).

2. After login → **Settings → API Key** — generate and copy your API key.
   - Your **username** is shown on the dashboard (top-right).
   - For testing: use `AT_USERNAME=sandbox` and the sandbox API key.
   - For production: switch to your real username and live API key.

3. **Optional — register a Sender ID**:
   - Go to **SMS → Sender IDs → Request** and apply for `FloodSight` as a
     custom sender name. This replaces the shared shortcode (e.g. `AT-FLDSGT`).
   - Approval takes 1–2 business days in Nigeria.
   - If you skip this for now, set `AT_SENDER_ID=` (blank) to use AT's shared pool.

4. **Test in sandbox**:
   - Add your number to the **sandbox simulator** in the AT dashboard so you can
     receive test messages before going live.

AT credentials to copy:
   - Your username → `AT_USERNAME`
   - Your API key → `AT_API_KEY`
   - Your sender ID (or blank) → `AT_SENDER_ID`

---

## Step 3 — Generate a DISPATCH_SECRET

Run once locally (or in any Python shell):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output — you'll use it in Render and in cron-job.org.

---

## Step 4 — Render: add environment variables

Go to **https://dashboard.render.com** → your `floodsight-starter` service
→ **Environment** → Add the following key/value pairs:

| Key | Value |
|-----|-------|
| `SUPABASE_URL` | `https://your-project-id.supabase.co` |
| `SUPABASE_KEY` | service_role secret key |
| `AT_USERNAME` | your Africa's Talking username (or `sandbox` for testing) |
| `AT_API_KEY` | your Africa's Talking API key |
| `AT_SENDER_ID` | `FloodSight` (or blank to use AT shared pool) |
| `DISPATCH_SECRET` | the hex string from Step 3 |

Click **Save Changes** — Render will redeploy automatically (~60 seconds).

---

## Step 5 — Smoke test the endpoints

Once Render is green, run these against the live API:

```bash
BASE=https://floodsight-starter.onrender.com

# 1. Subscriber count (should return 0 initially)
curl "$BASE/subscribers/count"
# → {"active_subscribers": 0}

# 2. Subscribe a test number (use your own verified Twilio number)
curl -X POST "$BASE/subscribe" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+2348012345678","lat":6.5820,"lon":3.4080,"area_name":"Kosofe"}'
# → {"status":"subscribed","phone":"+2348012345678","risk_class":"High","area_name":"Kosofe"}

# 3. Check subscriber count again
curl "$BASE/subscribers/count"
# → {"active_subscribers": 1}

# 4. Trigger a dispatch (replace YOUR_SECRET)
curl -X POST "$BASE/alerts/dispatch" \
  -H "Authorization: Bearer YOUR_SECRET"
# → {"highest_alert":"...","dispatched":0,"skipped":1,"errors":0,"subscribers":1,...}
# (skipped=1 is correct if no Watch/Warning is active today)
```

---

## Step 6 — Set up the hourly cron job

The `/alerts/dispatch` endpoint needs to run automatically every hour.
Use **cron-job.org** (free, no install required):

1. Sign up at **https://cron-job.org**
2. New cronjob:
   - **URL**: `https://floodsight-starter.onrender.com/alerts/dispatch`
   - **Schedule**: Every hour (`:00`)
   - **HTTP method**: POST
   - **Request headers**:
     ```
     Authorization: Bearer YOUR_DISPATCH_SECRET
     Content-Type: application/json
     ```
   - **Request body**: *(leave empty)*
3. Save and enable.

cron-job.org will email you if the endpoint returns a non-200 status —
useful for catching if Render's free tier spins down and times out.

**Alternative**: Render Cron Jobs (paid) or GitHub Actions scheduled workflow.

---

## Step 7 — Verify the public form works

Open **https://www.rankineinnovationlab.com/floodsight.html** and scroll to
the "Get Early Warnings" section. Fill in a test phone number and location,
click Subscribe. Then:

```bash
curl https://floodsight-starter.onrender.com/subscribers/count
```

Confirm the count increases. Check your Supabase dashboard → Table Editor →
`subscribers` to see the row.

---

## Environment variable reference

All variables are in `.env.example`. For local testing, copy to `.env`:

```bash
cp .env.example .env
# edit .env with real credentials
```

The API reads them via `python-dotenv` when running locally:
```bash
uvicorn api.main:app --reload --port 8000
```

On Render, env vars are set in the dashboard (Step 4) — `.env` is never
uploaded to GitHub (it's in `.gitignore`).

---

## Supabase table structure (reference)

```sql
subscribers   -- phone (UNIQUE), lat/lon, area_name, risk_class, active
alert_log     -- subscriber_id, alert_level, event_date (UNIQUE per day)
```

To view subscribers on Supabase: Dashboard → Table Editor → subscribers.  
To manually trigger a test alert log entry (for debugging):

```sql
-- Supabase SQL Editor
SELECT * FROM subscribers WHERE active = TRUE;
SELECT * FROM alert_log ORDER BY sent_at DESC LIMIT 20;
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/subscribe` returns 503 | SUPABASE_URL or SUPABASE_KEY not set | Check Render env vars |
| `/alerts/dispatch` returns 401 | Wrong Authorization header | Check DISPATCH_SECRET matches |
| `/alerts/dispatch` returns 503 | AT_USERNAME or AT_API_KEY missing | Add to Render env |
| SMS sends but recipient gets nothing | Using sandbox credentials in production | Switch AT_USERNAME to your real username + live API key |
| `dispatch` returns `dispatched:0, skipped:N` | No Watch/Warning active today | Normal behaviour — alerts only go out when thresholds are crossed |
| Supabase upsert fails | Using anon key instead of service_role | Re-copy service_role key |
