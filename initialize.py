"""
initialize.py — Environment initializer
=========================================
Run this once whenever the project is deployed to a new environment.
It is also safe to call on every startup — all operations are idempotent.

What it does:
  1. Creates any missing directories (e.g. DataBase/sqlite_data/).
  2. Connects to each SQLite DB defined in db_config.yaml and runs
     CREATE TABLE IF NOT EXISTS for every table defined in SCHEMA below.
  3. Skips MySQL DBs — those schemas are managed separately (migrations).

Usage:
    python initialize.py               # uses default db_config.yaml location
    python initialize.py --config /path/to/db_config.yaml

To add a new table in future:
    Add an entry to SCHEMA under the correct db key. Re-running
    initialize.py will create the new table without touching existing ones.
"""

import os
import argparse

from DataBase.DataBase import configure, get_database
from logger import Logger

logger = Logger("PROJ-INIT")
# ---------------------------------------------------------------------------
# SCHEMA REGISTRY
# Key   = logical DB name (must match a key in db_config.yaml, type: sqlite)
# Value = list of CREATE TABLE IF NOT EXISTS statements
#
# Rules:
#   - Always use IF NOT EXISTS — safe to re-run.
#   - INTEGER PRIMARY KEY in SQLite is auto-increment by default.
#   - Add new tables here; never remove old entries (use ALTER TABLE instead).
# ---------------------------------------------------------------------------

SCHEMA = {
    "kseb-local": [
        """
        CREATE TABLE IF NOT EXISTS timeout (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            METER_ID  TEXT    NOT NULL,
            timeout   TEXT    NOT NULL
        )
        """,
        # Add more tables here as the project grows, for example:
        # """
        # CREATE TABLE IF NOT EXISTS meter_reads (
        #     id          INTEGER PRIMARY KEY AUTOINCREMENT,
        #     METER_ID    TEXT    NOT NULL,
        #     profile     TEXT    NOT NULL,
        #     read_at     TEXT    NOT NULL,
        #     rows_read   INTEGER DEFAULT 0
        # )
        # """,
    ],
}


# ---------------------------------------------------------------------------
# Directory layout
# Paths here are relative to the project root (where initialize.py lives).
# They are created if missing.
# ---------------------------------------------------------------------------

REQUIRED_DIRS = [
    "DataBase/sqlite_data",
    "logs",
]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _ensure_dirs():
    """Create required directories if they don't exist."""
    base = os.path.dirname(os.path.abspath(__file__))
    for rel_path in REQUIRED_DIRS:
        full_path = os.path.join(base, rel_path)
        os.makedirs(full_path, exist_ok=True)
        logger.info("[initialize] Directory ready: {}".format(full_path), to_file=False)


def _initialize_sqlite_schemas():
    """
    For each db key in SCHEMA, connect via the database module and
    run every CREATE TABLE IF NOT EXISTS statement.
    Only runs against sqlite DBs — MySQL is skipped with a warning.
    """
    errors = []

    for db_name, statements in SCHEMA.items():
        try:
            db = get_database(db_name)
        except KeyError:
            logger.error(
                "[initialize] '{}' not found in db_config.yaml — skipping".format(db_name),
                to_file=False,
            )
            errors.append(db_name)
            continue

        if db.db_type != "sqlite":
            logger.warning(
                "[initialize] '{}' is type '{}', not sqlite — skipping schema init "
                "(manage MySQL schemas via migrations)".format(db_name, db.db_type),
                to_file=False,
            )
            continue

        logger.info(
            "[initialize] Initializing schema for '{}' ({})".format(
                db_name, db.config.get("path", "?")
            ),
            to_file=False,
        )

        for statement in statements:
            # Extract table name from statement for logging
            stripped = statement.strip()
            try:
                # "CREATE TABLE IF NOT EXISTS timeout (...)" → "timeout"
                table_name = stripped.split()[5]
            except IndexError:
                table_name = "unknown"

            try:
                with db.cursor() as cur:
                    cur.execute(stripped)
                logger.info(
                    "[initialize]   ✓ table '{}' ready".format(table_name),
                    to_file=False,
                )
            except Exception as ex:
                logger.error(
                    "[initialize]   ✗ failed to create table '{}': {}".format(table_name, ex),
                    to_file=False,
                )
                errors.append("{}.{}".format(db_name, table_name))

    return errors


def run(config_path=None):
    """
    Main entry point. Called by __main__ and can also be imported
    and called from pipeline.py on startup.

    Returns True if all steps succeeded, False if any step failed.
    """
    if config_path:
        configure(config_path)

    logger.info("[initialize] Starting environment initialization", to_file=False)

    _ensure_dirs()
    errors = _initialize_sqlite_schemas()

    if errors:
        logger.error(
            "[initialize] Completed with errors: {}".format(errors),
            to_file=False,
        )
        return False

    logger.info("[initialize] All done — environment is ready", to_file=False)
    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Initialize project environment — create dirs and SQLite tables."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to db_config.yaml (default: db_config.yaml next to this file)",
    )
    args = parser.parse_args()

    success = run(config_path=args.config)
    raise SystemExit(0 if success else 1)