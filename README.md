# crypto-market-pipeline

![Daily Ingest](https://github.com/SebManley/crypto-market-pipeline/actions/workflows/ingest.yml/badge.svg)
![CI](https://github.com/SebManley/crypto-market-pipeline/actions/workflows/ci.yml/badge.svg)
![dbt](https://img.shields.io/badge/dbt-1.8-orange)
![BigQuery](https://img.shields.io/badge/BigQuery-free--tier-4285F4)
[![Streamlit](https://img.shields.io/badge/Streamlit-live-FF4B4B)](https://crypto-market-pipeline-djijorlqysm2rh7p7v5pxg.streamlit.app)

A production-quality data pipeline tracking 10 cryptocurrencies via the CoinGecko API.
Demonstrates the patterns I apply to every client engagement: cloud warehouse ingestion,
dbt model layering with window functions, idempotent loads, comprehensive testing, and a live dashboard.

**Live dashboard →** [crypto-market-pipeline-djijorlqysm2rh7p7v5pxg.streamlit.app](https://crypto-market-pipeline-djijorlqysm2rh7p7v5pxg.streamlit.app)

---

## What this project demonstrates

| Pattern | Where |
|---|---|
| REST API ingestion with retry + rate limiting | `ingestion/coingecko.py` — tenacity backoff on 429/5xx |
| Cloud warehouse loading (BigQuery free tier) | `ingestion/bigquery_loader.py` — MERGE-based idempotent upserts |
| dbt staging → intermediate → mart layering | `dbt/models/` — QUALIFY dedup, LAG returns, rolling SMA |
| Incremental dbt model (partition + cluster) | `fct_daily_prices.sql` — unique_key merge on (coin_id, price_date) |
| Window functions in intermediate layer | `int_prices__rolling_metrics.sql` — 7d/30d SMA, stddev, cummax |
| dbt-utils generic + singular tests | `_marts.yml`, `tests/assert_price_positive.sql` |
| Source freshness monitoring | `_sources.yml` — warn after 1 day, error after 2 days |
| Mocked pytest suite (no real API/BQ calls) | `tests/` — responses mock + unittest.mock for BigQuery |
| GitHub Actions daily cron + slim CI | `.github/workflows/` — ingest + dbt run/test/freshness |
| Live public dashboard | `dashboard/app.py` — Streamlit 4-page app on Community Cloud |

---

## Architecture

```
CoinGecko REST API (free, no auth required)
  ↓  Python ingestion (requests, tenacity, google-cloud-bigquery)
  ↓  BigQuery raw dataset
        raw.prices           — partitioned by fetched_date, clustered by coin_id
        raw.coin_metadata
  ↓  dbt-bigquery
        staging/             — deduplicated views (QUALIFY pattern)
        intermediate/        — LAG daily returns, 7d/30d SMA + stddev, cummax
        marts/               — fct_daily_prices (incremental), fct_coin_volatility, dim_coins
  ↓  BigQuery analytics dataset
  ↓  Streamlit Community Cloud (live public URL)
        queries BigQuery via service account in st.secrets
```

Scheduled by GitHub Actions cron at 06:00 UTC daily.
CI on PRs runs dbt slim CI (changed models + downstream only).

---

## dbt Model Lineage

```
raw.prices ──────────────► stg_crypto__prices ──────► int_prices__daily_returns ──► int_prices__rolling_metrics ──► fct_daily_prices (incremental)
                                                                                                                  └──► fct_coin_volatility
raw.coin_metadata ────────► stg_crypto__coin_metadata ──────────────────────────────────────────────────────────► dim_coins
seeds.coin_watchlist ──────────────────────────────────────────────────────────────────────────────────────────► dim_coins
```

---

## Quick start

### Prerequisites
- Python 3.12+
- A Google Cloud project with BigQuery enabled (free tier: 10 GB storage, 1 TB queries/month)

### 1. Clone and configure

```bash
git clone https://github.com/SebManley/crypto-market-pipeline.git
cd crypto-market-pipeline

cp .env.example .env
# edit .env: set GCP_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS
```

### 2. Set up Python environment

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 3. Configure dbt profile

```bash
cp dbt/profiles.yml.example ~/.dbt/profiles.yml
# edit ~/.dbt/profiles.yml: set your GCP project ID
```

### 4. Run tests

```bash
pytest tests/ -v
```

### 5. Ingest data

```bash
# Initial full backfill (fetches full price history for all 10 coins)
python -m ingestion.ingest --full-refresh

# Subsequent incremental runs (last 2 days)
python -m ingestion.ingest

# Dry run (prints rows, no BigQuery writes)
python -m ingestion.ingest --dry-run
```

### 6. Run dbt models

```bash
cd dbt
dbt deps
dbt seed          # loads coin_watchlist.csv
dbt build         # staging → intermediate → marts + all tests
dbt source freshness
```

### 7. Run the dashboard locally

```bash
streamlit run dashboard/app.py
# open http://localhost:8501
```

---

## BigQuery setup

These commands provision everything the pipeline needs.

```bash
# 1. Create the project (or use an existing one)
gcloud projects create YOUR_PROJECT_ID

# 2. Enable BigQuery
gcloud services enable bigquery.googleapis.com --project=YOUR_PROJECT_ID

# 3. Create a service account
gcloud iam service-accounts create crypto-pipeline \
  --display-name="crypto-market-pipeline" \
  --project=YOUR_PROJECT_ID

# 4. Grant the minimum required roles
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:crypto-pipeline@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:crypto-pipeline@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"

# 5. Generate the keyfile (run this in Google Cloud Shell)
gcloud iam service-accounts keys create gcp_keyfile.json \
  --iam-account=crypto-pipeline@YOUR_PROJECT_ID.iam.gserviceaccount.com

# The ingestion script auto-creates the 'raw' dataset and tables on first run.
# dbt creates 'analytics' and 'analytics_ci' datasets automatically.
```

**Downloading the keyfile from Cloud Shell:**
Cloud Shell creates `gcp_keyfile.json` in its own Linux filesystem, not on your local machine.
To get it locally, click the **⋮ menu → Download** in the Cloud Shell toolbar and enter `gcp_keyfile.json` as the path.
This downloads a zip containing the Cloud Shell home directory — extract just `gcp_keyfile.json` from it and place it in the project root:

```
crypto-market-pipeline/
└── gcp_keyfile.json   ← goes here (already in .gitignore — never commit this)
```

---

## GitHub Actions secrets

Add these to your repository's **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID |
| `GCP_SERVICE_ACCOUNT_JSON` | Full contents of `gcp_keyfile.json` |
| `COINGECKO_API_KEY` | Optional — raises free tier rate limit from 10 to 50 req/min |

---

## Streamlit Community Cloud deployment

1. Push the repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
3. Set **Main file path** to `dashboard/app.py`
4. Under **Advanced settings → Secrets**, add:

```toml
gcp_project_id = "your-gcp-project-id"

[gcp_service_account]
type = "service_account"
project_id = "your-gcp-project-id"
private_key_id = "..."
private_key = "-----BEGIN RSA PRIVATE KEY-----\n..."
client_email = "crypto-pipeline@your-gcp-project-id.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
```

---

## Coins tracked

10 coins spanning L1 protocols and DeFi:

| Coin | CoinGecko ID | Category |
|---|---|---|
| Bitcoin | `bitcoin` | Layer 1 |
| Ethereum | `ethereum` | Layer 1 |
| Solana | `solana` | Layer 1 |
| BNB | `binancecoin` | Layer 1 |
| XRP | `ripple` | Layer 1 |
| Cardano | `cardano` | Layer 1 |
| Avalanche | `avalanche-2` | Layer 1 |
| Chainlink | `chainlink` | DeFi |
| Uniswap | `uniswap` | DeFi |
| Polkadot | `polkadot` | Layer 1 |

To change the watchlist, edit `dbt/seeds/coin_watchlist.csv` and re-run `dbt seed`.
The ingestion script reads this file as its coin list automatically.

---

## Project structure

```
crypto-market-pipeline/
├── .github/workflows/
│   ├── ci.yml               # pytest + dbt slim CI on PRs
│   └── ingest.yml           # daily cron: ingest → dbt → test → freshness
├── .streamlit/config.toml   # dark theme
├── dbt/
│   ├── dbt_project.yml
│   ├── packages.yml         # dbt-utils
│   ├── profiles.yml.example
│   ├── macros/generate_schema_name.sql
│   ├── seeds/coin_watchlist.csv
│   ├── models/
│   │   ├── staging/         # stg_crypto__prices, stg_crypto__coin_metadata
│   │   ├── intermediate/    # int_prices__daily_returns, int_prices__rolling_metrics
│   │   └── marts/           # fct_daily_prices, fct_coin_volatility, dim_coins
│   └── tests/assert_price_positive.sql
├── ingestion/
│   ├── coingecko.py
│   ├── bigquery_loader.py
│   └── ingest.py
├── tests/
│   ├── conftest.py
│   ├── test_coingecko.py
│   └── test_bigquery_loader.py
├── dashboard/app.py
├── .env.example
├── requirements.txt
└── requirements-dev.txt
```

---

## Schema layout

| Dataset | Contains | Materialization |
|---|---|---|
| `raw` | Python-loaded source tables | physical tables |
| `analytics` | All dbt models (staging views, int views, mart tables) | view / incremental |
| `analytics_ci` | CI-only dataset for PR validation | same as analytics |
