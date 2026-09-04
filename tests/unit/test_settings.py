import shutil
from pathlib import Path

import pytest
from flask import current_app

from app.extensions import db
from app.models import ExportRecord, SourceDocument
from app.services.export_service import build_export
from app.services.project_service import create_project
from app.services.settings import save_settings


def test_save_settings_updates_local_data_directories(app, tmp_path):
    data_dir = tmp_path / "custom-data"
    export_dir = tmp_path / "custom-exports"

    with app.app_context():
        settings = save_settings(
            {
                "data_dir": str(data_dir),
                "export_dir": str(export_dir),
            }
        )

        assert settings["data_dir"] == str(data_dir.resolve())
        assert settings["export_dir"] == str(export_dir.resolve())
        assert current_app.config["AX_DATA_DIR"] == data_dir.resolve()
        assert current_app.config["AX_UPLOAD_DIR"] == (data_dir / "uploads").resolve()
        assert current_app.config["AX_EXPORT_DIR"] == export_dir.resolve()
        assert current_app.config["AX_UPLOAD_DIR"].is_dir()
        assert current_app.config["AX_EXPORT_DIR"].is_dir()


def test_settings_page_has_editable_local_data_and_model_test(client, monkeypatch):
    monkeypatch.setattr("app.routes.main.list_ollama_models", lambda *_args: ["llama3:latest"])

    response = client.get("/settings")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="data_dir"' in html
    assert 'name="export_dir"' in html
    assert "Ollama: llama3:latest" in html
    assert "Test local models" in html
    assert "Test Ollama" not in html
    assert "Default project behavior" not in html


def test_settings_api_updates_local_data_directories(client, app, csrf, tmp_path):
    data_dir = tmp_path / "api-data"
    export_dir = tmp_path / "api-exports"

    response = client.patch(
        "/api/settings",
        headers={"X-CSRFToken": csrf},
        json={
            "provider_choice": "deterministic",
            "data_dir": str(data_dir),
            "export_dir": str(export_dir),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["settings"]["data_dir"] == str(data_dir.resolve())
    assert payload["data"]["settings"]["export_dir"] == str(export_dir.resolve())
    with app.app_context():
        assert current_app.config["AX_UPLOAD_DIR"] == (data_dir / "uploads").resolve()
        assert current_app.config["AX_EXPORT_DIR"] == export_dir.resolve()


def test_storage_changes_move_tracked_files_and_keep_downloads_working(client, app, tmp_path):
    new_data_dir = tmp_path / "moved-data"
    new_export_dir = tmp_path / "moved-exports"

    with app.app_context():
        project = create_project(name="Moving files")
        stored_name = "stored-source.txt"
        old_upload = current_app.config["AX_UPLOAD_DIR"] / stored_name
        old_upload.write_text("Source contents", encoding="utf-8")
        db.session.add(
            SourceDocument(
                project=project,
                title="Source",
                source_type="upload",
                original_filename="source.txt",
                stored_filename=stored_name,
                mime_type="text/plain",
                file_size=15,
                extracted_text="Source contents",
                edited_text="Source contents",
                extraction_status="ready",
            )
        )
        export = build_export(project)
        db.session.commit()
        export_id = export.id
        old_export = export.local_path

        save_settings({"data_dir": str(new_data_dir), "export_dir": str(new_export_dir)})
        moved = db.session.get(ExportRecord, export_id)
        assert not old_upload.exists()
        assert (new_data_dir / "uploads" / stored_name).is_file()
        assert not Path(old_export).exists()
        assert Path(moved.local_path).is_file()

    response = client.get(f"/downloads/{export_id}")
    assert response.status_code == 200
    assert response.mimetype == "application/zip"


def test_storage_change_rolls_back_partial_moves(app, tmp_path, monkeypatch):
    new_data_dir = tmp_path / "failed-data"
    new_export_dir = tmp_path / "failed-exports"

    with app.app_context():
        project = create_project(name="Rollback files")
        stored_name = "rollback-source.txt"
        old_upload_dir = current_app.config["AX_UPLOAD_DIR"]
        old_export_dir = current_app.config["AX_EXPORT_DIR"]
        old_upload = old_upload_dir / stored_name
        old_upload.write_text("Source contents", encoding="utf-8")
        db.session.add(
            SourceDocument(
                project=project,
                title="Source",
                source_type="upload",
                original_filename="source.txt",
                stored_filename=stored_name,
                mime_type="text/plain",
                file_size=15,
                extracted_text="Source contents",
                edited_text="Source contents",
                extraction_status="ready",
            )
        )
        export = build_export(project)
        db.session.commit()
        old_export = export.local_path

        real_move = shutil.move
        calls = 0

        def fail_second_move(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated move failure")
            return real_move(source, destination)

        monkeypatch.setattr("app.services.settings.shutil.move", fail_second_move)
        with pytest.raises(OSError, match="simulated move failure"):
            save_settings({"data_dir": str(new_data_dir), "export_dir": str(new_export_dir)})

        assert old_upload.is_file()
        assert Path(old_export).is_file()
        assert current_app.config["AX_UPLOAD_DIR"] == old_upload_dir
        assert current_app.config["AX_EXPORT_DIR"] == old_export_dir


def test_reduced_motion_setting_is_applied_to_pages(client, app):
    with app.app_context():
        save_settings({"reduced_motion": True})

    html = client.get("/agent/new").get_data(as_text=True)
    assert 'class="app-shell-body reduced-motion"' in html
    assert 'rel="icon"' in html
