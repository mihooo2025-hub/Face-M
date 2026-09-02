import json
from pathlib import Path
from typing import Any

from config import STATE_FILE
from utils import iso_now

DEFAULT_STATE = {
    "version": 1,
    "posts": {},
    "successful_fingerprints": [],
    "successful_source_texts": [],
    "updated_at": None,
}


class StateStore:
    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return json.loads(json.dumps(DEFAULT_STATE))
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("state root must be an object")
            data.setdefault("version", 1)
            data.setdefault("posts", {})
            data.setdefault("successful_fingerprints", [])
            data.setdefault("successful_source_texts", [])
            data.setdefault("updated_at", None)
            return data
        except (json.JSONDecodeError, OSError, ValueError):
            return json.loads(json.dumps(DEFAULT_STATE))

    def save(self) -> None:
        self.data["updated_at"] = iso_now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def posts(self) -> dict[str, Any]:
        return self.data["posts"]

    def get(self, key: str):
        return self.posts.get(key)

    def upsert(self, key: str, value: dict[str, Any]) -> None:
        self.posts[key] = value

    def add_success_fingerprint(self, fingerprint: str) -> None:
        items = self.data["successful_fingerprints"]
        if fingerprint not in items:
            items.append(fingerprint)
        if len(items) > 1000:
            del items[:-1000]

    def has_success_fingerprint(self, fingerprint: str) -> bool:
        return fingerprint in self.data["successful_fingerprints"]
