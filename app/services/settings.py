from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from flask import current_app

DEFAULT_SETTINGS = {
    "active_provider": "deterministic",
    "ollama_base_url": "http://127.0.0.1:11434",
    "ollama_model": "llama3.1",
    "ollama_timeout": 20,
    "data_dir": "",
    "export_dir": "",
    "reduced_motion": False,
}


def _settings_path() -> Path:
    return Path(current_app.instance_path) / "settings.json"


def _base_dir() -> Path:
    return Path(current_app.config.get("BASE_DIR", Path.cwd())).resolve()


def _resolve_directory(value: object, fallback: object) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else Path(fallback)
    if not path.is_absolute():
        path = _base_dir() / path
    return path.resolve()


def _normalize_settings(settings: Mapping[str, object]) -> dict:
    normalized = dict(settings)
    data_fallback = current_app.config.get("AX_DATA_DIR", _base_dir() / "data")
    data_dir = _resolve_directory(normalized.get("data_dir"), data_fallback)
    export_fallback = current_app.config.get("AX_EXPORT_DIR", data_dir / "exports")
    if not normalized.get("export_dir"):
        export_fallback = data_dir / "exports"
    export_dir = _resolve_directory(normalized.get("export_dir"), export_fallback)
    normalized["data_dir"] = str(data_dir)
    normalized["export_dir"] = str(export_dir)
    try:
        normalized["ollama_timeout"] = max(1, min(int(normalized.get("ollama_timeout") or 20), 120))
    except (TypeError, ValueError):
        normalized["ollama_timeout"] = 20
    reduced_motion = normalized.get("reduced_motion", False)
    if isinstance(reduced_motion, str):
        normalized["reduced_motion"] = reduced_motion.strip().lower() in {"1", "true", "yes", "on"}
    else:
        normalized["reduced_motion"] = bool(reduced_motion)
    return normalized


def apply_settings_to_config(settings: Mapping[str, object]) -> dict:
    current = _normalize_settings(settings)
    _prepare_storage_directories(current)
    data_dir = Path(current["data_dir"])
    upload_dir = (data_dir / "uploads").resolve()
    export_dir = Path(current["export_dir"])

    current_app.config["AX_ACTIVE_PROVIDER"] = current["active_provider"]
    current_app.config["AX_OLLAMA_BASE_URL"] = current["ollama_base_url"]
    current_app.config["AX_OLLAMA_MODEL"] = current["ollama_model"]
    current_app.config["AX_OLLAMA_TIMEOUT"] = int(current["ollama_timeout"])
    current_app.config["AX_DATA_DIR"] = data_dir
    current_app.config["AX_UPLOAD_DIR"] = upload_dir
    current_app.config["AX_EXPORT_DIR"] = export_dir
    return current


def _prepare_storage_directories(settings: Mapping[str, object]) -> None:
    data_dir = Path(str(settings["data_dir"]))
    directories = (data_dir, (data_dir / "uploads").resolve(), Path(str(settings["export_dir"])))
    for directory in directories:
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"{directory} exists but is not a directory.")
        directory.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    path = _settings_path()
    settings = dict(DEFAULT_SETTINGS)
    settings.update(
        {
            "active_provider": current_app.config.get("AX_ACTIVE_PROVIDER", "deterministic"),
            "ollama_base_url": current_app.config.get("AX_OLLAMA_BASE_URL"),
            "ollama_model": current_app.config.get("AX_OLLAMA_MODEL"),
            "ollama_timeout": current_app.config.get("AX_OLLAMA_TIMEOUT"),
            "data_dir": str(current_app.config.get("AX_DATA_DIR", _base_dir() / "data")),
            "export_dir": str(
                current_app.config.get(
                    "AX_EXPORT_DIR",
                    Path(current_app.config.get("AX_DATA_DIR", _base_dir() / "data")) / "exports",
                )
            ),
        }
    )
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                settings.update({key: stored[key] for key in DEFAULT_SETTINGS if key in stored})
        except json.JSONDecodeError:
            pass
    return _normalize_settings(settings)


def provider_label(settings: Mapping[str, object]) -> str:
    if settings.get("active_provider") == "ollama":
        model = str(settings.get("ollama_model") or "").strip()
        if model:
            return f"Local Ollama model: {model}"
        return "Local Ollama model"
    return "Built-in draft helper"


def save_settings(data: dict) -> dict:
    previous = load_settings()
    current = dict(previous)
    allowed = set(DEFAULT_SETTINGS)
    for key, value in data.items():
        if key in allowed:
            current[key] = value
    current = _normalize_settings(current)
    _prepare_storage_directories(current)

    settings_path = _settings_path()
    previous_settings = settings_path.read_bytes() if settings_path.exists() else None
    moves: list[tuple[Path, Path]] = []
    try:
        export_updates = _move_tracked_storage(previous, current, moves)
        for record, new_path in export_updates:
            record.local_path = str(new_path)
        current = apply_settings_to_config(current)
        _write_settings_file(settings_path, current)

        from app.extensions import db

        db.session.commit()
    except Exception:
        from app.extensions import db

        db.session.rollback()
        _rollback_moves(moves)
        apply_settings_to_config(previous)
        _restore_settings_file(settings_path, previous_settings)
        raise
    return current


def _move_tracked_storage(
    previous: Mapping[str, object],
    current: Mapping[str, object],
    moves: list[tuple[Path, Path]],
) -> list[tuple[object, Path]]:
    from app.models import ExportRecord, SourceDocument
    from app.services.security import ensure_within_directory

    old_upload_dir = (Path(str(previous["data_dir"])) / "uploads").resolve()
    new_upload_dir = (Path(str(current["data_dir"])) / "uploads").resolve()
    if old_upload_dir != new_upload_dir:
        seen_uploads: set[str] = set()
        for source in SourceDocument.query.filter(SourceDocument.stored_filename != "").all():
            if source.stored_filename in seen_uploads:
                continue
            seen_uploads.add(source.stored_filename)
            old_path = ensure_within_directory(old_upload_dir, old_upload_dir / source.stored_filename)
            new_path = ensure_within_directory(new_upload_dir, new_upload_dir / source.stored_filename)
            _move_required_path(old_path, new_path, moves, "uploaded source")

    old_export_dir = Path(str(previous["export_dir"])).resolve()
    new_export_dir = Path(str(current["export_dir"])).resolve()
    updates: list[tuple[object, Path]] = []
    if old_export_dir == new_export_dir:
        return updates

    migrated_paths: dict[Path, Path] = {}
    reserved_targets: set[Path] = set()
    for record in ExportRecord.query.order_by(ExportRecord.created_at).all():
        old_zip = ensure_within_directory(old_export_dir, Path(record.local_path))
        resolved_old_zip = old_zip.resolve()
        if resolved_old_zip in migrated_paths:
            updates.append((record, migrated_paths[resolved_old_zip]))
            continue

        new_zip = _available_export_target(new_export_dir / old_zip.name, reserved_targets)
        _move_required_path(old_zip, new_zip, moves, "export ZIP")
        old_bundle = old_zip.with_suffix("")
        if old_bundle.exists():
            _move_required_path(old_bundle, new_zip.with_suffix(""), moves, "export folder")
        migrated_paths[resolved_old_zip] = new_zip
        reserved_targets.add(new_zip)
        reserved_targets.add(new_zip.with_suffix(""))
        updates.append((record, new_zip))
    return updates


def _available_export_target(candidate: Path, reserved: set[Path]) -> Path:
    target = candidate.resolve()
    if target not in reserved and not target.exists() and not target.with_suffix("").exists():
        return target
    return candidate.with_name(f"{candidate.stem}-{uuid4().hex[:8]}{candidate.suffix}").resolve()


def _move_required_path(
    source: Path,
    destination: Path,
    moves: list[tuple[Path, Path]],
    label: str,
) -> None:
    if source.resolve() == destination.resolve():
        return
    if not source.exists():
        raise ValueError(f"Could not move {label}; the existing file is missing: {source}")
    if destination.exists():
        raise ValueError(f"Could not move {label}; the destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    moves.append((source, destination))


def _rollback_moves(moves: list[tuple[Path, Path]]) -> None:
    for source, destination in reversed(moves):
        if not destination.exists() or source.exists():
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))


def _write_settings_file(path: Path, settings: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(dict(settings), indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_settings_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.restore")
    try:
        temporary.write_bytes(previous)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
