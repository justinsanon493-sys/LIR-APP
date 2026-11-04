"""Core application package for LIR."""

from flask import Flask

from .config import Config
from .logging_config import configure_logging
from .routes import register_blueprints


def create_app(config_class=Config, legacy_application=None):
    if legacy_application is not None:
        return legacy_application

    app = Flask(__name__)
    app.config.from_object(config_class)
    configure_logging(app)
    register_blueprints(app)
    return app
