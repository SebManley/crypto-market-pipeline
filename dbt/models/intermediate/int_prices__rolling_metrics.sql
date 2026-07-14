WITH daily_returns AS (
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
    daily_return_pct
  FROM {{ ref('int_prices__daily_returns') }}
),

with_rolling AS (
  SELECT
    *,

    -- Simple moving averages
    AVG(close_usd) OVER (
      PARTITION BY coin_id
      ORDER BY price_date
      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS sma_7d,

    AVG(close_usd) OVER (
      PARTITION BY coin_id
      ORDER BY price_date
      ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS sma_30d,

    -- Rolling return standard deviations
    STDDEV(daily_return_pct) OVER (
      PARTITION BY coin_id
      ORDER BY price_date
      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS return_stddev_7d,

    STDDEV(daily_return_pct) OVER (
      PARTITION BY coin_id
      ORDER BY price_date
      ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS return_stddev_30d,

    -- Cumulative max for drawdown calculation
    MAX(close_usd) OVER (
      PARTITION BY coin_id
      ORDER BY price_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cummax_close
  FROM daily_returns
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
  -- Annualised volatility from 30d daily return stddev (sqrt(365))
  return_stddev_30d * SQRT(365) AS annualised_volatility_30d
FROM with_rolling
