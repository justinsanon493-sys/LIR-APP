"""Transitional Flask app factory.

The legacy implementation in the repository root still owns the production
routes and database migrations. Returning that instance here keeps all existing
URLs and behavior intact while new domains are migrated incrementally into
`lir.routes` and `lir.services`.
"""


def create_app(legacy_application=None):
    if legacy_application is not None:
        return legacy_application

    # Import lazily to avoid a package-import cycle while app.py is loading.
    import app as legacy_app

    return legacy_app.app
