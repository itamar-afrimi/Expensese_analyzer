from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

from models import Transaction
from .base import BankParser


class MizrahiParser(BankParser):
    """Parser for Mizrahi-Tfahot Bank CSV exports."""

    name = "מזרחי-טפחות"

    HEADER_SIGNATURES = ["תאריך", "תיאור", "זכות", "חובה", "יתרה מצטברת"]

    @classmethod
    def can_parse(cls, header_line: str, sample_lines: list[str]) -> bool:
        return "יתרה מצטברת" in header_line or (
            "תיאור" in header_line and
            sum(1 for sig in cls.HEADER_SIGNATURES if sig in header_line) >= 4
        )

    def parse(self, filepath: Path) -> list[Transaction]:
        content = self.read_file(filepath)
        transactions: list[Transaction] = []

        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            tx_date = self._parse_date(row.get("תאריך", ""))
            if tx_date is None:
                continue

            description = (row.get("תיאור", "") or "").strip()
            if not description:
                continue

            debit = self.parse_amount(row.get("חובה", ""))
            credit = self.parse_amount(row.get("זכות", ""))

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
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None
