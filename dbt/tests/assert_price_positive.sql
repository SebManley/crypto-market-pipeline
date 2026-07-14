-- Singular test: fail if any close_usd is zero or negative in the mart.
-- This should never happen given upstream source tests, but acts as a final guard.
SELECT
  coin_id,
  price_date,
  close_usd
FROM {{ ref('fct_daily_prices') }}
WHERE close_usd <= 0
