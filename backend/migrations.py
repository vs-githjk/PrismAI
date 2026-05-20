import logging
import os
import pathlib

import psycopg2

logger = logging.getLogger(__name__)

_SCHEMA = pathlib.Path(__file__).parent / "schema.sql"


def run_migrations() -> None:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not set — skipping auto-migrations")
        return

    try:
        sql = _SCHEMA.read_text()
    except FileNotFoundError:
        logger.error("schema.sql not found at %s", _SCHEMA)
        return

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.close()
        logger.info("Migrations applied successfully")
    except Exception as exc:
        # Log but don't crash — a migration failure shouldn't take down the API
        logger.error("Migration failed (check DATABASE_URL and schema.sql): %s", exc)
