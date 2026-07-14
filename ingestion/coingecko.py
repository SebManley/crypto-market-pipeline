"""
coingecko.py

CoinGecko REST API client. Fetches OHLCV + market chart data for a list of coins.
No API key required for free tier (10 req/min); pass api_key to raise limit to 50 req/min.

Usage:
  client = CoinGeckoClient()
  prices = client.fetch_market_chart('bitcoin', days=30)
  ohlc   = client.fetch_ohlc('bitcoin', days=30)
"""

import logging
import time
from typing import Optional

import requests
from tenacity import (
  retry,
  retry_if_exception_type,
  stop_after_attempt,
  wait_exponential,
)

log = logging.getLogger(__name__)

BASE_URL = 'https://api.coingecko.com/api/v3'
FREE_TIER_INTERVAL_SECONDS = 6.5  # ~9 req/min, safely under 10 req/min limit


class RateLimitError(Exception):
  pass


def _is_retryable(exc: BaseException) -> bool:
  if isinstance(exc, requests.HTTPError):
    return exc.response is not None and exc.response.status_code in (429, 500, 502, 503, 504)
  return isinstance(exc, (requests.ConnectionError, requests.Timeout))


class CoinGeckoClient:
  def __init__(self, api_key: Optional[str] = None) -> None:
    self._session = requests.Session()
    self._last_call = 0.0
    if api_key:
      self._session.headers['x-cg-demo-api-key'] = api_key
      self._interval = 1.5  # 50 req/min with key
    else:
      self._interval = FREE_TIER_INTERVAL_SECONDS

  def _throttle(self) -> None:
    elapsed = time.monotonic() - self._last_call
    if elapsed < self._interval:
      time.sleep(self._interval - elapsed)
    self._last_call = time.monotonic()

  @retry(
    retry=retry_if_exception_type((requests.HTTPError, requests.ConnectionError, requests.Timeout)),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
  )
  def _get(self, path: str, params: dict) -> dict | list:
    self._throttle()
    url = f'{BASE_URL}{path}'
    log.debug('GET %s %s', url, params)
    resp = self._session.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

  def fetch_market_chart(self, coin_id: str, days: int | str) -> dict:
    """
    Returns {prices: [[ts_ms, price], ...], market_caps: [...], total_volumes: [...]}.
    days='max' returns full history; integer days returns daily granularity for days > 90.
    """
    return self._get(
      f'/coins/{coin_id}/market_chart',
      params={'vs_currency': 'usd', 'days': days, 'interval': 'daily'},
    )

  def fetch_ohlc(self, coin_id: str, days: int) -> list[list]:
    """
    Returns [[ts_ms, open, high, low, close], ...] OHLC candles.
    days must be one of: 1, 7, 14, 30, 90, 180, 365.
    """
    return self._get(
      f'/coins/{coin_id}/ohlc',
      params={'vs_currency': 'usd', 'days': days},
    )

  def fetch_coin_info(self, coin_id: str) -> dict:
    """Returns coin metadata: name, symbol, genesis_date, market_data (ATH etc.)."""
    return self._get(
      f'/coins/{coin_id}',
      params={
        'localization': 'false',
        'tickers': 'false',
        'community_data': 'false',
        'developer_data': 'false',
      },
    )
