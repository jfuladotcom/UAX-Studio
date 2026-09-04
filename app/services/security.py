from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

ALLOWED_UPLOAD_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".pdf", ".docx"}
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "project"


def safe_display_filename(filename: str) -> str:
    secured = secure_filename(filename or "")
    return secured or "source.txt"


def allowed_extension(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS


def generated_storage_name(original_filename: str) -> str:
    ext = Path(original_filename or "").suffix.lower()
    return f"{uuid.uuid4()}{ext}"


def ensure_within_directory(base_dir: Path, target: Path) -> Path:
    base = base_dir.resolve()
    resolved = target.resolve()
    if resolved == base or base in resolved.parents:
        return resolved
    raise ValueError("Path escapes the configured data directory.")


def save_upload(upload: FileStorage, upload_dir: Path) -> tuple[str, int]:
    if not upload or not upload.filename:
        raise ValueError("Choose a supported file to upload.")
    if not allowed_extension(upload.filename):
        raise ValueError("Unsupported file type. Use TXT, MD, JSON, CSV, PDF, or DOCX.")
    stored_name = generated_storage_name(upload.filename)
    target = ensure_within_directory(upload_dir, upload_dir / stored_name)
    upload.save(target)
    size = target.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        target.unlink(missing_ok=True)
        raise ValueError("That upload is larger than 25 MB.")
    return stored_name, size


def remove_tree_safely(base_dir: Path, target: Path) -> None:
    resolved = ensure_within_directory(base_dir, target)
    if resolved.exists():
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
