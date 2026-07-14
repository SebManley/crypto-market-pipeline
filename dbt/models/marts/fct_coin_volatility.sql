WITH daily AS (
  SELECT
    coin_id,
    price_date,
    close_usd,
    daily_return_pct,
    volume_usd,
    market_cap_usd,
    annualised_volatility_30d
  FROM {{ ref('fct_daily_prices') }}
),

-- First and last close per (coin_id, week) for weekly return
weekly_bounds AS (
  SELECT
    coin_id,
    DATE_TRUNC(price_date, WEEK) AS week_start,
    MIN(CASE WHEN price_date = min_date THEN close_usd END) AS week_open,
    MIN(CASE WHEN price_date = max_date THEN close_usd END) AS week_close
  FROM (
    SELECT
      *,
      MIN(price_date) OVER (PARTITION BY coin_id, DATE_TRUNC(price_date, WEEK)) AS min_date,
      MAX(price_date) OVER (PARTITION BY coin_id, DATE_TRUNC(price_date, WEEK)) AS max_date
    FROM daily
  )
  GROUP BY coin_id, week_start
),

weekly_agg AS (
  SELECT
    coin_id,
    DATE_TRUNC(price_date, WEEK)              AS week_start,
    MIN(close_usd)                            AS weekly_low,
    MAX(close_usd)                            AS weekly_high,
    AVG(close_usd)                            AS weekly_avg_close,
    SUM(volume_usd)                           AS weekly_volume,
    AVG(market_cap_usd)                       AS avg_market_cap,
    STDDEV(daily_return_pct)                  AS weekly_return_stddev,
    STDDEV(daily_return_pct) * SQRT(52)       AS annualised_volatility_weekly,
    AVG(annualised_volatility_30d)            AS avg_annualised_volatility_30d,
    COUNT(*)                                  AS trading_days
  FROM daily
  GROUP BY coin_id, week_start
)

SELECT
  a.coin_id,
  a.week_start,
  a.weekly_low,
  a.weekly_high,
  a.weekly_avg_close,
  a.weekly_volume,
  a.avg_market_cap,
  a.weekly_return_stddev,
  a.annualised_volatility_weekly,
  a.avg_annualised_volatility_30d,
  a.trading_days,
  SAFE_DIVIDE(b.week_close - b.week_open, b.week_open) * 100 AS weekly_return_pct
FROM weekly_agg a
LEFT JOIN weekly_bounds b USING (coin_id, week_start)
