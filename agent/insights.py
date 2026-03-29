from __future__ import annotations

from typing import Optional

from openai import OpenAI
from rich.console import Console

from models import ExpenseReport
from .prompts import INSIGHTS_SYSTEM, INSIGHTS_USER

console = Console()


class InsightsGenerator:
    """GPT-powered spending insights in Hebrew."""

    def __init__(
        self,
        budgets: dict[str, float],
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
    ):
        self.budgets = budgets
        self.model = model
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()

    def generate(self, report: ExpenseReport) -> str:
        """Generate Hebrew insights for a billing period report."""
        category_breakdown = "\n".join(
            f"  {cat}: {amount:,.0f} ש\"ח" for cat, amount in report.by_category().items()
        )

        budget_lines = []
        for cat, limit in self.budgets.items():
            spent = report.by_category().get(cat, 0)
            status = "✅" if spent <= limit else "🚨"
            diff = spent - limit
            budget_lines.append(
                f"  {cat}: תקציב {limit:,.0f} ש\"ח | הוצאה {spent:,.0f} ש\"ח | "
                f"{'חריגה' if diff > 0 else 'נותר'} {abs(diff):,.0f} ש\"ח {status}"
            )

        user_msg = INSIGHTS_USER.format(
            month_label=report.label,
            total=f"{report.total:,.0f}",
            category_breakdown=category_breakdown,
            budgets="\n".join(budget_lines),
            extra_context=f"טווח תאריכים: {report.date_range_str}" if report.transactions else "",
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": INSIGHTS_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
            )
            return response.choices[0].message.content or "לא הצלחתי לייצר תובנות."
        except Exception as e:
            return f"שגיאה בייצור תובנות: {e}"
