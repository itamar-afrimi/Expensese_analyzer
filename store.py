from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_DEFAULT_PATH = Path(__file__).parent / "data" / "category_cache.json"


class CategoryStore:
    """Persistent JSON cache mapping transaction UIDs to categories.

    Avoids repeat OpenAI calls for previously categorised transactions.
    Also stores user corrections so they override AI results.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path or _DEFAULT_PATH
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._cache = json.load(f)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def get(self, uid: str) -> Optional[str]:
        entry = self._cache.get(uid)
        return entry["category"] if entry else None

    def put(self, uid: str, category: str, source: str = "ai") -> None:
        self._cache[uid] = {"category": category, "source": source}

    def put_correction(self, uid: str, category: str) -> None:
        """Store a user correction — these always take priority."""
        self._cache[uid] = {"category": category, "source": "user"}

    def is_user_corrected(self, uid: str) -> bool:
        entry = self._cache.get(uid)
        return entry is not None and entry.get("source") == "user"

    def clear(self) -> None:
        self._cache.clear()
        self.save()

    @property
    def size(self) -> int:
        return len(self._cache)
