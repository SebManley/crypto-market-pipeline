"""Unit tests for ingestion/bigquery_loader.py using a mocked BigQuery client."""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

from ingestion.bigquery_loader import BigQueryLoader


SAMPLE_PRICE_ROWS = [
  {
    'coin_id':        'bitcoin',
    'price_date':     '2024-01-15',
    'open_usd':       41800.0,
    'high_usd':       42500.0,
    'low_usd':        41200.0,
    'close_usd':      42000.0,
    'volume_usd':     15_000_000_000.0,
    'market_cap_usd': 820_000_000_000.0,
    'fetched_date':   '2024-01-15',
    'fetched_at':     '2024-01-15T06:00:00+00:00',
  },
  {
    'coin_id':        'ethereum',
    'price_date':     '2024-01-15',
    'open_usd':       2200.0,
    'high_usd':       2350.0,
    'low_usd':        2180.0,
    'close_usd':      2300.0,
    'volume_usd':     8_000_000_000.0,
    'market_cap_usd': 276_000_000_000.0,
    'fetched_date':   '2024-01-15',
    'fetched_at':     '2024-01-15T06:00:00+00:00',
  },
]

SAMPLE_METADATA_ROWS = [
  {
    'coin_id':      'bitcoin',
    'name':         'Bitcoin',
    'symbol':       'btc',
    'genesis_date': '2009-01-03',
    'ath_usd':      73738.0,
    'ath_date':     '2024-03-14',
    'fetched_at':   '2024-01-15T06:00:00+00:00',
  },
]


@pytest.fixture
def loader():
  with patch('ingestion.bigquery_loader.bigquery.Client') as MockClient:
    mock_client = MagicMock()
    mock_client.get_dataset.return_value = MagicMock()
    mock_client.get_table.return_value = MagicMock()
    mock_client.load_table_from_json.return_value.result.return_value = None
    mock_client.query.return_value.result.return_value = None
    mock_client.delete_table.return_value = None
    MockClient.return_value = mock_client

    bq = BigQueryLoader(project_id='test-project', raw_dataset='raw')
    bq.client = mock_client
    yield bq


class TestEnsureTablesExist:
  def test_skips_dataset_creation_when_dataset_exists(self, loader):
    loader.ensure_tables_exist()
    loader.client.create_dataset.assert_not_called()

  def test_creates_dataset_when_missing(self, loader):
    loader.client.get_dataset.side_effect = Exception('not found')
    loader.ensure_tables_exist()
    loader.client.create_dataset.assert_called_once()

  def test_skips_table_creation_when_tables_exist(self, loader):
    loader.ensure_tables_exist()
    loader.client.create_table.assert_not_called()

  def test_creates_tables_when_missing(self, loader):
    loader.client.get_table.side_effect = Exception('not found')
    loader.ensure_tables_exist()
    assert loader.client.create_table.call_count == 2


class TestUpsertPrices:
  def test_calls_load_and_merge_and_cleanup(self, loader):
    loader.upsert_prices(SAMPLE_PRICE_ROWS)

    loader.client.load_table_from_json.assert_called_once()
    loader.client.query.assert_called_once()
    loader.client.delete_table.assert_called_once()

  def test_merge_sql_references_correct_tables(self, loader):
    loader.upsert_prices(SAMPLE_PRICE_ROWS)

    merge_sql = loader.client.query.call_args[0][0]
    assert 'test-project.raw.prices' in merge_sql
    assert 'MERGE' in merge_sql
    assert 'coin_id' in merge_sql
    assert 'price_date' in merge_sql

  def test_returns_row_count(self, loader):
    count = loader.upsert_prices(SAMPLE_PRICE_ROWS)
    assert count == 2

  def test_empty_rows_short_circuits(self, loader):
    count = loader.upsert_prices([])
    loader.client.load_table_from_json.assert_not_called()
    assert count == 0

  def test_idempotent_on_duplicate_rows(self, loader):
    rows = SAMPLE_PRICE_ROWS + SAMPLE_PRICE_ROWS  # double-write same rows
    loader.upsert_prices(rows)
    # MERGE handles dedup — we just assert it still only runs one query
    assert loader.client.query.call_count == 1


class TestUpsertCoinMetadata:
  def test_calls_load_and_merge(self, loader):
    loader.upsert_coin_metadata(SAMPLE_METADATA_ROWS)

    loader.client.load_table_from_json.assert_called_once()
    loader.client.query.assert_called_once()

  def test_merge_sql_merges_on_coin_id(self, loader):
    loader.upsert_coin_metadata(SAMPLE_METADATA_ROWS)

    merge_sql = loader.client.query.call_args[0][0]
    assert 'test-project.raw.coin_metadata' in merge_sql
    assert 'T.coin_id = S.coin_id' in merge_sql

  def test_empty_rows_short_circuits(self, loader):
    count = loader.upsert_coin_metadata([])
    loader.client.load_table_from_json.assert_not_called()
    assert count == 0
