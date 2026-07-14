"""
bigquery_loader.py

BigQuery loader using load jobs (no DML/MERGE) to avoid billing requirements.

Strategy:
  - Full refresh: WRITE_TRUNCATE replaces the table entirely.
  - Incremental: WRITE_APPEND adds new rows; dbt staging deduplicates with QUALIFY.
  - coin_metadata: always WRITE_TRUNCATE (10 rows, fast to replace).

Usage:
  loader = BigQueryLoader(project_id='my-project')
  loader.ensure_tables_exist()
  loader.write_prices(rows, full_refresh=True)
  loader.write_coin_metadata(rows)
"""

import logging
from typing import Optional

from google.cloud import bigquery
from google.oauth2 import service_account

log = logging.getLogger(__name__)

PRICES_SCHEMA = [
  bigquery.SchemaField('coin_id',        'STRING',    mode='REQUIRED'),
  bigquery.SchemaField('price_date',     'DATE',      mode='REQUIRED'),
  bigquery.SchemaField('open_usd',       'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('high_usd',       'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('low_usd',        'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('close_usd',      'FLOAT64',   mode='REQUIRED'),
  bigquery.SchemaField('volume_usd',     'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('market_cap_usd', 'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('fetched_date',   'DATE',      mode='REQUIRED'),
  bigquery.SchemaField('fetched_at',     'TIMESTAMP', mode='REQUIRED'),
]

METADATA_SCHEMA = [
  bigquery.SchemaField('coin_id',      'STRING',    mode='REQUIRED'),
  bigquery.SchemaField('name',         'STRING',    mode='NULLABLE'),
  bigquery.SchemaField('symbol',       'STRING',    mode='NULLABLE'),
  bigquery.SchemaField('genesis_date', 'DATE',      mode='NULLABLE'),
  bigquery.SchemaField('ath_usd',      'FLOAT64',   mode='NULLABLE'),
  bigquery.SchemaField('ath_date',     'DATE',      mode='NULLABLE'),
  bigquery.SchemaField('fetched_at',   'TIMESTAMP', mode='REQUIRED'),
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

  def write_prices(self, rows: list[dict], full_refresh: bool = False) -> int:
    if not rows:
      return 0
    disposition = 'WRITE_TRUNCATE' if full_refresh else 'WRITE_APPEND'
    job_config = bigquery.LoadJobConfig(
      schema=PRICES_SCHEMA,
      write_disposition=disposition,
    )
    self.client.load_table_from_json(rows, self._table_ref('prices'), job_config=job_config).result()
    log.info('Wrote %d price rows (%s)', len(rows), disposition)
    return len(rows)

  def write_coin_metadata(self, rows: list[dict]) -> int:
    if not rows:
      return 0
    job_config = bigquery.LoadJobConfig(
      schema=METADATA_SCHEMA,
      write_disposition='WRITE_TRUNCATE',
    )
    self.client.load_table_from_json(rows, self._table_ref('coin_metadata'), job_config=job_config).result()
    log.info('Wrote %d metadata rows (WRITE_TRUNCATE)', len(rows))
    return len(rows)

  # Keep old names as aliases so tests don't break
  def upsert_prices(self, rows: list[dict], full_refresh: bool = False) -> int:
    return self.write_prices(rows, full_refresh=full_refresh)

  def upsert_coin_metadata(self, rows: list[dict]) -> int:
    return self.write_coin_metadata(rows)
