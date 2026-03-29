from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

from models import Transaction
from .base import BankParser


class LeumiParser(BankParser):
    """Parser for Bank Leumi CSV exports."""

    name = "לאומי"

    HEADER_SIGNATURES = ["תאריך העסקה", "תאריך ערך", "תיאור", "סכום חיוב", "סכום זיכוי"]

    @classmethod
    def can_parse(cls, header_line: str, sample_lines: list[str]) -> bool:
        return any(sig in header_line for sig in cls.HEADER_SIGNATURES[:3])

    def parse(self, filepath: Path) -> list[Transaction]:
        content = self.read_file(filepath)
        transactions: list[Transaction] = []

        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            tx_date = self._parse_date(
                row.get("תאריך העסקה", "") or row.get("תאריך", "")
            )
            if tx_date is None:
                continue

            description = (row.get("תיאור", "") or "").strip()
            if not description:
                continue

            debit = self.parse_amount(row.get("סכום חיוב", "") or row.get("חובה", ""))
            credit = self.parse_amount(row.get("סכום זיכוי", "") or row.get("זכות", ""))

            if debit is not None:
                amount = abs(debit)
            elif credit is not None:
                amount = -abs(credit)
            else:
                continue

            transactions.append(
                Transaction(date=tx_date, description=description, amount=amount, source_bank=self.name)
            )

        return transactions

    @staticmethod
    def _parse_date(value: str) -> date | None:
        value = value.strip()
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None
