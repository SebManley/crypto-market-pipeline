WITH prices AS (
  SELECT
    coin_id,
    price_date,
    open_usd,
    high_usd,
    low_usd,
    close_usd,
    volume_usd,
    market_cap_usd
  FROM {{ ref('stg_crypto__prices') }}
),

with_returns AS (
  SELECT
    *,
    LAG(close_usd) OVER (
      PARTITION BY coin_id
      ORDER BY price_date
    ) AS prev_close_usd,

    SAFE_DIVIDE(
      close_usd - LAG(close_usd) OVER (PARTITION BY coin_id ORDER BY price_date),
      LAG(close_usd) OVER (PARTITION BY coin_id ORDER BY price_date)
    ) * 100 AS daily_return_pct
  FROM prices
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
  daily_return_pct
FROM with_returns
