"""
bigquery_loader.py

Idempotent BigQuery loader. Writes raw price and metadata rows via MERGE statements
so the pipeline is safe to re-run without duplicating data.

Usage:
  loader = BigQueryLoader(project_id='my-project')
  loader.ensure_tables_exist()
  loader.upsert_prices(rows)
  loader.upsert_coin_metadata(rows)
"""

import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

from google.cloud import bigquery
from google.oauth2 import service_account

log = logging.getLogger(__name__)

PRICES_SCHEMA = [
  bigquery.SchemaField('coin_id',       'STRING',    mode='REQUIRED'),
  bigquery.SchemaField('price_date',    'DATE',      mode='REQUIRED'),
  bigquery.SchemaField('open_usd',      'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('high_usd',      'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('low_usd',       'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('close_usd',     'FLOAT64',   mode='REQUIRED'),
  bigquery.SchemaField('volume_usd',    'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('market_cap_usd','FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('fetched_date',  'DATE',      mode='REQUIRED'),
  bigquery.SchemaField('fetched_at',    'TIMESTAMP', mode='REQUIRED'),
]

METADATA_SCHEMA = [
  bigquery.SchemaField('coin_id',       'STRING',    mode='REQUIRED'),
  bigquery.SchemaField('name',          'STRING',    mode='NULLABLE'),
  bigquery.SchemaField('symbol',        'STRING',    mode='NULLABLE'),
  bigquery.SchemaField('genesis_date',  'DATE',      mode='NULLABLE'),
  bigquery.SchemaField('ath_usd',       'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('ath_date',      'DATE',      mode='NULLABLE'),
  bigquery.SchemaField('fetched_at',    'TIMESTAMP', mode='REQUIRED'),
]


class BigQueryLoader:
  def __init__(
    self,
    project_id: str,
    raw_dataset: str = 'raw',
    credentials_path: Optional[str] = None,
  ) -> None:
    self.project_id = project_id
    self.raw_dataset = raw_dataset

    if credentials_path:
      creds = service_account.Credentials.from_service_account_file(credentials_path)
      self.client = bigquery.Client(project=project_id, credentials=creds)
    else:
      self.client = bigquery.Client(project=project_id)

  def _table_ref(self, table: str) -> str:
    return f'{self.project_id}.{self.raw_dataset}.{table}'

  def ensure_tables_exist(self) -> None:
    dataset_ref = bigquery.DatasetReference(self.project_id, self.raw_dataset)
    try:
      self.client.get_dataset(dataset_ref)
    except Exception:
      dataset = bigquery.Dataset(dataset_ref)
      dataset.location = 'US'
      self.client.create_dataset(dataset)
      log.info('Created dataset %s.%s', self.project_id, self.raw_dataset)

    self._ensure_table(
      'prices',
      PRICES_SCHEMA,
      partition_field='fetched_date',
      cluster_fields=['coin_id'],
    )
    self._ensure_table('coin_metadata', METADATA_SCHEMA)

  def _ensure_table(
    self,
    table_name: str,
    schema: list,
    partition_field: Optional[str] = None,
    cluster_fields: Optional[list] = None,
  ) -> None:
    ref = self._table_ref(table_name)
    try:
      self.client.get_table(ref)
      log.debug('Table %s already exists.', ref)
    except Exception:
      table = bigquery.Table(ref, schema=schema)
      if partition_field:
        table.time_partitioning = bigquery.TimePartitioning(field=partition_field)
      if cluster_fields:
        table.clustering_fields = cluster_fields
      self.client.create_table(table)
      log.info('Created table %s', ref)

  def upsert_prices(self, rows: list[dict]) -> int:
    if not rows:
      return 0
    temp_table = f'{self._table_ref("prices")}_tmp_{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}'
    job_config = bigquery.LoadJobConfig(schema=PRICES_SCHEMA, write_disposition='WRITE_TRUNCATE')
    self.client.load_table_from_json(rows, temp_table, job_config=job_config).result()

    merge_sql = f"""
      MERGE `{self._table_ref('prices')}` T
      USING `{temp_table}` S
        ON T.coin_id = S.coin_id AND T.price_date = S.price_date
      WHEN MATCHED THEN UPDATE SET
        open_usd       = S.open_usd,
        high_usd       = S.high_usd,
        low_usd        = S.low_usd,
        close_usd      = S.close_usd,
        volume_usd     = S.volume_usd,
        market_cap_usd = S.market_cap_usd,
        fetched_date   = S.fetched_date,
        fetched_at     = S.fetched_at
      WHEN NOT MATCHED THEN INSERT ROW
    """
    self.client.query(merge_sql).result()
    self.client.delete_table(temp_table, not_found_ok=True)
    log.info('Upserted %d price rows', len(rows))
    return len(rows)

  def upsert_coin_metadata(self, rows: list[dict]) -> int:
    if not rows:
      return 0
    temp_table = f'{self._table_ref("coin_metadata")}_tmp_{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}'
    job_config = bigquery.LoadJobConfig(schema=METADATA_SCHEMA, write_disposition='WRITE_TRUNCATE')
    self.client.load_table_from_json(rows, temp_table, job_config=job_config).result()

    merge_sql = f"""
      MERGE `{self._table_ref('coin_metadata')}` T
      USING `{temp_table}` S ON T.coin_id = S.coin_id
      WHEN MATCHED THEN UPDATE SET
        name         = S.name,
        symbol       = S.symbol,
        genesis_date = S.genesis_date,
        ath_usd      = S.ath_usd,
        ath_date     = S.ath_date,
        fetched_at   = S.fetched_at
      WHEN NOT MATCHED THEN INSERT ROW
    """
    self.client.query(merge_sql).result()
    self.client.delete_table(temp_table, not_found_ok=True)
    log.info('Upserted %d metadata rows', len(rows))
    return len(rows)
