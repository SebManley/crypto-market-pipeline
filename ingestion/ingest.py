"""
ingest.py

CLI orchestrator for the crypto-market-pipeline ingestion.
Reads coin list from dbt/seeds/coin_watchlist.csv, fetches data from CoinGecko,
and upserts to BigQuery raw dataset.

Usage:
  python -m ingestion.ingest                          # incremental (last 2 days)
  python -m ingestion.ingest --full-refresh           # full history ('max' days)
  python -m ingestion.ingest --coins bitcoin ethereum # specific coins only
  python -m ingestion.ingest --dry-run                # print rows, no BQ writes
"""

import argparse
import csv
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from ingestion.bigquery_loader import BigQueryLoader
from ingestion.coingecko import CoinGeckoClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

WATCHLIST_PATH = Path(__file__).parent.parent / 'dbt' / 'seeds' / 'coin_watchlist.csv'
INCREMENTAL_DAYS = 2
OHLC_DAYS = 30


def load_watchlist(path: Path) -> list[str]:
  with open(path, newline='') as f:
    return [row['coin_id'] for row in csv.DictReader(f)]


def parse_market_chart(coin_id: str, data: dict, fetched_at: datetime) -> list[dict]:
  prices     = {int(ts): v for ts, v in data.get('prices', [])}
  volumes    = {int(ts): v for ts, v in data.get('total_volumes', [])}
  market_caps = {int(ts): v for ts, v in data.get('market_caps', [])}
  fetched_date = fetched_at.date().isoformat()

  rows = []
  for ts_ms, close in prices.items():
    price_date = date.fromtimestamp(ts_ms / 1000).isoformat()
    rows.append({
      'coin_id':        coin_id,
      'price_date':     price_date,
      'open_usd':       None,
      'high_usd':       None,
      'low_usd':        None,
      'close_usd':      close,
      'volume_usd':     volumes.get(ts_ms),
      'market_cap_usd': market_caps.get(ts_ms),
      'fetched_date':   fetched_date,
      'fetched_at':     fetched_at.isoformat(),
    })
  return rows


def merge_ohlc(price_rows: list[dict], ohlc_data: list[list]) -> list[dict]:
  """Merge OHLC candles into price rows keyed by price_date."""
  ohlc_by_date = {}
  for candle in ohlc_data:
    ts_ms, open_, high, low, close = candle
    d = date.fromtimestamp(ts_ms / 1000).isoformat()
    ohlc_by_date[d] = (open_, high, low, close)

  for row in price_rows:
    candle = ohlc_by_date.get(row['price_date'])
    if candle:
      row['open_usd'], row['high_usd'], row['low_usd'], _ = candle
  return price_rows


def parse_coin_metadata(coin_id: str, data: dict, fetched_at: datetime) -> dict:
  market = data.get('market_data', {})
  ath_date_raw = market.get('ath_date', {}).get('usd')
  genesis_raw  = data.get('genesis_date')

  ath_date = None
  if ath_date_raw:
    try:
      ath_date = datetime.fromisoformat(ath_date_raw.rstrip('Z')).date().isoformat()
    except ValueError:
      pass

  return {
    'coin_id':      coin_id,
    'name':         data.get('name'),
    'symbol':       data.get('symbol'),
    'genesis_date': genesis_raw,
    'ath_usd':      market.get('ath', {}).get('usd'),
    'ath_date':     ath_date,
    'fetched_at':   fetched_at.isoformat(),
  }


def run(
  coins: list[str],
  full_refresh: bool,
  dry_run: bool,
  project_id: str,
  raw_dataset: str,
  api_key: str | None,
) -> None:
  client = CoinGeckoClient(api_key=api_key)
  days = 365 if full_refresh else INCREMENTAL_DAYS
  fetched_at = datetime.now(timezone.utc)

  all_price_rows: list[dict] = []
  all_metadata_rows: list[dict] = []

  for coin_id in coins:
    log.info('Fetching %s (days=%s) ...', coin_id, days)
    try:
      chart = client.fetch_market_chart(coin_id, days=days)
      price_rows = parse_market_chart(coin_id, chart, fetched_at)

      try:
        ohlc = client.fetch_ohlc(coin_id, days=OHLC_DAYS)
        price_rows = merge_ohlc(price_rows, ohlc)
      except Exception as e:
        log.warning('OHLC fetch failed for %s: %s — skipping OHLC merge', coin_id, e)

      all_price_rows.extend(price_rows)
      log.info('  -> %d price rows', len(price_rows))

      meta_raw = client.fetch_coin_info(coin_id)
      all_metadata_rows.append(parse_coin_metadata(coin_id, meta_raw, fetched_at))

    except Exception as e:
      log.error('Failed to fetch %s: %s', coin_id, e)
      continue

  log.info('Total: %d price rows, %d metadata rows', len(all_price_rows), len(all_metadata_rows))

  if dry_run:
    log.info('[DRY RUN] Would write %d price rows and %d metadata rows — no BQ writes performed.',
             len(all_price_rows), len(all_metadata_rows))
    for row in all_price_rows[:3]:
      log.info('  Sample price row: %s', row)
    return

  loader = BigQueryLoader(project_id=project_id, raw_dataset=raw_dataset)
  loader.ensure_tables_exist()
  loader.upsert_prices(all_price_rows, full_refresh=full_refresh)
  loader.upsert_coin_metadata(all_metadata_rows)
  log.info('Ingestion complete.')


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--full-refresh', action='store_true',
                      help='Fetch full history for all coins (days=max).')
  parser.add_argument('--dry-run', action='store_true',
                      help='Fetch data and print rows, but do not write to BigQuery.')
  parser.add_argument('--coins', nargs='+', metavar='COIN',
                      help='Override coin list (default: read from coin_watchlist.csv).')
  args = parser.parse_args()

  project_id = os.environ['GCP_PROJECT_ID']
  raw_dataset = os.environ.get('BQ_RAW_DATASET', 'raw')
  api_key     = os.environ.get('COINGECKO_API_KEY') or None

  coins = args.coins or load_watchlist(WATCHLIST_PATH)
  run(
    coins=coins,
    full_refresh=args.full_refresh,
    dry_run=args.dry_run,
    project_id=project_id,
    raw_dataset=raw_dataset,
    api_key=api_key,
  )


if __name__ == '__main__':
  main()
