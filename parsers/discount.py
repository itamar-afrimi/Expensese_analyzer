from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

from models import Transaction
from .base import BankParser


class DiscountParser(BankParser):
    """Parser for Discount Bank CSV exports."""

    name = "דיסקונט"

    HEADER_SIGNATURES = ["תאריך ערך", "תאור", "סכום", "יתרה"]

    @classmethod
    def can_parse(cls, header_line: str, sample_lines: list[str]) -> bool:
        return "תאור" in header_line and ("דיסקונט" in header_line.lower() or
               sum(1 for sig in cls.HEADER_SIGNATURES if sig in header_line) >= 3)

    def parse(self, filepath: Path) -> list[Transaction]:
        content = self.read_file(filepath)
        transactions: list[Transaction] = []

        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            tx_date = self._parse_date(
                row.get("תאריך ערך", "") or row.get("תאריך", "")
            )
            if tx_date is None:
                continue

            description = (row.get("תאור", "") or row.get("תיאור", "") or "").strip()
            if not description:
                continue

            amount_str = row.get("סכום", "")
            amount = self.parse_amount(amount_str)
            if amount is None:
                continue

            if amount < 0:
                amount = -amount
            is_credit = "זכות" in row.get("סוג", "") or amount_str.strip().startswith("-")
            if is_credit:
                amount = -amount

            transactions.append(
                Transaction(date=tx_date, description=description, amount=amount, source_bank=self.name)
            )

        return transactions

    @staticmethod
    def _parse_date(value: str) -> date | None:
        value = value.strip()
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None
