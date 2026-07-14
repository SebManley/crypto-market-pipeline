# crypto-market-pipeline

Portfolio project: CoinGecko REST API → Python ingestion → BigQuery → dbt → Streamlit dashboard.

## Stack
- **Source**: CoinGecko free API (no auth required)
- **Ingestion**: Python 3.12, `requests`, `tenacity`, `google-cloud-bigquery`
- **Warehouse**: Google BigQuery (free tier)
- **Transforms**: dbt-bigquery 1.8, dbt-utils
- **Dashboard**: Streamlit Community Cloud (live public URL)
- **CI/CD**: GitHub Actions (daily cron ingest + dbt slim CI on PRs)

## Directory structure

```
crypto-market-pipeline/
├── .github/workflows/
│   ├── ci.yml               # dbt slim CI on PRs
│   └── ingest.yml           # daily cron: ingest → dbt run → dbt test → freshness
├── .streamlit/
│   └── config.toml
├── dbt/
│   ├── dbt_project.yml
│   ├── packages.yml         # dbt-utils
│   ├── profiles.yml.example
│   ├── macros/generate_schema_name.sql
│   ├── seeds/coin_watchlist.csv
│   ├── models/
│   │   ├── staging/         # views, QUALIFY dedup
│   │   ├── intermediate/    # window functions (LAG, rolling SMA)
│   │   └── marts/           # fct_daily_prices (incremental), fct_coin_volatility, dim_coins
│   └── tests/assert_price_positive.sql
├── ingestion/
│   ├── coingecko.py         # CoinGeckoClient with tenacity retry
│   ├── bigquery_loader.py   # MERGE-based idempotent upsert
│   └── ingest.py            # CLI: --full-refresh, --dry-run, --coins
├── tests/                   # pytest with mocked HTTP + BQ
├── dashboard/app.py         # Streamlit 4-page app
├── .env.example
├── requirements.txt
└── requirements-dev.txt
```

## BigQuery datasets
- `raw` — written by Python ingestion only
  - `raw.prices` — partitioned by `fetched_date`, clustered by `coin_id`
  - `raw.coin_metadata`
- `analytics` — owned by dbt (staging views, intermediate views, mart tables)
- `analytics_ci` — CI workflow target only

## Local dev setup
```bash
cp .env.example .env
# fill in GCP_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
cd dbt && dbt deps
python -m ingestion.ingest --dry-run
pytest tests/
cd dbt && dbt build
streamlit run dashboard/app.py
```

## Running ingestion
```bash
python -m ingestion.ingest --full-refresh     # backfill all history
python -m ingestion.ingest                    # incremental (last 2 days)
python -m ingestion.ingest --coins bitcoin ethereum  # specific coins only
python -m ingestion.ingest --dry-run          # print rows, no BQ write
```

## Key conventions
- All ingestion is idempotent via BigQuery MERGE on (coin_id, price_date)
- dbt incremental models use unique_key=['coin_id','price_date'] — safe to re-run
- Coin watchlist in `dbt/seeds/coin_watchlist.csv` is the single source of truth
- No secrets committed — keyfile path via GOOGLE_APPLICATION_CREDENTIALS env var
