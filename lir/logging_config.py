"""Logging configuration for the app."""

import logging
import os
from logging.handlers import RotatingFileHandler


def configure_logging(app):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        handler = RotatingFileHandler(os.path.join(log_dir, "lir.log"), maxBytes=2_000_000, backupCount=5)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    app.logger.info("LIR logging initialized")
