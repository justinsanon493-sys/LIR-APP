"""Database helpers for SQLite operations."""

import os
import sqlite3
from contextlib import closing
from typing import Any

from flask import g


def get_db_path(app=None):
    if app is not None:
        return app.config.get("DATABASE", "./data/livraisons.db")
    return os.environ.get("DONNEES_DIR", "./data") + "/livraisons.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(get_db_path())
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    os.makedirs(os.path.dirname(get_db_path(app)), exist_ok=True)
    with closing(sqlite3.connect(get_db_path(app))) as conn:
        conn.execute("SELECT 1")
