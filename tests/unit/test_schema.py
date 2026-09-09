from pathlib import Path

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.config import Config
from app.extensions import db
from app.services.schema import LEGACY_BASELINE, SCHEMA_HEAD


def test_unversioned_legacy_database_is_backed_up_and_upgraded(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"

    class LegacyConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        INSTANCE_DIR = tmp_path / "instance"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        AX_DATA_DIR = tmp_path / "data"
        AX_UPLOAD_DIR = AX_DATA_DIR / "uploads"
        AX_EXPORT_DIR = AX_DATA_DIR / "exports"
        AUTO_INIT_DB = False

    legacy_app = create_app(LegacyConfig)
    with legacy_app.app_context():
        upgrade(directory=str(Path(legacy_app.root_path) / "migrations"), revision=LEGACY_BASELINE)
        with db.engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
        db.session.remove()

    class UpgradeConfig(LegacyConfig):
        AUTO_INIT_DB = True

    upgraded_app = create_app(UpgradeConfig)
    with upgraded_app.app_context():
        columns = {column["name"] for column in inspect(db.engine).get_columns("synthesis_item")}
        revision = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert "inclusion_status" in columns
        assert revision == SCHEMA_HEAD
        assert list((tmp_path / "backups").glob("legacy-*.sqlite3"))
        db.session.remove()

