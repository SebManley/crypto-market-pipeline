"""
app.py

Streamlit dashboard for crypto-market-pipeline.
Four pages: Market Overview, Technical Analysis, Volatility & Risk, Pipeline Status.

BigQuery auth: st.secrets["gcp_service_account"] in production, ADC locally.
Run: streamlit run dashboard/app.py
"""

import os
from datetime import date, timedelta

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account

st.set_page_config(
  page_title='Crypto Market Analysis',
  page_icon=None,
  layout='wide',
  initial_sidebar_state='expanded',
)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', '')
if not PROJECT_ID:
  try:
    PROJECT_ID = st.secrets.get('gcp_project_id', '')
  except FileNotFoundError:
    PROJECT_ID = ''


@st.cache_resource
def get_bq_client() -> bigquery.Client:
  try:
    if 'gcp_service_account' in st.secrets:
      creds = service_account.Credentials.from_service_account_info(
        st.secrets['gcp_service_account'],
        scopes=['https://www.googleapis.com/auth/cloud-platform'],
      )
      return bigquery.Client(project=PROJECT_ID, credentials=creds)
  except FileNotFoundError:
    pass
  return bigquery.Client(project=PROJECT_ID)


@st.cache_data(ttl=3600)
def load_daily_prices(days_back: int = 90) -> pd.DataFrame:
  client = get_bq_client()
  query = f"""
    SELECT
      coin_id, price_date, open_usd, high_usd, low_usd, close_usd,
      volume_usd, market_cap_usd, daily_return_pct, sma_7d, sma_30d,
      annualised_volatility_30d, drawdown_from_ath_pct, price_vs_sma7_pct
    FROM `{PROJECT_ID}.analytics.fct_daily_prices`
    WHERE price_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
    ORDER BY coin_id, price_date
  """
  return client.query(query).to_dataframe(create_bqstorage_client=False)


@st.cache_data(ttl=3600)
def load_dim_coins() -> pd.DataFrame:
  client = get_bq_client()
  query = f"""
    SELECT
      coin_id, name, symbol, category, genesis_date, days_since_genesis,
      ath_usd, ath_date, latest_price_date, latest_close_usd, latest_market_cap_usd, days_of_data
    FROM `{PROJECT_ID}.analytics.dim_coins`
    ORDER BY latest_market_cap_usd DESC NULLS LAST
  """
  return client.query(query).to_dataframe(create_bqstorage_client=False)


@st.cache_data(ttl=3600)
def load_volatility() -> pd.DataFrame:
  client = get_bq_client()
  query = f"""
    SELECT
      coin_id, week_start, weekly_return_pct, weekly_return_stddev,
      annualised_volatility_weekly, avg_annualised_volatility_30d,
      weekly_volume, avg_market_cap, trading_days
    FROM `{PROJECT_ID}.analytics.fct_coin_volatility`
    WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL 180 DAY)
    ORDER BY coin_id, week_start
  """
  return client.query(query).to_dataframe(create_bqstorage_client=False)


@st.cache_data(ttl=3600)
def load_pipeline_status() -> pd.DataFrame:
  client = get_bq_client()
  query = f"""
    SELECT
      coin_id,
      MAX(fetched_date) AS last_fetched_date,
      COUNT(*)          AS total_rows,
      COUNT(CASE WHEN fetched_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) THEN 1 END) AS rows_last_7d,
      MIN(price_date)   AS earliest_date,
      MAX(price_date)   AS latest_date
    FROM `{PROJECT_ID}.raw.prices`
    GROUP BY coin_id
    ORDER BY coin_id
  """
  return client.query(query).to_dataframe(create_bqstorage_client=False)


def fmt_price(v: float) -> str:
  if v is None or pd.isna(v):
    return 'N/A'
  if v >= 1000:
    return f'${v:,.0f}'
  return f'${v:.4f}'


def fmt_pct(v: float) -> str:
  if v is None or pd.isna(v):
    return 'N/A'
  return f'{v:+.2f}%'


def fmt_billions(v: float) -> str:
  if v is None or pd.isna(v):
    return 'N/A'
  return f'${v / 1e9:.1f}B'


# ─── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title('₿ Crypto Market Pipeline')
page = st.sidebar.radio(
  'Navigate',
  ['Market Overview', 'Technical Analysis', 'Volatility & Risk', 'Pipeline Status'],
)

days_back = st.sidebar.slider('Lookback (days)', min_value=30, max_value=365, value=90, step=30)


# ─── Page: Market Overview ─────────────────────────────────────────────────────

if page == 'Market Overview':
  st.title('Market Overview')

  try:
    df    = load_daily_prices(days_back)
    coins = load_dim_coins()
  except Exception as e:
    st.error(f'Failed to load data: {e}')
    st.stop()

  # Metric cards
  st.subheader('Latest Snapshot')
  latest = df.sort_values('price_date').groupby('coin_id').last().reset_index()
  latest = latest.merge(coins[['coin_id', 'name', 'symbol']], on='coin_id', how='left')

  cols = st.columns(min(5, len(latest)))
  for i, row in latest.head(5).iterrows():
    with cols[i % 5]:
      delta_color = 'normal' if pd.notna(row.get('daily_return_pct')) else 'off'
      st.metric(
        label=f"{row.get('symbol', row['coin_id']).upper()}",
        value=fmt_price(row['close_usd']),
        delta=fmt_pct(row.get('daily_return_pct')),
        delta_color=delta_color,
      )

  st.divider()

  # Normalised price index (rebased to 100)
  st.subheader('Normalised Price Index (base = 100)')
  pivot = df.pivot(index='price_date', columns='coin_id', values='close_usd')
  first = pivot.iloc[0]
  normalised = (pivot / first * 100).reset_index().melt(
    id_vars='price_date', var_name='coin_id', value_name='index_value'
  )

  fig = px.line(
    normalised, x='price_date', y='index_value', color='coin_id',
    labels={'price_date': 'Date', 'index_value': 'Index (100 = start)', 'coin_id': 'Coin'},
  )
  fig.update_layout(hovermode='x unified', plot_bgcolor='rgba(0,0,0,0)')
  st.plotly_chart(fig, use_container_width=True)

  # Stacked volume
  st.subheader('Daily Trading Volume')
  vol_df = df[df['volume_usd'].notna()].copy()
  fig_vol = px.bar(
    vol_df, x='price_date', y='volume_usd', color='coin_id',
    labels={'price_date': 'Date', 'volume_usd': 'Volume (USD)', 'coin_id': 'Coin'},
    barmode='stack',
  )
  fig_vol.update_layout(plot_bgcolor='rgba(0,0,0,0)')
  st.plotly_chart(fig_vol, use_container_width=True)


# ─── Page: Technical Analysis ──────────────────────────────────────────────────

elif page == 'Technical Analysis':
  st.title('Technical Analysis')

  try:
    df = load_daily_prices(days_back)
  except Exception as e:
    st.error(f'Failed to load data: {e}')
    st.stop()

  coin = st.selectbox('Select coin', sorted(df['coin_id'].unique()))
  coin_df = df[df['coin_id'] == coin].sort_values('price_date')

  # Candlestick + SMA overlay
  st.subheader(f'{coin.upper()} — Price & Moving Averages')
  fig = go.Figure()

  has_ohlc = coin_df[['open_usd', 'high_usd', 'low_usd']].notna().all(axis=1).any()
  if has_ohlc:
    fig.add_trace(go.Candlestick(
      x=coin_df['price_date'],
      open=coin_df['open_usd'],
      high=coin_df['high_usd'],
      low=coin_df['low_usd'],
      close=coin_df['close_usd'],
      name='OHLC',
    ))
  else:
    fig.add_trace(go.Scatter(
      x=coin_df['price_date'], y=coin_df['close_usd'],
      mode='lines', name='Close', line={'color': '#F7931A'},
    ))

  if coin_df['sma_7d'].notna().any():
    fig.add_trace(go.Scatter(
      x=coin_df['price_date'], y=coin_df['sma_7d'],
      mode='lines', name='SMA 7d', line={'color': '#00D4FF', 'dash': 'dot'},
    ))
  if coin_df['sma_30d'].notna().any():
    fig.add_trace(go.Scatter(
      x=coin_df['price_date'], y=coin_df['sma_30d'],
      mode='lines', name='SMA 30d', line={'color': '#FF6B6B', 'dash': 'dash'},
    ))

  fig.update_layout(xaxis_rangeslider_visible=False, plot_bgcolor='rgba(0,0,0,0)')
  st.plotly_chart(fig, use_container_width=True)

  col1, col2 = st.columns(2)

  # Drawdown area chart
  with col1:
    st.subheader('Drawdown from ATH (%)')
    fig_dd = px.area(
      coin_df, x='price_date', y='drawdown_from_ath_pct',
      color_discrete_sequence=['#FF4444'],
      labels={'price_date': 'Date', 'drawdown_from_ath_pct': 'Drawdown (%)'},
    )
    fig_dd.update_layout(plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig_dd, use_container_width=True)

  # Daily return histogram
  with col2:
    st.subheader('Daily Return Distribution (%)')
    ret = coin_df['daily_return_pct'].dropna()
    fig_hist = px.histogram(
      ret, nbins=60, color_discrete_sequence=['#F7931A'],
      labels={'value': 'Daily Return (%)', 'count': 'Days'},
    )
    fig_hist.update_layout(showlegend=False, plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig_hist, use_container_width=True)


# ─── Page: Volatility & Risk ───────────────────────────────────────────────────

elif page == 'Volatility & Risk':
  st.title('Volatility & Risk')

  try:
    vol_df = load_volatility()
    prices = load_daily_prices(days_back)
    coins  = load_dim_coins()
  except Exception as e:
    st.error(f'Failed to load data: {e}')
    st.stop()

  # Rolling 30d vol line chart
  st.subheader('Annualised 30-Day Volatility')
  ann_vol = prices[prices['annualised_volatility_30d'].notna()]
  fig_vol = px.line(
    ann_vol, x='price_date', y='annualised_volatility_30d', color='coin_id',
    labels={'price_date': 'Date', 'annualised_volatility_30d': 'Ann. Vol (%)', 'coin_id': 'Coin'},
  )
  fig_vol.update_layout(hovermode='x unified', plot_bgcolor='rgba(0,0,0,0)')
  st.plotly_chart(fig_vol, use_container_width=True)

  col1, col2 = st.columns(2)

  # Volatility heatmap (coin × month)
  with col1:
    st.subheader('Volatility Heatmap (coin × month)')
    hm = vol_df.copy()
    hm['month'] = pd.to_datetime(hm['week_start']).dt.to_period('M').astype(str)
    hm_pivot = hm.groupby(['coin_id', 'month'])['avg_annualised_volatility_30d'].mean().unstack('month')
    if not hm_pivot.empty:
      fig_hm = px.imshow(
        hm_pivot,
        color_continuous_scale='RdYlGn_r',
        labels={'color': 'Ann. Vol (%)'},
        aspect='auto',
      )
      fig_hm.update_layout(plot_bgcolor='rgba(0,0,0,0)')
      st.plotly_chart(fig_hm, use_container_width=True)

  # Return vs volatility scatter
  with col2:
    st.subheader('Return vs. Volatility (bubble = market cap)')
    scatter_df = vol_df.groupby('coin_id').agg(
      weekly_return=('weekly_return_pct', 'mean'),
      volatility=('annualised_volatility_weekly', 'mean'),
      market_cap=('avg_market_cap', 'mean'),
    ).reset_index()
    scatter_df = scatter_df.merge(coins[['coin_id', 'symbol']], on='coin_id', how='left')
    fig_sc = px.scatter(
      scatter_df,
      x='volatility', y='weekly_return',
      size='market_cap', color='coin_id',
      text='symbol',
      labels={'volatility': 'Ann. Volatility (%)', 'weekly_return': 'Avg Weekly Return (%)'},
      size_max=60,
    )
    fig_sc.update_traces(textposition='top center')
    fig_sc.update_layout(plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig_sc, use_container_width=True)


# ─── Page: Pipeline Status ─────────────────────────────────────────────────────

elif page == 'Pipeline Status':
  st.title('Pipeline Status')

  try:
    status_df = load_pipeline_status()
  except Exception as e:
    st.error(f'Failed to load pipeline status: {e}')
    st.stop()

  # Summary metrics
  if not status_df.empty:
    latest_fetch = status_df['last_fetched_date'].max()
    days_stale   = (date.today() - pd.to_datetime(latest_fetch).date()).days
    total_rows   = status_df['total_rows'].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric('Last Ingest', str(latest_fetch))
    col2.metric('Days Since Last Ingest', str(days_stale), delta=f'{days_stale}d', delta_color='inverse')
    col3.metric('Total Raw Rows', f'{total_rows:,}')

    # Freshness indicator
    freshness_ok = days_stale <= 1
    if freshness_ok:
      st.success('Data is fresh — last ingest within 24 hours.')
    elif days_stale <= 2:
      st.warning(f'Data is {days_stale} days old — ingest may have been delayed.')
    else:
      st.error(f'Data is {days_stale} days old — ingest pipeline may have failed.')

  st.divider()
  st.subheader('Rows per coin (last 7 days)')
  if not status_df.empty:
    col_order = ['coin_id', 'last_fetched_date', 'rows_last_7d', 'total_rows', 'earliest_date', 'latest_date']
    st.dataframe(status_df[col_order], use_container_width=True)

  st.divider()
  st.subheader('GitHub Actions')
  st.markdown(
    '[![Daily Ingest](https://github.com/SebManley/crypto-market-pipeline/actions/workflows/ingest.yml/badge.svg)]'
    '(https://github.com/SebManley/crypto-market-pipeline/actions/workflows/ingest.yml)'
    '&nbsp;&nbsp;'
    '[![CI](https://github.com/SebManley/crypto-market-pipeline/actions/workflows/ci.yml/badge.svg)]'
    '(https://github.com/SebManley/crypto-market-pipeline/actions/workflows/ci.yml)'
  )

  st.divider()
  st.subheader('Architecture')
  st.code("""
CoinGecko API (free, unauthenticated)
  ↓  Python ingestion (requests + tenacity retry)
  ↓  BigQuery raw dataset (partitioned + clustered)
  ↓  dbt staging → intermediate → marts
  ↓  BigQuery analytics dataset
  ↓  Streamlit Community Cloud (this app)
  """, language='text')
