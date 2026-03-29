from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import pandas as pd

from models import Transaction

EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlsb"}


class BankParser(ABC):
    """Base class for Israeli bank CSV/Excel parsers."""

    name: str = "base"

    @classmethod
    @abstractmethod
    def can_parse(cls, header_line: str, sample_lines: list[str]) -> bool:
        """Return True if this parser recognises the file format."""

    @abstractmethod
    def parse(self, filepath: Path) -> list[Transaction]:
        """Parse the file and return normalised transactions."""

    @staticmethod
    def is_excel(filepath: Path) -> bool:
        return filepath.suffix.lower() in EXCEL_EXTENSIONS

    @staticmethod
    def read_file(filepath: Path) -> str:
        """Read a CSV or Excel file, returning CSV-formatted text.

        Excel files are converted to CSV via pandas so downstream
        csv.DictReader logic works unchanged.
        """
        if filepath.suffix.lower() in EXCEL_EXTENSIONS:
            return BankParser._read_excel_as_csv(filepath)

        for encoding in ("utf-8-sig", "utf-8", "windows-1255", "iso-8859-8"):
            try:
                return filepath.read_text(encoding=encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError(f"Could not decode {filepath} with any known encoding")

    @staticmethod
    def _read_excel_as_csv(filepath: Path) -> str:
        """Read an Excel file and return its contents as CSV text.

        Israeli bank Excel exports sometimes have junk header rows before
        the actual data table.  We try each sheet and look for the first
        row that looks like a header (contains Hebrew column names).
        """
        engine = "xlrd" if filepath.suffix.lower() == ".xls" else "openpyxl"

        try:
            xls = pd.ExcelFile(filepath, engine=engine)
        except Exception:
            xls = pd.ExcelFile(filepath)

        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name, header=None, dtype=str)
            if df.empty:
                continue

            header_row_idx = BankParser._find_header_row(df)
            if header_row_idx is not None:
                df.columns = df.iloc[header_row_idx].astype(str).str.strip()
                df = df.iloc[header_row_idx + 1 :].reset_index(drop=True)
                df = df.dropna(how="all")
                buf = io.StringIO()
                df.to_csv(buf, index=False, encoding="utf-8")
                return buf.getvalue()

        df = xls.parse(0, dtype=str)
        df = df.dropna(how="all")
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8")
        return buf.getvalue()

    @staticmethod
    def _find_header_row(df: pd.DataFrame, max_scan: int = 40) -> Optional[int]:
        """Scan the first rows for one that looks like a Hebrew table header."""
        hebrew_markers = [
            "תאריך", "תיאור", "תאור", "פירוט", "סכום",
            "חובה", "זכות", "יתרה", "אסמכתא",
            "שם בית עסק", "סכום חיוב",
        ]
        for idx in range(min(max_scan, len(df))):
            row_text = " ".join(str(v) for v in df.iloc[idx] if pd.notna(v))
            hits = sum(1 for m in hebrew_markers if m in row_text)
            if hits >= 2:
                return idx
        return None

    @staticmethod
    def parse_amount(value: str) -> Optional[float]:
        """Parse an amount string, handling Hebrew-style formatting."""
        if not value or not value.strip():
            return None
        cleaned = value.strip().replace(",", "").replace("₪", "").replace(" ", "")
        if cleaned in ("-", "", "nan", "None"):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
