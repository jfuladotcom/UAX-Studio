import pytest

from app import create_app
from app.config import Config
from app.extensions import db


@pytest.fixture()
def app(tmp_path):
    data_dir = tmp_path / "data"

    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        INSTANCE_DIR = tmp_path / "instance"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.sqlite3'}"
        AX_DATA_DIR = data_dir
        AX_UPLOAD_DIR = data_dir / "uploads"
        AX_EXPORT_DIR = data_dir / "exports"
        AUTO_INIT_DB = True
        WTF_CSRF_ENABLED = False

    app = create_app(TestConfig)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def csrf(client):
    client.get("/")
    with client.session_transaction() as session:
        return session["csrf_token"]
