"""File storage abstraction. Local disk now; an S3/Azure Blob implementation can replace it without touching callers."""
import uuid
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Storage(Protocol):
    def save(self, data: bytes, suffix: str) -> str: ...
    def path(self, name: str) -> Path: ...
    def delete(self, name: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, suffix: str) -> str:
        name = f"{uuid.uuid4().hex}{suffix}"  # never the user-supplied filename
        (self.root / name).write_bytes(data)
        return name

    def path(self, name: str) -> Path:
        p = (self.root / name).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("invalid storage name")
        return p

    def delete(self, name: str) -> None:
        self.path(name).unlink(missing_ok=True)


def get_storage() -> Storage:
    s = get_settings()
    root = Path(s.upload_dir) if s.upload_dir else Path(__file__).resolve().parents[2] / "uploads"
    return LocalStorage(root)
