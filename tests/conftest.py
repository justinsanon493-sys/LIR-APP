"""Testing configuration for the transitional application."""

import pytest


@pytest.fixture
def app_client():
    from lir import create_app

    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client
