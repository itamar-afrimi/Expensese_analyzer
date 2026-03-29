from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from models import Transaction
from .base import BankParser

ENGLISH_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

HEBREW_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4,
    "מאי": 5, "יוני": 6, "יולי": 7, "אוגוסט": 8,
    "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}


class CreditCardParser(BankParser):
    """Parser for Israeli credit card company Excel exports (Max, Cal, Isracard, etc.)."""

    name = "כרטיס אשראי"

    SECTION_MARKERS = [
        "פירוט עבור הכרטיסים בארץ",
        "פירוט עבור הכרטיסים בחו''ל",
        "פירוט עבור הכרטיסים בחו\"ל",
    ]

    HEADER_SIGNATURES = [
        "שם בית עסק", "סכום חיוב", "חיוב לתאריך", "סכום קנייה",
    ]

    @classmethod
    def can_parse(cls, header_line: str, sample_lines: list[str]) -> bool:
        all_text = header_line + " " + " ".join(sample_lines)
        return (
            "שם בית עסק" in all_text
            or "חיובים קודמים" in all_text
            or "סכום חיוב" in all_text
            or any(marker in all_text for marker in cls.SECTION_MARKERS)
        )

    def parse(self, filepath: Path) -> list[Transaction]:
        return self._parse_excel_directly(filepath)

    def _parse_excel_directly(self, filepath: Path) -> list[Transaction]:
        """Parse the Excel file by locating each transaction section."""
        engine = "xlrd" if filepath.suffix.lower() == ".xls" else "openpyxl"
        try:
            df = pd.read_excel(filepath, header=None, dtype=str, engine=engine)
        except Exception:
            df = pd.read_excel(filepath, header=None, dtype=str)

        transactions: list[Transaction] = []
        sections = self._find_detail_sections(df)
        for header_idx, is_foreign in sections:
            section_txs = self._parse_section(df, header_idx, is_foreign)
            transactions.extend(section_txs)

        billing_label = self._determine_billing_label(filepath, transactions)

        for tx in transactions:
            tx.billing_label = billing_label

        return transactions

    def _determine_billing_label(
        self, filepath: Path, transactions: list[Transaction]
    ) -> str:
        """Smart billing period detection using multiple strategies.

        1. Extract month name from filename (English/Hebrew), infer year from transactions
        2. Fall back to the month with the most transactions
        3. Last resort: use the raw filename stem
        """
        month_num = self._month_from_filename(filepath)
        if month_num is not None:
            year = self._infer_year_for_month(month_num, transactions, filepath)
            return f"חיוב {month_num:02d}/{year}"

        label = self._label_from_transaction_majority(transactions)
        if label:
            return label

        return filepath.stem

    @staticmethod
    def _month_from_filename(filepath: Path) -> Optional[int]:
        """Try to extract a month number from the filename."""
        stem = filepath.stem.lower().replace("_", " ").replace("-", " ")

        for name, num in sorted(ENGLISH_MONTHS.items(), key=lambda x: -len(x[0])):
            if name in stem:
                return num

        original_stem = filepath.stem
        for name, num in HEBREW_MONTHS.items():
            if name in original_stem:
                return num

        mm_yyyy = re.search(r"(\d{1,2})[_\-./](\d{4})", stem)
        if mm_yyyy:
            month = int(mm_yyyy.group(1))
            if 1 <= month <= 12:
                return month

        return None

    @staticmethod
    def _infer_year_for_month(
        month: int, transactions: list[Transaction], filepath: Path
    ) -> int:
        """Infer the correct year for a detected month.

        Uses explicit year from filename if present, otherwise picks the year
        that has the most transactions in the given month.
        """
        stem = filepath.stem.lower().replace("_", " ").replace("-", " ")
        year_match = re.search(r"20\d{2}", stem)
        if year_match:
            return int(year_match.group())

        if transactions:
            year_counts = Counter(
                t.date.year for t in transactions if t.date.month == month
            )
            if year_counts:
                return year_counts.most_common(1)[0][0]

        return datetime.now().year

    @staticmethod
    def _label_from_transaction_majority(transactions: list[Transaction]) -> Optional[str]:
        """Use the month that appears most frequently in the transactions."""
        if not transactions:
            return None
        month_counts = Counter((t.date.year, t.date.month) for t in transactions)
        (year, month), _ = month_counts.most_common(1)[0]
        return f"חיוב {month:02d}/{year}"

    def _find_detail_sections(self, df: pd.DataFrame) -> list[tuple[int, bool]]:
        """Find rows that contain section headers with column definitions."""
        sections: list[tuple[int, bool]] = []
        for idx in range(len(df)):
            row_text = " ".join(str(v) for v in df.iloc[idx] if pd.notna(v))
            if "שם בית עסק" in row_text and "תאריך" in row_text:
                is_foreign = "חו\"ל" in row_text or "חו''ל" in row_text
                if not is_foreign and idx > 2:
                    context = " ".join(
                        str(v) for v in df.iloc[max(0, idx - 3) : idx].values.flatten()
                        if pd.notna(v)
                    )
                    is_foreign = "חו\"ל" in context or "חו''ל" in context
                sections.append((idx, is_foreign))
        return sections

    def _parse_section(
        self, df: pd.DataFrame, header_idx: int, is_foreign: bool
    ) -> list[Transaction]:
        """Parse transactions from a section starting at header_idx."""
        header_row = df.iloc[header_idx]
        columns = {str(v).strip(): i for i, v in enumerate(header_row) if pd.notna(v)}

        date_col = self._find_column(columns, ["תאריך"])
        name_col = self._find_column(columns, ["שם בית עסק"])
        amount_col = self._find_column(
            columns, ["סכום חיוב בש''ח", 'סכום חיוב בש"ח', "סכום חיוב"]
        )
        if amount_col is None:
            amount_col = self._find_column(columns, ["סכום קנייה"])

        if date_col is None or name_col is None or amount_col is None:
            return []

        transactions: list[Transaction] = []

        for row_idx in range(header_idx + 1, len(df)):
            row = df.iloc[row_idx]

            if row.isna().all():
                empty_count = 0
                for check_idx in range(row_idx, min(row_idx + 3, len(df))):
                    if df.iloc[check_idx].isna().all():
                        empty_count += 1
                if empty_count >= 2:
                    break
                continue

            row_text = " ".join(str(v) for v in row if pd.notna(v))
            if any(m in row_text for m in self.SECTION_MARKERS) or "מספר חשבון" in row_text:
                break
            if "שם כרטיס" in row_text and "תאריך" in row_text:
                break

            date_val = str(row.iloc[date_col]) if pd.notna(row.iloc[date_col]) else ""
            name_val = str(row.iloc[name_col]) if pd.notna(row.iloc[name_col]) else ""
            amount_val = str(row.iloc[amount_col]) if pd.notna(row.iloc[amount_col]) else ""

            tx_date = self._parse_date(date_val)
            if tx_date is None:
                continue

            name_val = name_val.strip()
            if not name_val:
                continue

            amount = self.parse_amount(amount_val)
            if amount is None:
                continue
            amount = abs(amount)

            suffix = " (חו\"ל)" if is_foreign else ""
            transactions.append(
                Transaction(
                    date=tx_date,
                    description=name_val + suffix,
                    amount=amount,
                    source_bank=self.name,
                )
            )

        return transactions

    @staticmethod
    def _find_column(columns: dict[str, int], candidates: list[str]) -> Optional[int]:
        for candidate in candidates:
            if candidate in columns:
                return columns[candidate]
        for col_name, idx in columns.items():
            for candidate in candidates:
                if candidate in col_name:
                    return idx
        return None

    @staticmethod
    def _parse_date(value: str) -> Optional[date]:
        value = value.strip()
        if not value or value == "nan":
            return None
        for fmt in (
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y",
            "%d/%m/%y", "%d-%m-%Y",
        ):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None
