from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from models import Transaction

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

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

_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{2,4})")
_AMOUNT_RE = re.compile(r"^(-?[\d,]+\.\d{2})")
_SKIP_MARKERS = ["כ\"הס", "ךיראתל בויח", "החנה כ", "םוכס", "בויחה", "הלמע"]


def _is_available() -> bool:
    return pdfplumber is not None


def _parse_date(val: str) -> Optional[date]:
    val = val.strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(val: str) -> Optional[float]:
    cleaned = val.strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _reverse_hebrew_word(word: str) -> str:
    """Reverse a Hebrew word's characters (PDF stores visual LTR order)."""
    return word[::-1]


def _fix_hebrew_text(text: str) -> str:
    """Fix Hebrew text extracted from PDF: reverse each Hebrew word's
    characters and reverse the overall word order."""
    hebrew_re = re.compile(r"[\u0590-\u05FF]")
    tokens = text.split()
    fixed = []
    for t in tokens:
        if hebrew_re.search(t):
            fixed.append(_reverse_hebrew_word(t))
        else:
            fixed.append(t)
    fixed.reverse()
    return " ".join(fixed)


def _extract_business_name(middle: str, is_foreign: bool = False) -> str:
    """Extract and fix business name from a transaction line."""
    tokens = middle.split()
    payment_methods = {
        "דיינ.שת", "שת.דיינ", "גצוה", "אל", "עבק.ה", "ןוערפ", "פירעון",
    }
    tokens = [t for t in tokens if t not in payment_methods]

    if is_foreign:
        tokens = [t for t in tokens if t not in ("א", "ל")]
        cleaned = " ".join(tokens).strip()
        cleaned = re.sub(r"\d{2}/\d{2}/\d{2,4}", "", cleaned).strip()
        cleaned = re.sub(r"[€$£]\s*", "", cleaned).strip()
        cleaned = re.sub(r"^([A-Z])\s+([A-Z])", r"\1\2", cleaned)
        return cleaned

    hebrew_re = re.compile(r"[\u0590-\u05FF]")
    fixed_tokens = []
    for t in tokens:
        if hebrew_re.search(t):
            fixed_tokens.append(_reverse_hebrew_word(t))
        else:
            fixed_tokens.append(t)
    fixed_tokens.reverse()

    name = " ".join(fixed_tokens).strip()
    return name if name else middle.strip()


def parse_pdf(filepath: Path) -> list[Transaction]:
    """Parse an Israeli credit card PDF statement."""
    if not _is_available():
        raise ImportError("pdfplumber is required for PDF parsing. Install with: pip install pdfplumber")

    pdf = pdfplumber.open(filepath)
    transactions: list[Transaction] = []
    is_foreign_section = False

    for page in pdf.pages:
        text = page.extract_text()
        if not text:
            continue

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            if "ל\"וחב תושיכר" in line or "ל\"וחב" in line and "תושיכר" in line:
                is_foreign_section = True
                continue
            if "ץראב" in line and ("וכוז" in line or "וביוח" in line):
                is_foreign_section = False
                continue

            if any(m in line for m in _SKIP_MARKERS):
                continue

            dates = _DATE_RE.findall(line)
            amount_match = _AMOUNT_RE.match(line)

            if not dates or not amount_match:
                continue

            amount = _parse_amount(amount_match.group(1))
            if amount is None or amount == 0:
                continue

            tx_date_str = dates[-1]
            tx_date = _parse_date(tx_date_str)
            if tx_date is None:
                continue

            after_amount = line[amount_match.end():].strip()
            before_date = after_amount
            for d in dates:
                idx = before_date.rfind(d)
                if idx >= 0:
                    before_date = before_date[:idx].strip()

            if is_foreign_section:
                parts = re.split(r"[\d,.]+\s+[\d.]+\s+\d{2}/\d{2}/\d{2}", after_amount, maxsplit=1)
                if len(parts) > 1:
                    middle = parts[1]
                    middle = re.sub(r"^[\s\d,.$€£-]+", "", middle).strip()
                    middle = re.sub(r"\s+[אל]\s*$", "", middle).strip()
                else:
                    middle = before_date
            else:
                second_amount = re.match(r"(-?[\d,]+\.\d{2})\s+", after_amount)
                if second_amount:
                    middle = after_amount[second_amount.end():].strip()
                else:
                    middle = after_amount

                for d in dates:
                    idx = middle.rfind(d)
                    if idx >= 0:
                        middle = middle[:idx].strip()

            business = _extract_business_name(middle, is_foreign=is_foreign_section)
            if not business or len(business) < 2:
                continue

            suffix = " (חו\"ל)" if is_foreign_section else ""
            transactions.append(Transaction(
                date=tx_date,
                description=business + suffix,
                amount=abs(amount),
                source_bank="כרטיס אשראי (PDF)",
            ))

    pdf.close()

    billing_label = _determine_billing_label(filepath, transactions)
    for tx in transactions:
        tx.billing_label = billing_label

    return transactions


def _determine_billing_label(filepath: Path, transactions: list[Transaction]) -> str:
    month = _month_from_filename(filepath)
    if month is not None:
        year = _infer_year_for_month(month, transactions, filepath)
        return f"חיוב {month:02d}/{year}"

    if transactions:
        month_counts = Counter((t.date.year, t.date.month) for t in transactions)
        (year, month), _ = month_counts.most_common(1)[0]
        return f"חיוב {month:02d}/{year}"

    return filepath.stem


def _month_from_filename(filepath: Path) -> Optional[int]:
    stem = filepath.stem.lower().replace("_", " ").replace("-", " ")
    for name, num in sorted(ENGLISH_MONTHS.items(), key=lambda x: -len(x[0])):
        if name in stem:
            return num
    original = filepath.stem
    for name, num in HEBREW_MONTHS.items():
        if name in original:
            return num
    mm_yyyy = re.search(r"(\d{1,2})[_\-./](\d{4})", stem)
    if mm_yyyy:
        m = int(mm_yyyy.group(1))
        if 1 <= m <= 12:
            return m
    return None


def _infer_year_for_month(
    month: int, transactions: list[Transaction], filepath: Path
) -> int:
    stem = filepath.stem.lower().replace("_", " ").replace("-", " ")
    year_match = re.search(r"20\d{2}", stem)
    if year_match:
        return int(year_match.group())
    if transactions:
        year_counts = Counter(t.date.year for t in transactions if t.date.month == month)
        if year_counts:
            return year_counts.most_common(1)[0][0]
    return datetime.now().year
