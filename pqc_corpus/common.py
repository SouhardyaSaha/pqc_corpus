"""Small helpers shared by the Python mining workers."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


def now() -> str:
    """Current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, data: Any) -> None:
    """Replace a JSON file via a temporary sibling, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def connect_read_only(path: Path) -> sqlite3.Connection:
    """Open an existing SQLite database without the ability to modify it."""
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def lowercase_slug(repo: str) -> str:
    """File stem for per-repository plans, logs, and selections: owner__name."""
    return repo.lower().replace('/', '__')


def mirror_name(repo: str) -> str:
    """Mirror directory name; keeps the repository's original letter case."""
    return repo.replace('/', '__') + '.git'


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()
