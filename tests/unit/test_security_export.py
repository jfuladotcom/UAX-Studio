from pathlib import Path

import pytest

from app.models import Project
from app.services.export_service import build_export, mermaid_for_workflow
from app.services.security import ensure_within_directory, remove_tree_safely


def test_path_safety_rejects_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(ValueError):
        ensure_within_directory(base, base / ".." / "outside.txt")


def test_remove_tree_safely_cannot_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError):
        remove_tree_safely(base, outside)
    assert outside.exists()


def test_mermaid_sanitizes_labels():
    text = mermaid_for_workflow(
        {
            "nodes": [{"id": "a-b", "label": "Bad [label] | text"}],
            "edges": [],
        }
    )
    assert "Bad label  text" in text
    assert "n_a_b" in text


def test_export_bundle_contains_required_files(app):
    with app.app_context():
        project = Project.query.filter_by(slug="galleryflow-artist-submission-coordination").first()
        record = build_export(project)
        manifest_paths = {item["path"] for item in record.manifest_json["files"]}
        assert "AI_BUILD_BRIEF.md" in manifest_paths
        assert "FULA_BUILD_SPEC.md" not in manifest_paths
        assert "workflow.json" in manifest_paths
        assert all(not Path(path).is_absolute() for path in manifest_paths)
        assert Path(record.local_path).exists()
