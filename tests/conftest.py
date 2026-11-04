"""Testing configuration."""

import pytest


@pytest.fixture
def app_client():
    from lir import create_app

    app = create_app()
    with app.test_client() as client:
        yield client
