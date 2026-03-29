from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path
from typing import Optional

from openai import OpenAI

from models import Receipt

SCAN_SYSTEM_PROMPT = """אתה מומחה בקריאת קבלות וחשבוניות ישראליות.
תקבל תמונה של קבלה ותחלץ ממנה את המידע הבא בפורמט JSON מדויק.

הקטגוריות האפשריות הן:
{categories}

החזר JSON בפורמט הבא בלבד (בלי טקסט נוסף):
{{
  "store_name": "שם בית העסק",
  "date": "YYYY-MM-DD",
  "items": [
    {{"name": "שם הפריט", "price": 0.00}},
    ...
  ],
  "total": 0.00,
  "suggested_category": "שם הקטגוריה"
}}

כללים:
- אם לא ניתן לקרוא את התאריך, השתמש בתאריך של היום
- אם לא ניתן לזהות פריטים בודדים, החזר רשימה ריקה
- הסכום הכולל חייב להיות מספר
- בחר את הקטגוריה המתאימה ביותר מהרשימה
"""


class ReceiptScanner:
    """Scan receipt photos using GPT-4o Vision."""

    def __init__(
        self,
        categories: list[str],
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
    ):
        self.categories = categories
        self.model = model
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()

    def scan(self, photo_path: Path) -> Receipt:
        """Scan a receipt photo and return extracted data."""
        photo_path = Path(photo_path)
        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")

        b64_image = self._encode_image(photo_path)
        mime_type = self._get_mime_type(photo_path)

        system_msg = SCAN_SYSTEM_PROMPT.format(
            categories="\n".join(f"- {c}" for c in self.categories)
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "אנא חלץ את המידע מהקבלה הזו:",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64_image}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            temperature=0.1,
            max_tokens=2000,
        )

        content = response.choices[0].message.content or "{}"
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        parsed = json.loads(content)

        receipt_date = date.today()
        if parsed.get("date"):
            try:
                receipt_date = date.fromisoformat(parsed["date"])
            except ValueError:
                pass

        return Receipt(
            store_name=parsed.get("store_name", "לא ידוע"),
            date=receipt_date,
            items=parsed.get("items", []),
            total=float(parsed.get("total", 0)),
            suggested_category=parsed.get("suggested_category"),
            photo_path=str(photo_path),
        )

    @staticmethod
    def _encode_image(path: Path) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _get_mime_type(path: Path) -> str:
        suffix = path.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".heic": "image/heic",
            ".gif": "image/gif",
        }
        return mime_map.get(suffix, "image/jpeg")
