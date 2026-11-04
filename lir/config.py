"""Application configuration for LIR."""

import os


class Config:
    SECRET_KEY = os.environ.get("APP_SESSION_SECRET", "dev-secret-change-me")
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    TESTING = False
    DB_PATH = os.environ.get("DONNEES_DIR", "./data")
    DATABASE = os.path.join(DB_PATH, "livraisons.db")
    JSON_SORT_KEYS = False
