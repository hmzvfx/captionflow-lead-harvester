# Captionflow Lead Harvester

Incremental public lead discovery for Captionflow. The system discovers creator/business prospects, normalizes and deduplicates them, applies deterministic qualification, crawls a small number of allowed public pages for **publicly exposed** contact emails, and upserts the result into Google Sheets.

It **does not send email**, does not run outreach campaigns, does not guess email patterns, does not bypass authentication/CAPTCHAs/anti-bot controls, and does not require a paid lead/enrichment API or OpenAI.

## What it does

`DISCOVERY → NORMALIZATION → DEDUPLICATION → QUALIFICATION → PUBLIC ENRICHMENT → VERIFIED PUBLIC EMAIL IF OBSERVED → GOOGLE SHEETS`

Providers are extensible and currently include:

- **YouTube** — free YouTube Data API quota; expensive `search.list` is bounded, query-rotated and cached through state.
- **Public Web / Seeds** — explicit public seed URLs, respecting robots rules.
- **RSS/Atom** — configured public feeds.
- **Sitemaps** — configured public sitemaps.

Instagram/TikTok links can be stored when they are publicly exposed by a source, but this project does not pretend unrestricted mass scraping of those platforms is reliable or free.

## Architecture

```text
src/captionflow_harvester/
  providers/       YouTube, web, RSS, sitemap, seed providers
  discovery/       query expansion, normalization, deduplication
  qualification/   deterministic scoring/rules
  enrichment/      bounded website crawl, email extraction/evidence
  persistence/     Google Sheets + checkpoint/state
  runtime/         budgets, async HTTP, workers, metrics, redacted logging
  pipeline.py      incremental orchestration
```

State is persisted in a hidden `SYSTEM_STATE` sheet so scheduled GitHub Actions runs continue from prior query offsets/tokens and checkpoints instead of starting from zero.

## Google Cloud setup

Recommended authentication is **GitHub Actions OIDC / Workload Identity Federation**, not a downloaded JSON key.

1. Enable the Google Sheets API in the Google Cloud project.
2. Create a service account and give that service account edit access to the target Google Sheet (share the Sheet with its service-account email).
3. Create a Workload Identity Pool/provider for GitHub and restrict the provider to this repository: `hmzvfx/captionflow-lead-harvester`.
4. Allow the GitHub principal to impersonate the service account with `roles/iam.workloadIdentityUser`.
5. Put the provider resource name and service-account email into the GitHub secrets listed below.

The workflows use `google-github-actions/auth@v2`, which exposes Application Default Credentials to the Python Google client automatically. No service-account JSON belongs in the repository.

## GitHub secrets

| NAME | TYPE | REQUIRED | DEFAULT | PURPOSE |
|---|---|---:|---|---|
| `YOUTUBE_API_KEY` | Secret | Recommended | none | YouTube discovery using the free YouTube Data API quota |
| `GOOGLE_SPREADSHEET_ID` | Secret | Yes for Sheets | none | Existing Google Sheet to bootstrap/upsert |
| `GOOGLE_WORKLOAD_IDENTITY_PROVIDER` | Secret | Yes in Actions | none | Full Workload Identity Provider resource name |
| `GOOGLE_SERVICE_ACCOUNT_EMAIL` | Secret | Yes in Actions | none | Service account impersonated by GitHub OIDC |

At least one discovery source must exist: YouTube key and/or one of the public `PUBLIC_*` variables.

## GitHub variables

| NAME | TYPE | REQUIRED | DEFAULT | PURPOSE |
|---|---|---:|---:|---|
| `WORKER_COUNT` | Variable | No | `20` | Bounded async concurrency; does not increase quotas |
| `TARGET_LANGUAGES` | Variable | No | `fr` | Comma-separated target languages |
| `TARGET_COUNTRIES` | Variable | No | `BE,FR,CA,CH` | Comma-separated target country codes |
| `TARGET_NICHES` | Variable | No | `business,fitness,marketing,coaching,real_estate,finance` | Query/scoring niches |
| `CREATOR_TYPES` | Variable | No | `coach,consultant,formateur,entrepreneur,creator,podcast` | Query-expansion creator intents |
| `MIN_SUBSCRIBERS` | Variable | No | `500` | Lower audience-fit bound |
| `MAX_SUBSCRIBERS` | Variable | No | `500000` | Upper audience-fit bound |
| `RECENT_DAYS` | Variable | No | `45` | Recent-activity window |
| `MIN_SCORE` | Variable | No | `55` | Minimum score written to leads |
| `HOT_SCORE` | Variable | No | `80` | HOT threshold |
| `GOOD_SCORE` | Variable | No | `65` | GOOD threshold |
| `POSSIBLE_SCORE` | Variable | No | `50` | POSSIBLE threshold |
| `TARGET_PROSPECTS_PER_RUN` | Variable | No | `500` | Goal/cap, never a guaranteed result count |
| `MAX_YOUTUBE_REQUESTS_PER_RUN` | Variable | No | `20` | Total YouTube API request cap/run |
| `MAX_YOUTUBE_SEARCH_REQUESTS_PER_RUN` | Variable | No | `3` | Expensive `search.list` request cap/run |
| `MAX_WEBSITES_PER_RUN` | Variable | No | `120` | Domains allowed for enrichment/run |
| `MAX_PAGES_PER_DOMAIN` | Variable | No | `5` | Max relevant public pages/domain |
| `MAX_ENRICHMENTS_PER_RUN` | Variable | No | `120` | Qualified leads allowed into web enrichment |
| `MAX_RUNTIME_MINUTES` | Variable | No | `40` | Internal runtime ceiling |
| `MAX_PAGE_BYTES` | Variable | No | `1500000` | Max downloaded bytes/page |
| `HTTP_TIMEOUT_SECONDS` | Variable | No | `12` | HTTP timeout |
| `PER_HOST_DELAY_SECONDS` | Variable | No | `0.6` | Polite delay between requests to the same host |
| `PUBLIC_SEED_URLS` | Variable | No | empty | Comma-separated public creator/business seed URLs |
| `PUBLIC_FEED_URLS` | Variable | No | empty | Comma-separated public RSS/Atom feeds |
| `PUBLIC_SITEMAP_URLS` | Variable | No | empty | Comma-separated public sitemap URLs |

`LLM_ENABLED` remains false in the workflow and the core pipeline has no OpenAI requirement.

## Bootstrap Sheet

In GitHub:

**Actions → Initialize Captionflow Lead Sheet → Run workflow**

The bootstrap is non-destructive. It creates only these harvester-owned tabs if missing:

1. `LEADS`
2. `HOT LEADS`
3. `NO EMAIL`
4. `STATS`
5. hidden `SYSTEM_STATE`

It writes headers only when empty, applies dark header formatting, freezes row 1, adds filtering/status validation, and hides technical state. If a same-named sheet already contains incompatible headers, the command stops rather than silently deleting data.

## Run manually

After bootstrap:

**Actions → Captionflow Lead Harvest → Run workflow**

Each run uploads `reports/run_<id>.json` as a GitHub Actions artifact. The report includes candidate/lead/email counts, request counts, retries, 429s, errors, and efficiency ratios.

## Automatic schedule

`harvest.yml` runs once per hour at minute 17. GitHub concurrency prevents overlapping harvest runs. State stored in the Sheet rotates queries and preserves YouTube page tokens/checkpoints between runs.

## How to read the Sheet

- **LEADS** — canonical one-row-per-prospect table. Existing rows are updated by stable Lead ID; manual `Status` is preserved.
- **HOT LEADS** — derived shortlist of `Classification = HOT`, sorted toward verified email + highest score.
- **NO EMAIL** — qualified prospects for which no reliable public email was observed.
- **STATS** — totals, daily/new counts, source/niche/language/country breakdowns and last-run metrics.
- **SYSTEM_STATE** — hidden machine state; do not edit unless debugging.

Email status `VERIFIED_PUBLIC_SOURCE` means the exact address was actually observed on a public source. The system does not construct `firstname@domain` guesses.

## Troubleshooting

- **Google 403**: verify the Sheet is shared with `GOOGLE_SERVICE_ACCOUNT_EMAIL`, Sheets API is enabled, and the GitHub OIDC principal has `roles/iam.workloadIdentityUser` on that service account.
- **YouTube 403/quota**: the current default allocation includes 100 `search.list` calls/day; the default here is 3/hour (max 72/day). Lower `MAX_YOUTUBE_SEARCH_REQUESTS_PER_RUN` if your project quota differs.
- **No leads**: broaden niches/languages, add public seed/feed/sitemap sources, or lower `MIN_SCORE` carefully.
- **Few emails**: expected when creators do not publish one. `NO EMAIL` is intentionally retained rather than inventing addresses.
- **Sheet header conflict**: rename the incompatible old tab or align it manually; bootstrap refuses destructive resets.
- **429s**: reduce concurrency and/or increase `PER_HOST_DELAY_SECONDS`.

## Local validation

```bash
python -m pip install -e ".[dev]"
pytest
captionflow-harvester validate-config
```

No network is used by unit tests.
