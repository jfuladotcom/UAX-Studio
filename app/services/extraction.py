from __future__ import annotations

import json
from pathlib import Path

from app.services.security import TEXT_EXTENSIONS


def extract_text(path: Path, original_filename: str) -> tuple[str, str]:
    ext = Path(original_filename).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8", errors="replace"), ""
    if ext == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            return text.strip(), ""
        except Exception as exc:  # pragma: no cover - depends on optional parser internals
            return "", f"PDF extraction failed: {exc}"
    if ext == ".docx":
        try:
            from docx import Document

            document = Document(str(path))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            return text.strip(), ""
        except Exception as exc:  # pragma: no cover - depends on optional parser internals
            return "", f"DOCX extraction failed: {exc}"
    return "", "Unsupported file type."


def normalize_pasted_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").strip()


def preview_jsonish_text(text: str) -> str:
    try:
        parsed = json.loads(text)
    except Exception:
        return text
    return json.dumps(parsed, indent=2, ensure_ascii=True)
