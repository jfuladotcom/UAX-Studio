import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent


def _persistent_secret(instance_path: Path) -> str:
    configured = os.getenv("AX_SECRET_KEY")
    if configured:
        return configured
    instance_path.mkdir(parents=True, exist_ok=True)
    secret_file = instance_path / "secret.key"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return secret_file.read_text(encoding="utf-8").strip()


class Config:
    BASE_DIR = BASE_DIR
    INSTANCE_DIR = BASE_DIR / "instance"
    SECRET_KEY = _persistent_secret(INSTANCE_DIR)
    SQLALCHEMY_DATABASE_URI = os.getenv("AX_DATABASE_URI", "sqlite:///ax_studio.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    AX_DATA_DIR = Path(os.getenv("AX_DATA_DIR", BASE_DIR / "data")).resolve()
    AX_UPLOAD_DIR = (AX_DATA_DIR / "uploads").resolve()
    AX_EXPORT_DIR = (AX_DATA_DIR / "exports").resolve()
    AX_HOST = os.getenv("AX_HOST", "127.0.0.1")
    AX_PORT = int(os.getenv("AX_PORT", "5000"))
    AX_ACTIVE_PROVIDER = os.getenv("AX_ACTIVE_PROVIDER", "deterministic")
    AX_OLLAMA_BASE_URL = os.getenv("AX_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    AX_OLLAMA_MODEL = os.getenv("AX_OLLAMA_MODEL", "llama3.1")
    AX_OLLAMA_TIMEOUT = int(os.getenv("AX_OLLAMA_TIMEOUT", "20"))
    AUTO_INIT_DB = os.getenv("AX_AUTO_INIT_DB", "1") == "1"
    JSON_SORT_KEYS = False
