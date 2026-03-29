from __future__ import annotations

import json
from typing import Optional

from openai import OpenAI
from rich.console import Console
from rich.progress import track

from models import Transaction
from store import CategoryStore
from .prompts import CATEGORIZATION_SYSTEM, CATEGORIZATION_USER

console = Console()
BATCH_SIZE = 20


class Categorizer:
    """GPT-powered transaction categorizer with local caching."""

    def __init__(
        self,
        categories: list[str],
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        store: Optional[CategoryStore] = None,
    ):
        self.categories = categories
        self.model = model
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self.store = store or CategoryStore()

    def categorize(
        self, transactions: list[Transaction], force: bool = False
    ) -> list[Transaction]:
        """Categorize transactions, using cache when available."""
        to_categorize: list[Transaction] = []
        cached_count = 0

        for tx in transactions:
            if tx.category and not force:
                cached_count += 1
                continue
            if not force and not self.store.is_user_corrected(tx.uid):
                cached = self.store.get(tx.uid)
                if cached:
                    tx.category = cached
                    cached_count += 1
                    continue
            elif not force and self.store.is_user_corrected(tx.uid):
                tx.category = self.store.get(tx.uid)
                cached_count += 1
                continue
            to_categorize.append(tx)

        if cached_count:
            console.print(f"[dim]נטענו {cached_count} קטגוריות מהמטמון[/dim]")

        if not to_categorize:
            console.print("[green]כל העסקאות כבר מסווגות![/green]")
            return transactions

        console.print(f"[cyan]מסווג {len(to_categorize)} עסקאות עם AI...[/cyan]")

        batches = [
            to_categorize[i : i + BATCH_SIZE]
            for i in range(0, len(to_categorize), BATCH_SIZE)
        ]

        for batch in track(batches, description="מסווג..."):
            results = self._categorize_batch(batch)
            for tx, category in zip(batch, results):
                tx.category = category
                self.store.put(tx.uid, category, source="ai")

        self.store.save()
        console.print(f"[green]סיווג הושלם! {len(to_categorize)} עסקאות חדשות[/green]")
        return transactions

    def _categorize_batch(self, batch: list[Transaction]) -> list[str]:
        """Send a batch of transactions to OpenAI for categorization."""
        tx_text = "\n".join(
            f"- {tx.description} ({tx.amount} ש\"ח, {tx.date.isoformat()})"
            for tx in batch
        )

        system_msg = CATEGORIZATION_SYSTEM.format(
            categories="\n".join(f"- {c}" for c in self.categories)
        )
        user_msg = CATEGORIZATION_USER.format(transactions=tx_text)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)

            if isinstance(parsed, dict) and "categories" in parsed:
                results_list = parsed["categories"]
            elif isinstance(parsed, dict) and "transactions" in parsed:
                results_list = parsed["transactions"]
            elif isinstance(parsed, list):
                results_list = parsed
            else:
                results_list = list(parsed.values())[0] if parsed else []

            categories = []
            for item in results_list:
                if isinstance(item, dict):
                    cat = item.get("category", "אחר")
                elif isinstance(item, str):
                    cat = item
                else:
                    cat = "אחר"

                if cat not in self.categories:
                    cat = "אחר"
                categories.append(cat)

            while len(categories) < len(batch):
                categories.append("אחר")

            return categories[: len(batch)]

        except Exception as e:
            console.print(f"[red]שגיאה בסיווג: {e}[/red]")
            return ["אחר"] * len(batch)
