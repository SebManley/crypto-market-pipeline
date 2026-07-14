WITH source AS (
  SELECT
    coin_id,
    name,
    symbol,
    CAST(genesis_date AS DATE)      AS genesis_date,
    CAST(ath_usd      AS FLOAT64)   AS ath_usd,
    CAST(ath_date     AS DATE)      AS ath_date,
    CAST(fetched_at   AS TIMESTAMP) AS fetched_at
  FROM {{ source('crypto_raw', 'coin_metadata') }}
  WHERE coin_id IS NOT NULL
),

deduped AS (
  SELECT *
  FROM source
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY coin_id
    ORDER BY fetched_at DESC
  ) = 1
)

SELECT
  coin_id,
  name,
  symbol,
  genesis_date,
  ath_usd,
  ath_date,
  fetched_at
FROM deduped
