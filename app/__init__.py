from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import event

from app.config import Config
from app.extensions import db, migrate


def create_app(config_object: type[Config] | None = None) -> Flask:
    config = config_object or Config
    app = Flask(__name__, instance_relative_config=True, instance_path=str(config.INSTANCE_DIR))
    app.config.from_object(config)

    with app.app_context():
        from app.services.settings import apply_settings_to_config, load_settings

        apply_settings_to_config(load_settings())

    app.config["AX_UPLOAD_DIR"].mkdir(parents=True, exist_ok=True)
    app.config["AX_EXPORT_DIR"].mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrations_dir = Path(app.root_path) / "migrations"
    migrate.init_app(app, db, directory=str(migrations_dir), render_as_batch=True)

    with app.app_context():
        importlib.import_module("app.models")

        if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
            event.listen(db.engine, "connect", _set_sqlite_pragma)
        if app.config.get("AUTO_INIT_DB", True):
            from app.services.schema import ensure_database_schema

            ensure_database_schema()
            from app.services.project_service import seed_demo_project

            seed_demo_project(reset=False)

    from app.routes.main import bp as main_bp

    app.register_blueprint(main_bp)
    from app.cli import register_cli

    register_cli(app)
    register_template_helpers(app)
    register_csrf(app)
    register_error_handlers(app)
    return app


def _set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def register_template_helpers(app: Flask) -> None:
    from app.services.display_service import current_ui_copy

    app.add_template_filter(current_ui_copy)

    @app.context_processor
    def inject_globals():
        token = session.setdefault("csrf_token", __import__("secrets").token_urlsafe(32))
        from app.services.settings import load_settings, provider_label

        settings = load_settings()
        return {
            "csrf_token": token,
            "current_year": datetime.now(timezone.utc).year,
            "active_provider": settings.get("active_provider", "deterministic"),
            "active_provider_label": provider_label(settings),
            "reduced_motion": bool(settings.get("reduced_motion", False)),
        }

    @app.template_filter("provider_label")
    def provider_label_filter(settings):
        from app.services.settings import provider_label

        return provider_label(settings)

    @app.template_filter("datetime_local")
    def datetime_local(value):
        if not value:
            return "Not yet"
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.strftime("%Y-%m-%d %H:%M UTC")


def register_csrf(app: Flask) -> None:
    @app.before_request
    def csrf_protect():
        if request.method not in {"POST", "PATCH", "DELETE"}:
            return None
        sent = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
        expected = session.get("csrf_token")
        if expected and sent == expected:
            return None
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": {"message": "Security token expired. Refresh and try again."}}), 400
        flash("Security token expired. Refresh and try again.", "error")
        return redirect(request.referrer or url_for("main.index"))


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": {"message": "The requested record was not found."}}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(_error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": {"message": "That upload is larger than 25 MB."}}), 413
        flash("That upload is larger than 25 MB.", "error")
        return redirect(request.referrer or url_for("main.projects"))

    @app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": {"message": "Something went wrong locally."}}), 500
        return render_template("errors/500.html"), 500
