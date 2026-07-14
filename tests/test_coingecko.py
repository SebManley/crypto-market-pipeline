"""Unit tests for ingestion/coingecko.py using mocked HTTP responses."""

import pytest
import responses as responses_lib
import requests

from ingestion.coingecko import CoinGeckoClient
from tests.conftest import MOCK_COIN_ID, MOCK_MARKET_CHART, MOCK_OHLC, MOCK_COIN_INFO


class TestFetchMarketChart:
  def test_returns_expected_structure(self, mock_coingecko):
    client = CoinGeckoClient()
    result = client.fetch_market_chart(MOCK_COIN_ID, days=30)

    assert 'prices' in result
    assert 'total_volumes' in result
    assert 'market_caps' in result
    assert len(result['prices']) == 3

  def test_price_values_are_floats(self, mock_coingecko):
    client = CoinGeckoClient()
    result = client.fetch_market_chart(MOCK_COIN_ID, days=30)

    for ts_ms, price in result['prices']:
      assert isinstance(price, float)
      assert price > 0

  def test_passes_vs_currency_param(self, mock_coingecko):
    client = CoinGeckoClient()
    client.fetch_market_chart(MOCK_COIN_ID, days=7)

    req = mock_coingecko.calls[0].request
    assert 'vs_currency=usd' in req.url


class TestFetchOhlc:
  def test_returns_list_of_candles(self, mock_coingecko):
    client = CoinGeckoClient()
    result = client.fetch_ohlc(MOCK_COIN_ID, days=30)

    assert isinstance(result, list)
    assert len(result) == 3

  def test_candle_has_five_fields(self, mock_coingecko):
    client = CoinGeckoClient()
    result = client.fetch_ohlc(MOCK_COIN_ID, days=30)

    for candle in result:
      assert len(candle) == 5
      ts_ms, open_, high, low, close = candle
      assert high >= low
      assert open_ > 0
      assert close > 0


class TestFetchCoinInfo:
  def test_returns_name_and_symbol(self, mock_coingecko):
    client = CoinGeckoClient()
    result = client.fetch_coin_info(MOCK_COIN_ID)

    assert result['name'] == 'Bitcoin'
    assert result['symbol'] == 'btc'
    assert result['genesis_date'] == '2009-01-03'

  def test_market_data_present(self, mock_coingecko):
    client = CoinGeckoClient()
    result = client.fetch_coin_info(MOCK_COIN_ID)

    assert result['market_data']['ath']['usd'] == 73738.0


class TestRetryBehaviour:
  @responses_lib.activate
  def test_retries_on_429_then_succeeds(self):
    responses_lib.add(
      responses_lib.GET,
      f'https://api.coingecko.com/api/v3/coins/{MOCK_COIN_ID}/market_chart',
      status=429,
    )
    responses_lib.add(
      responses_lib.GET,
      f'https://api.coingecko.com/api/v3/coins/{MOCK_COIN_ID}/market_chart',
      json=MOCK_MARKET_CHART,
      status=200,
    )

    client = CoinGeckoClient()
    result = client.fetch_market_chart(MOCK_COIN_ID, days=1)
    assert 'prices' in result
    assert len(responses_lib.calls) == 2

  @responses_lib.activate
  def test_raises_after_max_retries(self):
    for _ in range(5):
      responses_lib.add(
        responses_lib.GET,
        f'https://api.coingecko.com/api/v3/coins/{MOCK_COIN_ID}/market_chart',
        status=500,
      )

    client = CoinGeckoClient()
    with pytest.raises(requests.HTTPError):
      client.fetch_market_chart(MOCK_COIN_ID, days=1)


class TestParseMarketChart:
  def test_parse_market_chart_row_count(self):
    from datetime import datetime, timezone
    from ingestion.ingest import parse_market_chart

    fetched_at = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    rows = parse_market_chart(MOCK_COIN_ID, MOCK_MARKET_CHART, fetched_at)

    assert len(rows) == 3

  def test_parse_market_chart_fields_present(self):
    from datetime import datetime, timezone
    from ingestion.ingest import parse_market_chart

    fetched_at = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    rows = parse_market_chart(MOCK_COIN_ID, MOCK_MARKET_CHART, fetched_at)

    for row in rows:
      assert row['coin_id'] == MOCK_COIN_ID
      assert row['close_usd'] > 0
      assert row['price_date'] is not None
      assert row['fetched_date'] is not None

  def test_parse_market_chart_empty_input(self):
    from datetime import datetime, timezone
    from ingestion.ingest import parse_market_chart

    fetched_at = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    rows = parse_market_chart(MOCK_COIN_ID, {'prices': [], 'total_volumes': [], 'market_caps': []}, fetched_at)

    assert rows == []

  def test_parse_market_chart_null_volume(self):
    from datetime import datetime, timezone
    from ingestion.ingest import parse_market_chart

    data = {
      'prices': [[1704931200000, 42000.0]],
      'total_volumes': [],
      'market_caps': [],
    }
    fetched_at = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    rows = parse_market_chart(MOCK_COIN_ID, data, fetched_at)

    assert rows[0]['volume_usd'] is None
    assert rows[0]['market_cap_usd'] is None
