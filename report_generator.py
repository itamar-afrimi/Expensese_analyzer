"""Generate a beautiful RTL Hebrew HTML report of expense analysis."""
from __future__ import annotations

import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from models import ExpenseReport, Transaction

OUTPUT_DIR = Path(__file__).parent / "output"


def _nis(amount: float) -> str:
    return f"{amount:,.0f}"


def _status_badge(spent: float, budget: float) -> str:
    diff = spent - budget
    if diff <= 0:
        pct = (spent / budget * 100) if budget else 0
        return f'<span class="badge badge-ok">בתקציב ({pct:.0f}%)</span>'
    return f'<span class="badge badge-over">חריגה של {_nis(diff)} ש"ח</span>'


def _progress_bar(spent: float, budget: float) -> str:
    pct = min((spent / budget * 100) if budget else 0, 100)
    color = "#2ecc71" if spent <= budget else "#e74c3c"
    over = spent > budget
    over_pct = min(((spent - budget) / budget * 100), 100) if over else 0
    return f'''<div class="progress-bar">
        <div class="progress-fill" style="width:{pct}%;background:{color}"></div>
        {"" if not over else f'<div class="progress-over" style="width:{over_pct}%"></div>'}
    </div>'''


def generate_html_report(
    reports: list[ExpenseReport],
    budgets: dict[str, float],
    insights: dict[str, str],
    charts: dict[str, str],
    output_path: Optional[Path] = None,
    open_in_browser: bool = True,
    income_map: Optional[dict[str, float]] = None,
    default_income: float = 0,
) -> Path:
    out = output_path or OUTPUT_DIR / "expense_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    income_map = income_map or {}
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    if len(reports) == 1:
        title = f"דוח הוצאות — {reports[0].label}"
    else:
        labels = sorted(r.label for r in reports)
        title = f"דוח הוצאות — {labels[0]} עד {labels[-1]}"

    period_sections = []
    for report in reports:
        inc = income_map.get(report.label, default_income)
        period_sections.append(_render_period_section(report, budgets, insights, charts, inc))

    all_transactions_html = _render_all_transactions(reports)
    summary_html = _render_summary_cards(reports, income_map, default_income)
    overview_html = _render_monthly_overview(reports, income_map, default_income) if len(reports) > 1 else ""

    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
            background: #f0f2f5;
            color: #1a1a2e;
            direction: rtl;
            line-height: 1.6;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; padding: 20px; }}
        header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: white;
            padding: 40px 20px;
            text-align: center;
            border-radius: 16px;
            margin-bottom: 30px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            position: relative;
        }}
        header h1 {{ font-size: 2.2em; margin-bottom: 8px; }}
        header .subtitle {{ opacity: 0.8; font-size: 1.1em; }}
        .print-btn {{
            position: absolute;
            top: 16px;
            left: 16px;
            background: rgba(255,255,255,0.2);
            color: white;
            border: 1px solid rgba(255,255,255,0.4);
            padding: 8px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.95em;
            font-weight: 600;
            transition: background 0.2s;
        }}
        .print-btn:hover {{ background: rgba(255,255,255,0.35); }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        }}
        .summary-card .number {{ font-size: 1.8em; font-weight: bold; color: #0f3460; }}
        .summary-card .number.positive {{ color: #2ecc71; }}
        .summary-card .number.negative {{ color: #e74c3c; }}
        .summary-card .label {{ color: #666; margin-top: 4px; }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 24px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        }}
        .card h2 {{
            font-size: 1.5em;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 2px solid #f0f2f5;
            color: #1a1a2e;
        }}
        .card h3 {{ font-size: 1.2em; margin: 16px 0 12px; color: #16213e; }}
        table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
        th {{
            background: #f8f9fa;
            padding: 12px 16px;
            text-align: right;
            font-weight: 600;
            color: #444;
            border-bottom: 2px solid #e0e0e0;
        }}
        td {{ padding: 10px 16px; border-bottom: 1px solid #f0f0f0; }}
        tr:hover td {{ background: #fafbfc; }}
        .amount {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
        .total-row td {{
            font-weight: bold;
            font-size: 1.1em;
            border-top: 2px solid #1a1a2e;
            background: #f8f9fa;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
        }}
        .badge-ok {{ background: #d4edda; color: #155724; }}
        .badge-over {{ background: #f8d7da; color: #721c24; }}
        .progress-bar {{
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: visible;
            position: relative;
            margin-top: 4px;
        }}
        .progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
        .progress-over {{
            height: 100%;
            background: #e74c3c;
            border-radius: 0 4px 4px 0;
            position: absolute;
            top: 0;
            right: 0;
            opacity: 0.5;
        }}
        .chart-img {{
            width: 100%;
            max-width: 800px;
            display: block;
            margin: 20px auto;
            border-radius: 8px;
        }}
        .insights-box {{
            background: #f0f7ff;
            border-right: 4px solid #0f3460;
            padding: 20px 24px;
            border-radius: 0 8px 8px 0;
            margin: 16px 0;
            line-height: 1.8;
            white-space: pre-wrap;
        }}
        .tx-table {{ font-size: 0.9em; }}
        .tx-table td {{ padding: 8px 12px; }}
        .category-tag {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.85em;
            background: #e8eaf6;
            color: #283593;
        }}
        .date-range {{
            font-size: 0.95em;
            color: #666;
            margin-bottom: 16px;
        }}
        .income-row {{ background: #f0fff0; }}
        .income-row td {{ color: #155724; }}
        .savings-row td {{ font-weight: bold; }}
        .period-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .period-header .period-stats {{
            display: flex;
            gap: 20px;
            font-size: 0.95em;
        }}
        .period-header .period-stats .stat {{
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .period-header .period-stats .stat-value {{
            font-size: 1.3em;
            font-weight: bold;
        }}
        .period-header .period-stats .stat-label {{
            font-size: 0.8em;
            color: #666;
        }}
        footer {{
            text-align: center;
            padding: 30px;
            color: #999;
            font-size: 0.9em;
        }}
        @media print {{
            body {{ background: white; font-size: 11pt; }}
            .container {{ padding: 0; max-width: 100%; }}
            .card {{ box-shadow: none; border: 1px solid #ddd; page-break-inside: avoid; break-inside: avoid; }}
            header {{
                background: #1a1a2e !important;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
                border-radius: 0;
                margin-bottom: 20px;
                page-break-after: avoid;
            }}
            .print-btn {{ display: none !important; }}
            .summary-cards {{ page-break-inside: avoid; break-inside: avoid; }}
            .summary-card {{
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
            .chart-img {{ max-width: 600px; page-break-inside: avoid; break-inside: avoid; }}
            .insights-box {{ page-break-inside: avoid; break-inside: avoid; }}
            footer {{ display: none; }}
            table {{ font-size: 10pt; page-break-inside: auto; }}
            tr {{ page-break-inside: avoid; break-inside: avoid; }}
            .badge {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            .badge-ok, .badge-over {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            .progress-bar, .progress-fill {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            .income-row {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            .period-section {{ page-break-before: auto; }}
        }}
        @page {{
            size: A4;
            margin: 12mm;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <button class="print-btn" onclick="window.print()">📄 שמור כ-PDF</button>
            <h1>{title}</h1>
            <div class="subtitle">נוצר ב-{now} | מבוסס AI</div>
        </header>

        {summary_html}

        {overview_html}

        {"".join(period_sections)}

        {all_transactions_html}

        <footer>
            נוצר אוטומטית על ידי מנתח הוצאות AI
        </footer>
    </div>
</body>
</html>"""

    out.write_text(html, encoding="utf-8")

    if open_in_browser:
        webbrowser.open(f"file://{out.resolve()}")

    return out


def _render_summary_cards(
    reports: list[ExpenseReport],
    income_map: dict[str, float],
    default_income: float,
) -> str:
    total_expenses = sum(r.total for r in reports)
    total_income = sum(income_map.get(r.label, default_income) for r in reports)
    savings = total_income - total_expenses
    savings_cls = "positive" if savings >= 0 else "negative"
    num_tx = sum(len(r.transactions) for r in reports)
    num_periods = len(reports)

    income_card = ""
    if total_income > 0:
        savings_pct = (savings / total_income * 100) if total_income else 0
        income_card = f'''
        <div class="summary-card">
            <div class="number">{_nis(total_income)}</div>
            <div class="label">סה"כ הכנסה (ש"ח)</div>
        </div>
        <div class="summary-card">
            <div class="number {savings_cls}">{_nis(savings)}</div>
            <div class="label">{"חיסכון" if savings >= 0 else "גירעון"} ({savings_pct:+.0f}%)</div>
        </div>'''

    return f'''
    <div class="summary-cards">
        <div class="summary-card">
            <div class="number">{_nis(total_expenses)}</div>
            <div class="label">סה"כ הוצאות (ש"ח)</div>
        </div>
        {income_card}
        <div class="summary-card">
            <div class="number">{num_tx}</div>
            <div class="label">עסקאות</div>
        </div>
        <div class="summary-card">
            <div class="number">{num_periods}</div>
            <div class="label">תקופות חיוב</div>
        </div>
    </div>'''


def _render_monthly_overview(
    reports: list[ExpenseReport],
    income_map: dict[str, float],
    default_income: float,
) -> str:
    rows = ""
    total_income_all = 0
    total_expense_all = 0
    for r in sorted(reports, key=lambda x: x.label):
        inc = income_map.get(r.label, default_income)
        total_income_all += inc
        total_expense_all += r.total
        savings = inc - r.total
        sav_color = "#155724" if savings >= 0 else "#721c24"
        rows += f"""<tr>
            <td>{r.label}</td>
            <td class="amount">{_nis(inc)} ש"ח</td>
            <td class="amount">{_nis(r.total)} ש"ח</td>
            <td class="amount" style="color:{sav_color}">{_nis(savings)} ש"ח</td>
            <td>{len(r.transactions)}</td>
        </tr>"""

    total_savings = total_income_all - total_expense_all
    sav_color = "#155724" if total_savings >= 0 else "#721c24"
    rows += f"""<tr class="total-row">
        <td>סה"כ</td>
        <td class="amount">{_nis(total_income_all)} ש"ח</td>
        <td class="amount">{_nis(total_expense_all)} ש"ח</td>
        <td class="amount" style="color:{sav_color}">{_nis(total_savings)} ש"ח</td>
        <td>{sum(len(r.transactions) for r in reports)}</td>
    </tr>"""

    return f'''
    <section class="card">
        <h2>סיכום כל התקופות</h2>
        <table>
            <thead>
                <tr>
                    <th>תקופה</th>
                    <th>הכנסה</th>
                    <th>הוצאות</th>
                    <th>חיסכון / גירעון</th>
                    <th>עסקאות</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </section>'''


def _render_period_section(
    report: ExpenseReport,
    budgets: dict[str, float],
    insights: dict[str, str],
    charts: dict[str, str],
    income: float = 0,
) -> str:
    breakdown = report.by_category()

    budget_rows = []
    for cat, spent in breakdown.items():
        budget = budgets.get(cat)
        if budget:
            budget_rows.append(f"""
            <tr>
                <td>{cat}</td>
                <td class="amount">{_nis(spent)} ש"ח</td>
                <td class="amount">{_nis(budget)} ש"ח</td>
                <td>{_status_badge(spent, budget)}{_progress_bar(spent, budget)}</td>
            </tr>""")
        else:
            budget_rows.append(f"""
            <tr>
                <td>{cat}</td>
                <td class="amount">{_nis(spent)} ש"ח</td>
                <td>—</td>
                <td>—</td>
            </tr>""")

    budget_rows.append(f"""
    <tr class="total-row">
        <td>סה"כ</td>
        <td class="amount">{_nis(report.total)} ש"ח</td>
        <td></td>
        <td></td>
    </tr>""")

    pie_b64 = charts.get(f"pie_{report.label}", "")
    budget_b64 = charts.get(f"budget_{report.label}", "")
    insight_text = insights.get(report.label, "")

    charts_html = ""
    if pie_b64:
        charts_html += f'<img src="data:image/png;base64,{pie_b64}" alt="pie chart" class="chart-img">'
    if budget_b64:
        charts_html += f'<img src="data:image/png;base64,{budget_b64}" alt="budget chart" class="chart-img">'

    insights_html = ""
    if insight_text:
        insights_html = f'''
        <h3>תובנות AI</h3>
        <div class="insights-box">{insight_text}</div>'''

    date_range_html = ""
    if report.transactions:
        date_range_html = f'<div class="date-range">טווח תאריכים: {report.date_range_str}</div>'

    income_html = ""
    if income > 0:
        savings = income - report.total
        sav_color = "#155724" if savings >= 0 else "#721c24"
        sav_label = "חיסכון" if savings >= 0 else "גירעון"
        income_html = f'''
        <div style="display:flex;gap:24px;margin:12px 0 20px;flex-wrap:wrap">
            <div><strong>הכנסה:</strong> {_nis(income)} ש"ח</div>
            <div><strong>הוצאות:</strong> {_nis(report.total)} ש"ח</div>
            <div style="color:{sav_color}"><strong>{sav_label}:</strong> {_nis(abs(savings))} ש"ח</div>
        </div>'''

    return f'''
    <section class="card period-section">
        <h2>{report.label}</h2>
        {date_range_html}
        {income_html}

        <h3>סיכום לפי קטגוריה</h3>
        <table>
            <thead>
                <tr>
                    <th>קטגוריה</th>
                    <th>הוצאה</th>
                    <th>תקציב</th>
                    <th>סטטוס</th>
                </tr>
            </thead>
            <tbody>
                {"".join(budget_rows)}
            </tbody>
        </table>

        {charts_html}
        {insights_html}
    </section>'''


def _render_all_transactions(reports: list[ExpenseReport]) -> str:
    all_tx: list[Transaction] = []
    for r in reports:
        all_tx.extend(sorted(r.transactions, key=lambda t: t.date, reverse=True))

    if not all_tx:
        return ""

    rows = []
    for tx in all_tx:
        cat_tag = f'<span class="category-tag">{tx.category or "—"}</span>'
        rows.append(f"""
        <tr>
            <td>{tx.date.strftime("%d/%m/%Y")}</td>
            <td>{tx.description}</td>
            <td class="amount">{_nis(tx.amount)} ש"ח</td>
            <td>{cat_tag}</td>
            <td>{tx.source_bank}</td>
        </tr>""")

    return f'''
    <section class="card">
        <h2>פירוט כל העסקאות ({len(all_tx)})</h2>
        <table class="tx-table">
            <thead>
                <tr>
                    <th>תאריך</th>
                    <th>תיאור</th>
                    <th>סכום</th>
                    <th>קטגוריה</th>
                    <th>מקור</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </section>'''
