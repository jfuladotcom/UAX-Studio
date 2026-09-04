import zipfile
from datetime import datetime, timezone

from flask import current_app

from app.extensions import db
from app.models import SourceDocument
from app.services.export_service import build_export
from app.services.project_service import create_project


def test_exports_are_unique_and_preserve_original_sources(app, client, monkeypatch):
    fixed_time = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.services.export_service.utcnow", lambda: fixed_time)

    with app.app_context():
        project = create_project(name="Source test")
        project_id = project.id
        for index, content in enumerate((b"first PDF", b"second PDF"), start=1):
            stored_name = f"stored-{index}.pdf"
            (current_app.config["AX_UPLOAD_DIR"] / stored_name).write_bytes(content)
            db.session.add(
                SourceDocument(
                    project=project,
                    title="Reference",
                    source_type="upload",
                    original_filename="brief.pdf",
                    stored_filename=stored_name,
                    mime_type="application/pdf",
                    file_size=len(content),
                    extracted_text=f"Extracted {index}",
                    edited_text=f"Edited {index}",
                    extraction_status="ready",
                )
            )
        db.session.flush()

        with_sources = build_export(project, include_sources=True)
        without_sources = build_export(project, include_sources=False)
        db.session.commit()

        assert with_sources.local_path != without_sources.local_path
        with zipfile.ZipFile(with_sources.local_path) as archive:
            names = set(archive.namelist())
            assert "sources/originals/brief.pdf" in names
            assert "sources/originals/brief-2.pdf" in names
            assert "sources/text/reference.txt" in names
            assert "sources/text/reference-2.txt" in names
            assert archive.read("sources/originals/brief.pdf") == b"first PDF"
        with zipfile.ZipFile(without_sources.local_path) as archive:
            assert not any(name.startswith("sources/") for name in archive.namelist())

    history = client.get(f"/agents/{project_id}/export").get_data(as_text=True)
    assert "sources/originals/brief.pdf" in history
    assert "sources/text/reference-2.txt" in history
    assert "data-export-list" in history
