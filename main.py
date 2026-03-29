#!/usr/bin/env python3
"""AI-Powered Monthly Expenses Analyzer — CLI Entry Point."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel

from models import Transaction, ExpenseReport, Receipt
from parsers import detect_and_parse
from store import CategoryStore
from agent.categorizer import Categorizer
from agent.insights import InsightsGenerator
from agent.chat import ExpenseChat
import visualizer
from report_generator import generate_html_report

console = Console()
CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_api_key(config: dict) -> str:
    key = os.environ.get("OPENAI_API_KEY") or config.get("openai", {}).get("api_key")
    if not key:
        console.print(
            "[red]שגיאה: לא נמצא מפתח OpenAI API.[/red]\n"
            "הגדר את המשתנה OPENAI_API_KEY או הוסף api_key ב-config.yaml"
        )
        sys.exit(1)
    return key


def collect_files(args) -> list[Path]:
    files: list[Path] = []
    if hasattr(args, "files") and args.files:
        for f in args.files:
            p = Path(f)
            if p.exists():
                files.append(p)
            else:
                console.print(f"[yellow]אזהרה: הקובץ {f} לא נמצא[/yellow]")
    if hasattr(args, "dir") and args.dir:
        d = Path(args.dir)
        if d.is_dir():
            for ext in ("*.csv", "*.xls", "*.xlsx", "*.xlsm", "*.pdf"):
                files.extend(d.glob(ext))
            files = sorted(set(files))
        else:
            console.print(f"[yellow]אזהרה: התיקייה {args.dir} לא נמצאה[/yellow]")
    return files


def parse_files(files: list[Path]) -> dict[str, list[Transaction]]:
    """Parse files and return transactions grouped by billing period label."""
    result: dict[str, list[Transaction]] = {}
    for filepath in files:
        try:
            txs = detect_and_parse(filepath)
            console.print(f"  [green]✓[/green] {filepath.name}: {len(txs)} עסקאות ({txs[0].source_bank})")

            label = txs[0].billing_label if txs[0].billing_label else filepath.stem
            if label not in result:
                result[label] = []
            result[label].extend(txs)
        except Exception as e:
            console.print(f"  [red]✗[/red] {filepath.name}: {e}")
    return result


def _inject_fixed_expenses(
    grouped: dict[str, list[Transaction]], fixed_expenses: list[dict]
) -> None:
    """Add fixed monthly expenses (e.g. rent) to each billing period."""
    if not fixed_expenses:
        return

    for label, txs in grouped.items():
        month_match = re.search(r"(\d{2})/(\d{4})", label)
        if month_match:
            m, y = int(month_match.group(1)), int(month_match.group(2))
            tx_date = date(y, m, 1)
        elif txs:
            tx_date = txs[0].date
        else:
            tx_date = date.today()

        freq_divisors = {"monthly": 1, "bi-monthly": 2, "quarterly": 3, "yearly": 12}
        for entry in fixed_expenses:
            freq = entry.get("frequency", "monthly")
            divisor = freq_divisors.get(freq, 1)
            monthly_amount = round(float(entry["amount"]) / divisor, 2)
            txs.append(
                Transaction(
                    date=tx_date,
                    description=entry["description"],
                    amount=monthly_amount,
                    category=entry.get("category"),
                    source_bank="הוצאה קבועה",
                    billing_label=label,
                )
            )


def build_reports(grouped: dict[str, list[Transaction]]) -> list[ExpenseReport]:
    """Build one ExpenseReport per billing period."""
    reports = []
    for label, txs in grouped.items():
        reports.append(ExpenseReport(label=label, transactions=txs))
    return reports


def cmd_analyze(args) -> None:
    config = load_config()
    api_key = get_api_key(config)
    categories = config.get("categories", [])
    budgets = config.get("budgets", {})

    console.print(Panel("[bold cyan]📊 מנתח הוצאות AI[/bold cyan]", border_style="cyan"))

    files = collect_files(args)
    if not files:
        console.print("[red]שגיאה: לא צוינו קבצים. השתמש ב --files או --dir[/red]")
        return

    console.print(f"\n[dim]טוען {len(files)} קבצים...[/dim]")
    grouped = parse_files(files)

    all_transactions = [tx for txs in grouped.values() for tx in txs]
    if not all_transactions:
        console.print("[red]לא נמצאו עסקאות בקבצים[/red]")
        return

    fixed_expenses = config.get("fixed_expenses", [])
    if fixed_expenses:
        _inject_fixed_expenses(grouped, fixed_expenses)
        names = ", ".join(e["description"] for e in fixed_expenses)
        console.print(f"  [green]✓[/green] הוצאות קבועות: {names}")
        all_transactions = [tx for txs in grouped.values() for tx in txs]

    if hasattr(args, "include_receipts") and args.include_receipts:
        from receipt_store import ReceiptStore
        receipt_store = ReceiptStore()
        receipt_txs = receipt_store.to_transactions()
        if receipt_txs:
            console.print(f"  [green]✓[/green] קבלות סרוקות: {len(receipt_txs)} עסקאות")
            for label, txs in grouped.items():
                txs.extend(receipt_txs)
                break

    console.print(f"[dim]סה\"כ: {len(all_transactions)} עסקאות[/dim]\n")

    console.print("[cyan]שלב 1:[/cyan] סיווג עסקאות עם AI...")
    store = CategoryStore()
    categorizer = Categorizer(
        categories=categories,
        model=config.get("openai", {}).get("categorization_model", "gpt-4o-mini"),
        api_key=api_key,
        store=store,
    )
    all_transactions = categorizer.categorize(all_transactions, force=args.recategorize)

    reports = build_reports(grouped)

    console.print("[cyan]שלב 2:[/cyan] מייצר תרשימים...")
    chart_data: dict[str, str] = {}
    for report in reports:
        _, pie_b64 = visualizer.pie_chart(report)
        chart_data[f"pie_{report.label}"] = pie_b64
        _, budget_b64 = visualizer.budget_bar_chart(report, budgets)
        chart_data[f"budget_{report.label}"] = budget_b64

    console.print("[cyan]שלב 3:[/cyan] מייצר תובנות AI...")
    insights_gen = InsightsGenerator(
        budgets=budgets,
        model=config.get("openai", {}).get("chat_model", "gpt-4o"),
        api_key=api_key,
    )
    insights_data: dict[str, str] = {}
    for report in reports:
        insight_text = insights_gen.generate(report)
        insights_data[report.label] = insight_text

    console.print("[cyan]שלב 4:[/cyan] מייצר דוח HTML...")
    report_path = generate_html_report(
        reports=reports,
        budgets=budgets,
        insights=insights_data,
        charts=chart_data,
        open_in_browser=not args.no_open if hasattr(args, "no_open") else True,
    )

    console.print(f"\n[bold green]הדוח מוכן![/bold green] 📄 {report_path}")


def cmd_chat(args) -> None:
    config = load_config()
    api_key = get_api_key(config)
    budgets = config.get("budgets", {})

    files = collect_files(args)
    if not files:
        console.print("[red]שגיאה: לא צוינו קבצים[/red]")
        return
    grouped = parse_files(files)
    all_transactions = [tx for txs in grouped.values() for tx in txs]
    if not all_transactions:
        console.print("[red]לא נמצאו עסקאות[/red]")
        return

    categories = config.get("categories", [])
    store = CategoryStore()
    categorizer = Categorizer(
        categories=categories,
        model=config.get("openai", {}).get("categorization_model", "gpt-4o-mini"),
        api_key=api_key,
        store=store,
    )
    all_transactions = categorizer.categorize(all_transactions)

    chat = ExpenseChat(
        transactions=all_transactions,
        budgets=budgets,
        model=config.get("openai", {}).get("chat_model", "gpt-4o"),
        api_key=api_key,
    )
    chat.run()


def cmd_scan(args) -> None:
    config = load_config()
    api_key = get_api_key(config)
    categories = config.get("categories", [])

    console.print(Panel("[bold cyan]📷 סורק קבלות AI[/bold cyan]", border_style="cyan"))

    photos: list[Path] = []
    if args.photo:
        for p in args.photo:
            path = Path(p)
            if path.exists():
                photos.append(path)
            else:
                console.print(f"[yellow]אזהרה: הקובץ {p} לא נמצא[/yellow]")
    if args.dir:
        d = Path(args.dir)
        if d.is_dir():
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.heic", "*.webp"):
                photos.extend(d.glob(ext))
            photos = sorted(set(photos))

    if not photos:
        console.print("[red]שגיאה: לא צוינו תמונות. השתמש ב --photo או --dir[/red]")
        return

    from agent.receipt_scanner import ReceiptScanner
    from receipt_store import ReceiptStore

    scanner = ReceiptScanner(
        categories=categories,
        model=config.get("openai", {}).get("chat_model", "gpt-4o"),
        api_key=api_key,
    )
    receipt_store = ReceiptStore()

    drive_folder = config.get("google_drive", {}).get("receipts_folder")

    for photo in photos:
        console.print(f"\n[cyan]סורק:[/cyan] {photo.name}...")
        try:
            receipt = scanner.scan(photo)
            receipt_store.add(receipt)

            console.print(f"  [green]✓[/green] {receipt.store_name}")
            console.print(f"    תאריך: {receipt.date.strftime('%d/%m/%Y')}")
            console.print(f"    סכום: {receipt.total:,.1f} ש\"ח")
            console.print(f"    קטגוריה: {receipt.suggested_category or 'לא זוהתה'}")
            if receipt.items:
                console.print(f"    פריטים: {len(receipt.items)}")

            if drive_folder:
                try:
                    from drive_upload import upload_to_drive
                    url = upload_to_drive(photo, drive_folder)
                    receipt.drive_url = url
                    console.print(f"    [green]הועלה ל-Google Drive[/green]")
                except Exception as e:
                    console.print(f"    [yellow]העלאה ל-Drive נכשלה: {e}[/yellow]")

        except Exception as e:
            console.print(f"  [red]✗[/red] שגיאה: {e}")

    receipt_store.save()
    console.print(f"\n[bold green]סריקה הושלמה![/bold green] {len(photos)} קבלות עובדו")
    console.print(f"[dim]השתמש ב --include-receipts בפקודת analyze כדי לכלול את הקבלות בדוח[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="מנתח הוצאות חכם מבוסס AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="פקודות זמינות")

    analyze_parser = subparsers.add_parser("analyze", help="ניתוח הוצאות מקבצי CSV/Excel")
    analyze_parser.add_argument("--files", nargs="+", help="קבצי CSV/XLS/XLSX לניתוח")
    analyze_parser.add_argument("--dir", help="תיקייה המכילה קבצי CSV/Excel")
    analyze_parser.add_argument(
        "--recategorize", action="store_true", help="סיווג מחדש (התעלם מהמטמון)"
    )
    analyze_parser.add_argument(
        "--no-open", action="store_true", help="אל תפתח את הדוח בדפדפן"
    )
    analyze_parser.add_argument(
        "--include-receipts", action="store_true", help="כלול קבלות סרוקות בדוח"
    )

    chat_parser = subparsers.add_parser("chat", help="צ'אט אינטראקטיבי על ההוצאות")
    chat_parser.add_argument("--files", nargs="+", help="קבצי CSV/XLS/XLSX לטעינה")
    chat_parser.add_argument("--dir", help="תיקייה המכילה קבצי CSV/Excel")

    scan_parser = subparsers.add_parser("scan", help="סריקת קבלות עם AI Vision")
    scan_parser.add_argument("--photo", nargs="+", help="תמונות קבלות לסריקה")
    scan_parser.add_argument("--dir", help="תיקייה המכילה תמונות קבלות")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "scan":
        cmd_scan(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
