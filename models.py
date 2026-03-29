from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


@dataclass
class Transaction:
    date: date
    description: str
    amount: float
    source_bank: str
    category: Optional[str] = None
    original_category: Optional[str] = None
    billing_label: Optional[str] = None

    @property
    def uid(self) -> str:
        """Stable hash used as cache key for categorisation."""
        raw = f"{self.date.isoformat()}|{self.description}|{self.amount}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Transaction:
        d = dict(d)
        if isinstance(d["date"], str):
            d["date"] = date.fromisoformat(d["date"])
        return cls(**d)


@dataclass
class CategoryResult:
    description: str
    category: str
    confidence: float = 1.0


@dataclass
class ExpenseReport:
    """A report for a single billing period (one file = one period)."""
    label: str
    transactions: list[Transaction] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(t.amount for t in self.transactions)

    def by_category(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for t in self.transactions:
            cat = t.category or "אחר"
            result[cat] = result.get(cat, 0) + t.amount
        return dict(sorted(result.items(), key=lambda x: x[1], reverse=True))

    @property
    def date_range(self) -> tuple[date, date]:
        dates = [t.date for t in self.transactions]
        return min(dates), max(dates)

    @property
    def date_range_str(self) -> str:
        start, end = self.date_range
        return f"{start.strftime('%d/%m/%Y')} — {end.strftime('%d/%m/%Y')}"


MonthlyReport = ExpenseReport


@dataclass
class Receipt:
    """Data extracted from a scanned receipt photo."""
    store_name: str
    date: date
    items: list[dict]
    total: float
    suggested_category: Optional[str] = None
    photo_path: Optional[str] = None
    drive_url: Optional[str] = None

    def to_transaction(self) -> Transaction:
        return Transaction(
            date=self.date,
            description=self.store_name,
            amount=self.total,
            source_bank="קבלה סרוקה",
            category=self.suggested_category,
        )

    def to_dict(self) -> dict:
        d = {
            "store_name": self.store_name,
            "date": self.date.isoformat(),
            "items": self.items,
            "total": self.total,
            "suggested_category": self.suggested_category,
            "photo_path": self.photo_path,
            "drive_url": self.drive_url,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Receipt:
        d = dict(d)
        if isinstance(d["date"], str):
            d["date"] = date.fromisoformat(d["date"])
        return cls(**d)
