from __future__ import annotations

from pathlib import Path

from models import Transaction
from .base import BankParser, EXCEL_EXTENSIONS
from .leumi import LeumiParser
from .hapoalim import HapoalimParser
from .discount import DiscountParser
from .mizrahi import MizrahiParser
from .credit_card import CreditCardParser
from .credit_card_pdf import parse_pdf as parse_credit_card_pdf, _is_available as pdf_available

ALL_PARSERS: list[type[BankParser]] = [
    CreditCardParser,
    LeumiParser,
    HapoalimParser,
    DiscountParser,
    MizrahiParser,
]

SUPPORTED_EXTENSIONS = {".csv", ".pdf"} | EXCEL_EXTENSIONS


def detect_and_parse(filepath: Path) -> list[Transaction]:
    """Auto-detect bank format and parse a CSV, Excel, or PDF file."""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {filepath.suffix}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if filepath.suffix.lower() == ".pdf":
        if not pdf_available():
            raise ImportError("pdfplumber is required for PDF parsing. Install: pip install pdfplumber")
        transactions = parse_credit_card_pdf(filepath)
        if transactions:
            return transactions
        raise ValueError(f"No transactions found in PDF: {filepath}")

    content = BankParser.read_file(filepath)
    lines = content.splitlines()

    if not lines:
        raise ValueError(f"Empty file: {filepath}")

    header_line = lines[0]
    sample_lines = lines[1:30]

    for parser_cls in ALL_PARSERS:
        if parser_cls.can_parse(header_line, sample_lines):
            parser = parser_cls()
            transactions = parser.parse(filepath)
            if transactions:
                return transactions

    raise ValueError(
        f"Could not detect bank format for {filepath}. "
        f"Header: {header_line[:100]}..."
    )
