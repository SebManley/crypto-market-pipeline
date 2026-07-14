WITH watchlist AS (
  SELECT
    coin_id,
    name      AS watchlist_name,
    symbol    AS watchlist_symbol,
    category
  FROM {{ ref('coin_watchlist') }}
),

metadata AS (
  SELECT
    coin_id,
    name,
    symbol,
    genesis_date,
    ath_usd,
    ath_date,
    fetched_at
  FROM {{ ref('stg_crypto__coin_metadata') }}
),

latest_price AS (
  SELECT
    coin_id,
    MAX(price_date) AS latest_price_date,
    -- Latest close on the most recent date
    MAX_BY(close_usd, price_date)      AS latest_close_usd,
    MAX_BY(market_cap_usd, price_date) AS latest_market_cap_usd,
    COUNT(DISTINCT price_date)         AS days_of_data
  FROM {{ ref('stg_crypto__prices') }}
  GROUP BY coin_id
)

SELECT
  w.coin_id,
  COALESCE(m.name, w.watchlist_name)     AS name,
  COALESCE(m.symbol, w.watchlist_symbol) AS symbol,
  w.category,
  m.genesis_date,
  DATE_DIFF(CURRENT_DATE(), m.genesis_date, DAY) AS days_since_genesis,
  m.ath_usd,
  m.ath_date,
  p.latest_price_date,
  p.latest_close_usd,
  p.latest_market_cap_usd,
  p.days_of_data,
  m.fetched_at AS metadata_fetched_at
FROM watchlist w
LEFT JOIN metadata      m USING (coin_id)
LEFT JOIN latest_price  p USING (coin_id)
