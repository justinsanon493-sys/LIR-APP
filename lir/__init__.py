"""Core application package for LIR."""

from flask import Flask

from .config import Config
from .routes import register_blueprints


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    register_blueprints(app)
    return app
