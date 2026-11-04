"""Route registry for migrated LIR domains."""

from .health import bp as health_bp


def register_blueprints(app):
    app.register_blueprint(health_bp)
    return app
