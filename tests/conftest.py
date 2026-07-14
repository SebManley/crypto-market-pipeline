"""Shared pytest fixtures for ingestion tests."""

import pytest
import responses as responses_lib

MOCK_COIN_ID = 'bitcoin'
MOCK_FETCHED_AT = '2024-01-15T06:00:00+00:00'

MOCK_MARKET_CHART = {
  'prices': [
    [1704931200000, 42000.0],
    [1705017600000, 43000.0],
    [1705104000000, 41500.0],
  ],
  'market_caps': [
    [1704931200000, 820_000_000_000.0],
    [1705017600000, 840_000_000_000.0],
    [1705104000000, 810_000_000_000.0],
  ],
  'total_volumes': [
    [1704931200000, 15_000_000_000.0],
    [1705017600000, 18_000_000_000.0],
    [1705104000000, 12_000_000_000.0],
  ],
}

MOCK_OHLC = [
  [1704931200000, 41800.0, 42500.0, 41200.0, 42000.0],
  [1705017600000, 42100.0, 43800.0, 41900.0, 43000.0],
  [1705104000000, 43100.0, 43200.0, 41000.0, 41500.0],
]

MOCK_COIN_INFO = {
  'id': 'bitcoin',
  'name': 'Bitcoin',
  'symbol': 'btc',
  'genesis_date': '2009-01-03',
  'market_data': {
    'ath': {'usd': 73738.0},
    'ath_date': {'usd': '2024-03-14T07:10:36.635Z'},
  },
}


@pytest.fixture
def mock_coingecko():
  """Activate responses mock context and register standard endpoints."""
  with responses_lib.RequestsMock() as rsps:
    rsps.add(
      responses_lib.GET,
      f'https://api.coingecko.com/api/v3/coins/{MOCK_COIN_ID}/market_chart',
      json=MOCK_MARKET_CHART,
      status=200,
    )
    rsps.add(
      responses_lib.GET,
      f'https://api.coingecko.com/api/v3/coins/{MOCK_COIN_ID}/ohlc',
      json=MOCK_OHLC,
      status=200,
    )
    rsps.add(
      responses_lib.GET,
      f'https://api.coingecko.com/api/v3/coins/{MOCK_COIN_ID}',
      json=MOCK_COIN_INFO,
      status=200,
    )
    yield rsps


@pytest.fixture
def mock_bq_client(mocker):
  """Patch google.cloud.bigquery.Client with a MagicMock."""
  mock_client = mocker.MagicMock()
  mock_client.get_dataset.return_value = mocker.MagicMock()
  mock_client.get_table.return_value = mocker.MagicMock()
  mock_client.load_table_from_json.return_value.result.return_value = None
  mock_client.query.return_value.result.return_value = None
  mock_client.delete_table.return_value = None
  mocker.patch('ingestion.bigquery_loader.bigquery.Client', return_value=mock_client)
  return mock_client
