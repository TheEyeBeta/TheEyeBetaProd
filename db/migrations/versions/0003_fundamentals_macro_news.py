"""fundamentals_macro_news
Revision ID: 0003_fundamentals_macro_news
Revises: 0002_prices
"""
from alembic import op
revision = "0003_fundamentals_macro_news"
down_revision = "0002_prices"

SQL_UP = """
CREATE TABLE theeyebeta.fundamentals (
  id bigserial PRIMARY KEY,
  instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
  period_end date NOT NULL,
  period_type text NOT NULL CHECK (period_type IN ('Q','A','TTM')),
  revenue numeric(20,2), net_income numeric(20,2), eps numeric(12,4),
  pe_ratio numeric(12,4), pb_ratio numeric(12,4), debt_to_equity numeric(12,4),
  roe numeric(12,6), gross_margin numeric(12,6), free_cash_flow numeric(20,2),
  raw jsonb NOT NULL DEFAULT '{}'::jsonb,
  source text NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (instrument_id, period_end, period_type, source)
);
CREATE INDEX idx_fundamentals_inst ON theeyebeta.fundamentals(instrument_id, period_end DESC);

CREATE TABLE theeyebeta.macro_indicators (
  id bigserial,
  series_code text NOT NULL,
  ts timestamptz NOT NULL,
  value numeric(20,6) NOT NULL,
  source text NOT NULL,
  UNIQUE (series_code, ts)
);
SELECT create_hypertable('theeyebeta.macro_indicators', 'ts', chunk_time_interval => INTERVAL '1 year');

CREATE TABLE theeyebeta.news_articles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  published_at timestamptz NOT NULL,
  source text NOT NULL,
  headline text NOT NULL,
  body text,
  url text,
  language char(2) NOT NULL DEFAULT 'en',
  tickers text[] NOT NULL DEFAULT '{}',
  ingested_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_news_published ON theeyebeta.news_articles(published_at DESC);
CREATE INDEX idx_news_tickers ON theeyebeta.news_articles USING GIN (tickers);

CREATE TABLE theeyebeta.news_embeddings (
  article_id uuid PRIMARY KEY REFERENCES theeyebeta.news_articles(id) ON DELETE CASCADE,
  model text NOT NULL,
  embedding vector(1536) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_news_embed_hnsw ON theeyebeta.news_embeddings
  USING hnsw (embedding vector_cosine_ops);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.fundamentals, theeyebeta.macro_indicators,
      theeyebeta.news_articles, theeyebeta.news_embeddings TO tb_app;
GRANT SELECT ON theeyebeta.fundamentals, theeyebeta.macro_indicators,
      theeyebeta.news_articles, theeyebeta.news_embeddings TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.news_embeddings;
DROP TABLE IF EXISTS theeyebeta.news_articles;
DROP TABLE IF EXISTS theeyebeta.macro_indicators;
DROP TABLE IF EXISTS theeyebeta.fundamentals;
"""

def upgrade(): op.execute(SQL_UP)
def downgrade(): op.execute(SQL_DOWN)
