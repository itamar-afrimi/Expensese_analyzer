from __future__ import annotations

import json
from typing import Optional

from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from models import Transaction, ExpenseReport
from .prompts import CHAT_SYSTEM

console = Console()

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_monthly_summary",
            "description": "Get a summary of expenses for a specific month",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "Year (e.g. 2026)"},
                    "month": {"type": "integer", "description": "Month number (1-12)"},
                },
                "required": ["year", "month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_category_breakdown",
            "description": "Get expense breakdown by category for a specific month",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "month": {"type": "integer"},
                },
                "required": ["year", "month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_months",
            "description": "Compare total and category expenses between two months",
            "parameters": {
                "type": "object",
                "properties": {
                    "year1": {"type": "integer"},
                    "month1": {"type": "integer"},
                    "year2": {"type": "integer"},
                    "month2": {"type": "integer"},
                },
                "required": ["year1", "month1", "year2", "month2"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_expenses",
            "description": "Get the top N largest expenses, optionally for a specific month",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Number of top expenses", "default": 10},
                    "year": {"type": "integer"},
                    "month": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_transactions",
            "description": "Search transactions by text in description",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text"},
                    "year": {"type": "integer"},
                    "month": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
]


class ExpenseChat:
    """Interactive Hebrew chat agent for exploring expense data."""

    def __init__(
        self,
        transactions: list[Transaction],
        budgets: dict[str, float],
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
    ):
        self.transactions = transactions
        self.budgets = budgets
        self.model = model
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self._reports: dict[str, ExpenseReport] = {}
        self._build_reports()

        expense_summary = self._build_expense_summary()
        budget_text = "\n".join(
            f"  {cat}: {limit:,.0f} ש\"ח" for cat, limit in budgets.items()
        )

        self.system_message = CHAT_SYSTEM.format(
            expense_data=expense_summary,
            budgets=budget_text,
        )
        self.messages: list[dict] = [{"role": "system", "content": self.system_message}]

    def _build_reports(self) -> None:
        for tx in self.transactions:
            key = tx.billing_label or f"{tx.date.year}-{tx.date.month:02d}"
            if key not in self._reports:
                self._reports[key] = ExpenseReport(label=key)
            self._reports[key].transactions.append(tx)

    def _build_expense_summary(self) -> str:
        lines = []
        for key in sorted(self._reports.keys()):
            report = self._reports[key]
            lines.append(f"\nחודש {report.label}: סה\"כ {report.total:,.0f} ש\"ח")
            for cat, amount in report.by_category().items():
                lines.append(f"  {cat}: {amount:,.0f} ש\"ח")
        return "\n".join(lines) if lines else "אין נתונים זמינים"

    def _handle_tool_call(self, name: str, args: dict) -> str:
        if name == "get_monthly_summary":
            return self._tool_monthly_summary(args["year"], args["month"])
        elif name == "get_category_breakdown":
            return self._tool_category_breakdown(args["year"], args["month"])
        elif name == "compare_months":
            return self._tool_compare_months(
                args["year1"], args["month1"], args["year2"], args["month2"]
            )
        elif name == "get_top_expenses":
            return self._tool_top_expenses(
                args.get("n", 10), args.get("year"), args.get("month")
            )
        elif name == "search_transactions":
            return self._tool_search(
                args["query"], args.get("year"), args.get("month")
            )
        return json.dumps({"error": "unknown tool"}, ensure_ascii=False)

    def _get_report(self, year: int, month: int) -> Optional[ExpenseReport]:
        key = f"{year}-{month:02d}"
        report = self._reports.get(key)
        if report:
            return report
        for r in self._reports.values():
            if any(t.date.year == year and t.date.month == month for t in r.transactions):
                return r
        return None

    def _tool_monthly_summary(self, year: int, month: int) -> str:
        report = self._get_report(year, month)
        if not report:
            return json.dumps(
                {"error": f"אין נתונים עבור {year}-{month:02d}"}, ensure_ascii=False
            )
        return json.dumps(
            {
                "month": report.label,
                "total": report.total,
                "num_transactions": len(report.transactions),
                "categories": report.by_category(),
            },
            ensure_ascii=False,
        )

    def _tool_category_breakdown(self, year: int, month: int) -> str:
        report = self._get_report(year, month)
        if not report:
            return json.dumps(
                {"error": f"אין נתונים עבור {year}-{month:02d}"}, ensure_ascii=False
            )
        breakdown = report.by_category()
        with_budget = {}
        for cat, spent in breakdown.items():
            budget = self.budgets.get(cat)
            with_budget[cat] = {
                "spent": spent,
                "budget": budget,
                "over": (spent - budget) if budget else None,
            }
        return json.dumps(with_budget, ensure_ascii=False)

    def _tool_compare_months(
        self, year1: int, month1: int, year2: int, month2: int
    ) -> str:
        r1 = self._get_report(year1, month1)
        r2 = self._get_report(year2, month2)
        if not r1 or not r2:
            return json.dumps({"error": "חסרים נתונים לאחד החודשים"}, ensure_ascii=False)
        return json.dumps(
            {
                "month1": {"label": r1.label, "total": r1.total, "categories": r1.by_category()},
                "month2": {"label": r2.label, "total": r2.total, "categories": r2.by_category()},
                "difference": r2.total - r1.total,
            },
            ensure_ascii=False,
        )

    def _tool_top_expenses(
        self, n: int = 10, year: Optional[int] = None, month: Optional[int] = None
    ) -> str:
        txs = self.transactions
        if year and month:
            txs = [t for t in txs if t.date.year == year and t.date.month == month]
        top = sorted(txs, key=lambda t: t.amount, reverse=True)[:n]
        return json.dumps(
            [
                {
                    "date": t.date.isoformat(),
                    "description": t.description,
                    "amount": t.amount,
                    "category": t.category,
                }
                for t in top
            ],
            ensure_ascii=False,
        )

    def _tool_search(
        self, query: str, year: Optional[int] = None, month: Optional[int] = None
    ) -> str:
        txs = self.transactions
        if year and month:
            txs = [t for t in txs if t.date.year == year and t.date.month == month]
        matches = [t for t in txs if query in t.description]
        return json.dumps(
            [
                {
                    "date": t.date.isoformat(),
                    "description": t.description,
                    "amount": t.amount,
                    "category": t.category,
                }
                for t in matches
            ],
            ensure_ascii=False,
        )

    def _send_message(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            tools=TOOLS,
            temperature=0.5,
        )

        message = response.choices[0].message

        while message.tool_calls:
            self.messages.append(message.model_dump())
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                result = self._handle_tool_call(fn_name, fn_args)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=TOOLS,
                temperature=0.5,
            )
            message = response.choices[0].message

        assistant_text = message.content or ""
        self.messages.append({"role": "assistant", "content": assistant_text})
        return assistant_text

    def run(self) -> None:
        """Start the interactive chat loop."""
        console.print(
            Panel(
                "[bold cyan]שלום! אני העוזר הפיננסי שלך 🤖[/bold cyan]\n\n"
                "אפשר לשאול אותי כל שאלה על ההוצאות שלך.\n"
                "למשל:\n"
                '  • "כמה הוצאתי על אוכל החודש?"\n'
                '  • "מה ההוצאה הכי גדולה שלי?"\n'
                '  • "תשווה לי ינואר מול פברואר"\n'
                '  • "איפה אני יכול לחסוך?"\n\n'
                '[dim]הקלד "יציאה" לסיום[/dim]',
                title="💬 צ׳אט הוצאות",
                border_style="cyan",
            )
        )

        while True:
            try:
                user_input = Prompt.ask("\n[bold green]את/ה[/bold green]")
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input.strip():
                continue
            if user_input.strip() in ("יציאה", "exit", "quit", "q"):
                console.print("[dim]להתראות! 👋[/dim]")
                break

            try:
                with console.status("[cyan]חושב...[/cyan]"):
                    answer = self._send_message(user_input)
                console.print(
                    Panel(Markdown(answer), title="🤖 עוזר", border_style="blue")
                )
            except Exception as e:
                console.print(f"[red]שגיאה: {e}[/red]")
