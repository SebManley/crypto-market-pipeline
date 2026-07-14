WITH source AS (
  SELECT
    coin_id,
    CAST(price_date    AS DATE)      AS price_date,
    CAST(open_usd      AS FLOAT64)   AS open_usd,
    CAST(high_usd      AS FLOAT64)   AS high_usd,
    CAST(low_usd       AS FLOAT64)   AS low_usd,
    CAST(close_usd     AS FLOAT64)   AS close_usd,
    CAST(volume_usd    AS FLOAT64)   AS volume_usd,
    CAST(market_cap_usd AS FLOAT64)  AS market_cap_usd,
    CAST(fetched_date  AS DATE)      AS fetched_date,
    CAST(fetched_at    AS TIMESTAMP) AS fetched_at
  FROM {{ source('crypto_raw', 'prices') }}
  WHERE close_usd IS NOT NULL
    AND close_usd > 0
),

deduped AS (
  SELECT *
  FROM source
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY coin_id, price_date
    ORDER BY fetched_at DESC
  ) = 1
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
  fetched_date,
  fetched_at
FROM deduped
