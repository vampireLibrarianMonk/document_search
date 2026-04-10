"""Postgres connection and schema setup.

Creates tables on first connect. All document metadata and job state
lives here so it survives container restarts.
"""

from __future__ import annotations

import logging
import os

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'uploaded_file',
    source_url TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT 'general',
    category TEXT NOT NULL DEFAULT 'Uncategorized',
    tags TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
);

-- Add category column if upgrading from older schema
DO $$ BEGIN
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'Uncategorized';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    section_heading TEXT NOT NULL DEFAULT 'Body',
    content TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'uploaded_file',
    document_type TEXT NOT NULL DEFAULT 'general',
    tags TEXT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS token_usage (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    model_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    document_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_token_usage_ts ON token_usage(timestamp);
"""


def _dsn() -> str:
    return (
        f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'docsearch')} "
        f"user={os.getenv('POSTGRES_USER', 'docsearch')} "
        f"password={os.getenv('POSTGRES_PASSWORD', 'docsearch_local')}"
    )


def get_conn():
    """Get a new database connection."""
    conn = psycopg2.connect(_dsn())
    conn.autocommit = True
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
        logger.info("Database schema initialized")
    finally:
        conn.close()
