{{
  config(
    materialized   = 'incremental',
    unique_key     = ['coin_id', 'price_date'],
    partition_by   = {'field': 'price_date', 'data_type': 'date'},
    cluster_by     = ['coin_id'],
    on_schema_change = 'fail'
  )
}}

WITH rolling AS (
  SELECT
    coin_id,
    price_date,
    open_usd,
    high_usd,
    low_usd,
    close_usd,
    volume_usd,
    market_cap_usd,
    prev_close_usd,
    daily_return_pct,
    sma_7d,
    sma_30d,
    return_stddev_7d,
    return_stddev_30d,
    cummax_close,
    annualised_volatility_30d
  FROM {{ ref('int_prices__rolling_metrics') }}
  {% if is_incremental() %}
    WHERE price_date > (SELECT MAX(price_date) FROM {{ this }})
  {% endif %}
)

SELECT
  coin_id,
  price_date,
  open_usd,
  high_usd,
  low_usd,
  close_usd,
  volume_usd,
  market_cap_usd,
  prev_close_usd,
  daily_return_pct,
  sma_7d,
  sma_30d,
  return_stddev_7d,
  return_stddev_30d,
  cummax_close,
  annualised_volatility_30d,

  -- Drawdown from running ATH
  SAFE_DIVIDE(close_usd - cummax_close, cummax_close) * 100 AS drawdown_from_ath_pct,

  -- Price deviation from 7d SMA (momentum signal)
  SAFE_DIVIDE(close_usd - sma_7d, sma_7d) * 100 AS price_vs_sma7_pct
FROM rolling
