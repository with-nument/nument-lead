# Data and outreach policy

What Nument Leads may collect, how it collects it, how long it keeps it, and how people stay in control of
their data. These rules come from the founder's decisions of 12 Nov 2026 (`IMPLEMENTATION_PLAN.md`, A.4) and
are enforced in code (Step 18). When this page and the plan disagree, the plan's reconciled rules (A.13.5)
win; this page is updated in the same change.

- [Sources](#sources)
- [How the code enforces it](#how-the-code-enforces-it)
- [Personal data](#personal-data)
- [Retention](#retention)
- [Deletion requests](#deletion-requests)
- [Opt-outs and wrong contacts](#opt-outs-and-wrong-contacts)
- [Google Places terms](#google-places-terms)
- [Country rules](#country-rules)
- [Sending on WhatsApp](#sending-on-whatsapp)
- [Security](#security)

## Sources

**Allowed**
- Public pages and official APIs.
- Grey-area pages whose terms discourage robots (today: Apna job pages), only at a slow rate, with an honest
  User-Agent, obeying robots.txt path rules, and stopping when blocked.
- Search-engine results that mention LinkedIn or X posts. The snippet is read; the page itself is never opened.

Each source, its pace and what the first live check measured: [sources.md](sources.md).

**Never**
- Logging in to any third-party site, or using fake accounts.
- Solving or bypassing CAPTCHAs.
- Proxies, IP rotation, residential proxy networks, or any other way around a block.
- Faking an app identity, or calling private or undocumented APIs.
- Fetching linkedin.com, x.com, twitter.com, instagram.com, facebook.com (including the Meta Ad Library) or
  any other host on the never-fetch list below.
- Buying data from brokers, leaked lists, Truecaller-style lookups, or guessing phone numbers.

## How the code enforces it

Every request goes through one module, `engine/src/nument_engine/http.py`. Sources, research and pipeline code
never open their own HTTP client; a test fails the build if they do.

| Rule | Enforcement |
|---|---|
| Never-fetch hosts | Refused before any connection: linkedin.com, x.com, twitter.com, instagram.com, facebook.com, fb.com, threads.net, tiktok.com, web.whatsapp.com, wa.me, api.whatsapp.com, truecaller.com, justdial.com, reddit.com, indiamart.com, sulekha.com, and their subdomains. WhatsApp links are built for the founder to open, never fetched |
| robots.txt | Read once per host per run. Our product token `NumentLeadBot` first, then `*`. 401 or 403 means the whole host is off limits; 404 means allowed; a disallowed page is skipped and recorded |
| Honest identity | `User-Agent: NumentLeadBot/1.0 (+https://nument.in)` on every request, including the browser used for script-heavy pages. Never a browser User-Agent, never rotated |
| Pace | Business websites 2 seconds per host and 8 pages per business a night; registries 3 seconds; Practo 5 seconds; grey sources 6 seconds; official APIs at their documented limits |
| Stop when blocked | 401, 403, 429, 503 or a challenge page raises `SourceBlocked`: the source rests 24 hours, then 72 hours, then 7 days for repeated blocks in 30 days, and a blocked business website is skipped for the rest of the run. Two blocks in 7 days switch a grey source off until the founder turns it back on |
| No proxies | The HTTP client ignores proxy settings in the environment and has no proxy configured; a test checks it |
| No evasion tools | CI fails if a CAPTCHA solver, stealth plugin, proxy-rotation service or private-API scraper appears in the dependencies |

Kill switches, all on the app's Engine page:

| Switch | Effect |
|---|---|
| `settings.sources_enabled[source]` | The source does nothing |
| `source_health.enabled` | Same; set by the engine after repeated blocks, or by the founder |
| `settings.segments_enabled[segment]` | No new research or leads for that segment |
| `settings.providers_enabled[provider]` | The AI router skips that provider and uses the fallbacks |
| Disabling a GitHub workflow | Nothing runs (emergency stop) |

## Personal data

India's DPDP Act exempts personal data that the person made public, but the engine still keeps it minimal
and purposeful.

| Stored | Never stored |
|---|---|
| Business name, website, address, and phones and emails the business published | Personal mobiles that the person did not publish for the business |
| The decision maker's name and role as written on the business's own pages | Photos, date of birth, home address, family details |
| Quotes from the business's own pages and job posts | Anything from personal social profiles |
| Derived flags from Google reviews ("reviews mention unanswered calls") | Review text or reviewer names |

Phones: only numbers the business published itself. First choice is its own website; the fallback is its
own Google listing, shown as "from Google listing".

## Retention

Applied by `nlead health --prune` (the monthly workflow; `--dry-run` counts only). The reconciled rule A.13.5
(13) sets the page text periods, which are shorter than Step 18.2.2 to fit the 500 MB free database.

| Data | Kept for | Then |
|---|---|---|
| Page text of businesses that did not become leads | 30 days | Text deleted; URL, hash and date kept |
| Page rows of businesses that did not become leads | 90 days | Row deleted; facts keep their quote and URL |
| Page text of businesses that became leads | 90 days | Text deleted; the row stays |
| Any page text | 20,000 characters | Trimmed |
| Google Places rating and review count | 30 days after the fetch | Set to null unless refreshed; `place_id` stays |
| Phones from a Google listing | 30 days unless re-verified | Deleted (do-not-contact rows stay) |
| Pages of golden-set businesses | While labelled | Never pruned: evals depend on them |
| Facts and signals | While the business exists | Deleted with the business |
| Suppression list | Forever | Never deleted: it is what keeps people from being contacted again |
| Leads and activities | At least 2 years (learning) | Archived or deleted on request |
| Costs and runs | 1 year | Deleted |
| Expired AI cache entries | Until they expire | Deleted |

## Deletion requests

1. The founder opens the lead and clicks **Forget this business** (admin only).
2. The engine deletes the business's contacts, facts, pages, signals, scores, leads, activities, feedback and
   source records.
3. It adds the business's phones, emails and web domain to `suppression` with reason `forget_request`, so the
   business is never collected again.
4. It writes one `runs` row of kind `manual` recording that a deletion happened, with no personal data in it.
5. Reply to the requester within 7 days.

## Opt-outs and wrong contacts

- Marking a lead **Wrong contact**, or a reply such as "stop" or "do not message", adds the phone (E.164) to
  `suppression`. If the business itself asked to stop, its web domain is added too.
- **Do not contact** in the app writes to `suppression` and sets `contacts.do_not_contact`.
- Suppression is checked three times: by the pre-filter, by the message writer, and again just before a lead
  reaches the sheet or the app.

## Google Places terms

1. Only `place_id` is stored permanently.
2. Rating, review count, phone and website are refreshed at most every 30 days and nulled by the prune job
   when they are older.
3. Review text and reviewer names are never stored. The `review_pain` signal stores a derived description and
   the Google Maps link for the place.
4. Wherever the app shows a Google rating, it says "Google" next to it.
5. Only the official Places API (New) is used. The Maps scraper stays off.

## Country rules

Guidance for a non-lawyer. Get a short legal check before enabling any wave 2 or wave 3 country, and record
the outreach channel and compliance notes in that country's segment files.

| Country | Main law | What it means here | Before enabling |
|---|---|---|---|
| India | DPDP Act 2023 and Rules 2025 | Public data is exempt, but stay minimal; honour deletion and opt-outs | A privacy page on nument.in names a contact for data requests |
| UAE | Federal Decree-Law 45 of 2021; DIFC and ADGM have their own laws | Consent is the main basis, with exceptions; keep B2B data minimal; honour opt-outs fast | Check whether DIFC or ADGM firms need extra steps |
| Saudi Arabia | Personal Data Protection Law | Consent based; strict rules on moving data out of the Kingdom | Legal check on cross-border transfer |
| Qatar | Law 13 of 2016 | Electronic marketing generally needs prior consent | Legal check; prefer email to a business address with an easy opt-out |
| UK | UK GDPR and PECR | Cold email to corporate addresses is allowed with identity and opt-out; sole traders need consent | Legitimate interests assessment; ICO fee and representative |
| Singapore | PDPA and the Do Not Call registry | Business contact information is largely exempt; marketing to Singapore numbers is checked against the DNC registry | Plan DNC checks |
| US | TCPA, CAN-SPAM, state laws | No automated calls or texts without consent; email needs identity, address and an opt-out | Email first; no SMS; legal check on state rules |
| Australia | Privacy Act, Spam Act 2003 | Commercial messages need consent and an unsubscribe | Legal check; likely email only to published business addresses |

## Sending on WhatsApp

The engine never sends. These rules protect the sender's number:

1. Send one by one from the WhatsApp Business app or WhatsApp Web. Never broadcast lists or bulk tools.
2. Start at 30 new chats a day per number. If almost nobody blocks or reports for a week, add about 10 a day
   each week, up to about 80 a day.
3. Send 10:00 to 12:00 or 15:00 to 17:00 in the recipient's time zone; not on Sundays or their public
   holidays (Friday afternoons are quiet in the Gulf).
4. Use the business profile: Nument logo, description and website.
5. If messages go undelivered for days or WhatsApp warns about the account, stop new chats for 48 hours and
   record it in [incidents.md](incidents.md).
6. At most two follow-ups (the day 3 and day 7 drafts), and only if the first message was delivered.
7. Anyone who asks to stop goes to **Do not contact** at once.

## Security

| Secret | Lives in | Never in |
|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | GitHub Actions secrets, Render server environment | Browser code, `NEXT_PUBLIC_` variables, the repository |
| `DATABASE_URL`, `DEV_DATABASE_URL` | GitHub Actions secrets, local env files | The repository, logs |
| `GEMINI_API_KEY`, `GEMINI_API_KEY_BACKUP`, `OPENAI_API_KEY`, `GOOGLE_MAPS_API_KEY` | GitHub Actions secrets, local env files | The repository, the web app |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | GitHub Actions secret | The repository; locally `GOOGLE_SERVICE_ACCOUNT_FILE` points outside it |
| `GH_DISPATCH_TOKEN` | Render server environment | Browser code |
| `BACKUP_PASSPHRASE` | GitHub Actions secret, plus a printed copy kept safely by the founder | Anywhere else |
| `RESEND_API_KEY` (optional) | GitHub Actions secret | The repository |

- Env files and key files are ignored by git. gitleaks scans the whole history in CI on every push, and
  `pre-commit install` adds the same scan before every local commit.
- Logs never print keys, full phone numbers or full emails; settings hold secrets as types that never print.
- Row Level Security is on for every table. The engine uses the service role; the web app uses the signed-in
  user's session. Roles: `admin` (everything), `caller` (no money, no costs, no settings), `viewer` (read only).
  Sign-ups are off; only an admin creates users.
- Two-factor authentication on GitHub, Supabase, Render, Google Cloud, Google AI Studio and OpenAI.
- Dependabot checks Python, npm and GitHub Actions dependencies; actions are pinned to commit SHAs.

| When | What |
|---|---|
| Monthly | Review app users and roles |
| Quarterly | Rotate the AI, Maps and service-account keys; renew `GH_DISPATCH_TOKEN`; test a backup restore |
| On any leak | Follow [incidents.md](incidents.md) |
