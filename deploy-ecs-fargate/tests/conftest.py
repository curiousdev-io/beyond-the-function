import pytest

from app import app as flask_app


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    """A test client. Nothing here talks to AWS, or to the network at all."""
    return app.test_client()
