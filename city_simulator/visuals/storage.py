"""Local file storage for the Visuals tab -- uploaded starting images and
downloaded generation results both end up here (under data/uploads/ and
data/outputs/ respectively), named by uuid so concurrent/repeat requests
never collide. Kept provider-agnostic on purpose: any Provider
implementation can call save_bytes()/save_url() the same way.
"""

import mimetypes
import uuid
from pathlib import Path

import requests

from . import config

_EXT_BY_CONTENT_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "video/mp4": ".mp4", "video/webm": ".webm",
}


def _pick_extension(content_type: str, fallback_name: str = "") -> str:
    if content_type in _EXT_BY_CONTENT_TYPE:
        return _EXT_BY_CONTENT_TYPE[content_type]
    guessed = mimetypes.guess_extension(content_type or "") if content_type else None
    if guessed:
        return guessed
    return Path(fallback_name).suffix or ""


def save_bytes(data: bytes, directory: Path, content_type: str = "", fallback_name: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    ext = _pick_extension(content_type, fallback_name)
    path = directory / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    return path


def save_upload(file_storage) -> Path:
    """file_storage: a werkzeug FileStorage from request.files[...]."""
    return save_bytes(
        file_storage.read(),
        config.UPLOADS_DIR,
        content_type=file_storage.mimetype,
        fallback_name=file_storage.filename or "",
    )


def save_url(url: str, directory: Path = None) -> Path:
    """Downloads a fal-hosted (or any) URL's bytes to local disk."""
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
    return save_bytes(resp.content, directory or config.OUTPUTS_DIR, content_type=content_type, fallback_name=url)


def relative_path(path: Path) -> str:
    """Path relative to visuals/data/, for building a /api/visuals/files/... URL."""
    return str(path.relative_to(config.UPLOADS_DIR.parent))
