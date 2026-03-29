from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from models import Receipt, Transaction

_DEFAULT_PATH = Path(__file__).parent / "data" / "receipts.json"


class ReceiptStore:
    """Persistent JSON store for scanned receipts."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or _DEFAULT_PATH
        self._receipts: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self._receipts = json.load(f)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._receipts, f, ensure_ascii=False, indent=2)

    def add(self, receipt: Receipt) -> None:
        self._receipts.append(receipt.to_dict())

    def get_all(self) -> list[Receipt]:
        return [Receipt.from_dict(d) for d in self._receipts]

    def to_transactions(self) -> list[Transaction]:
        return [r.to_transaction() for r in self.get_all()]

    @property
    def size(self) -> int:
        return len(self._receipts)
