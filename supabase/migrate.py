#!/usr/bin/env python3
"""Run all Supabase SQL migrations in dependency order.

Usage:
    python supabase/migrate.py

Requires DATABASE_URL in backend/.env:
    DATABASE_URL=postgresql://postgres.[project-ref]:[password]@aws-0-us-east-1.pooler.supabase.com:6543/postgres
"""

import os
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("psycopg2-binary not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from dotenv import load_dotenv

# Load from backend/.env (one level up from supabase/)
env_path = Path(__file__).parent.parent / "backend" / ".env"
load_dotenv(env_path)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print(
        "DATABASE_URL not set in backend/.env\n"
        "Add it like:\n"
        "  DATABASE_URL=postgresql://postgres.[ref]:[password]@aws-0-us-east-1.pooler.supabase.com:6543/postgres\n"
        "Find your connection string at: Supabase Dashboard > Settings > Database > Connection string (Transaction pooler)"
    )
    sys.exit(1)

# Run in this order to respect FK dependencies
MIGRATION_ORDER = [
    "full_schema_fix.sql",        # creates bot_sessions, user_settings
    "auth_migration.sql",         # adds user_id to meetings + chats
    "calendar_migration.sql",     # calendar columns on user_settings
    "tools_migration.sql",        # tool columns on user_settings
    "bot_commands_migration.sql", # bot command helpers
    "chats_unique_migration.sql", # unique constraint on chats(meeting_id, user_id)
    "action_refs_migration.sql",  # action_refs table (needs meetings)
    "memory_migration.sql",       # memory columns on bot_sessions
]

migrations_dir = Path(__file__).parent


def run_migrations():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    print(f"Connected to database.\n")

    for filename in MIGRATION_ORDER:
        path = migrations_dir / filename
        if not path.exists():
            print(f"  SKIP  {filename} (file not found)")
            continue

        sql = path.read_text(encoding="utf-8")
        try:
            cur.execute(sql)
            print(f"  OK    {filename}")
        except Exception as e:
            print(f"  FAIL  {filename}: {e}")
            conn.close()
            sys.exit(1)

    cur.close()
    conn.close()
    print("\nAll migrations applied successfully.")


if __name__ == "__main__":
    run_migrations()
