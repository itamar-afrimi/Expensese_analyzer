#!/usr/bin/env python3
"""Streamlit GUI for the AI-Powered Expenses Analyzer."""
from __future__ import annotations

import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml

from models import Transaction, ExpenseReport
from parsers import detect_and_parse
from store import CategoryStore

CONFIG_PATH = Path(__file__).parent / "config.yaml"
OUTPUT_DIR = Path(__file__).parent / "output"


def check_password() -> bool:
    """Return True if the user is authenticated or no password is configured."""
    try:
        required_pw = st.secrets["app"]["password"]
    except (KeyError, FileNotFoundError):
        return True

    if st.session_state.get("authenticated"):
        return True

    st.markdown("""
    <style>
        .login-box { max-width: 400px; margin: 120px auto; direction: rtl; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

    with st.container():
        st.title("🔒 מנתח הוצאות AI")
        st.caption("הזן סיסמה כדי להיכנס")
        pwd = st.text_input("סיסמה", type="password", key="login_pw")
        if pwd:
            if pwd == required_pw:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("סיסמה שגויה")
    return False


def get_api_key(config: dict) -> Optional[str]:
    """Resolve OpenAI API key from env, st.secrets, or config.yaml."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        try:
            key = st.secrets["openai"]["api_key"]
        except (KeyError, FileNotFoundError):
            pass
    if not key:
        key = config.get("openai", {}).get("api_key")
    return key or None


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def inject_fixed_expenses(
    grouped: dict[str, list[Transaction]], fixed_expenses: list[dict]
) -> None:
    if not fixed_expenses:
        return
    for label, txs in grouped.items():
        mm = re.search(r"(\d{2})/(\d{4})", label)
        tx_date = date(int(mm.group(2)), int(mm.group(1)), 1) if mm else (txs[0].date if txs else date.today())
        for entry in fixed_expenses:
            txs.append(Transaction(
                date=tx_date,
                description=entry["description"],
                amount=float(entry["amount"]),
                category=entry.get("category"),
                source_bank="הוצאה קבועה",
                billing_label=label,
            ))


def parse_uploaded_files(uploaded_files) -> dict[str, list[Transaction]]:
    grouped: dict[str, list[Transaction]] = {}
    for uf in uploaded_files:
        suffix = Path(uf.name).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(uf.getbuffer())
            tmp_path = Path(tmp.name)
        try:
            txs = detect_and_parse(tmp_path)
            label = txs[0].billing_label if txs and txs[0].billing_label else Path(uf.name).stem
            grouped.setdefault(label, []).extend(txs)
        except Exception as e:
            st.error(f"שגיאה בקובץ {uf.name}: {e}")
        finally:
            tmp_path.unlink(missing_ok=True)
    return grouped


def categorize_transactions(
    transactions: list[Transaction], config: dict, force: bool = False
) -> list[Transaction]:
    api_key = get_api_key(config)
    if not api_key:
        st.error("לא נמצא מפתח OpenAI API. הגדר ב-secrets או כמשתנה סביבה.")
        return transactions

    from agent.categorizer import Categorizer
    store = CategoryStore()
    categorizer = Categorizer(
        categories=config.get("categories", []),
        model=config.get("openai", {}).get("categorization_model", "gpt-4o-mini"),
        api_key=api_key,
        store=store,
    )
    return categorizer.categorize(transactions, force=force)


def generate_insights(report: ExpenseReport, config: dict) -> str:
    api_key = get_api_key(config)
    if not api_key:
        return "חסר מפתח API — לא ניתן לייצר תובנות"
    from agent.insights import InsightsGenerator
    gen = InsightsGenerator(
        budgets=config.get("budgets", {}),
        model=config.get("openai", {}).get("chat_model", "gpt-4o"),
        api_key=api_key,
    )
    return gen.generate(report)


def scan_receipt(photo_bytes: bytes, filename: str, config: dict) -> Optional[dict]:
    api_key = get_api_key(config)
    if not api_key:
        st.error("חסר מפתח API")
        return None
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(photo_bytes)
        tmp_path = Path(tmp.name)
    try:
        from agent.receipt_scanner import ReceiptScanner
        scanner = ReceiptScanner(
            categories=config.get("categories", []),
            model=config.get("openai", {}).get("chat_model", "gpt-4o"),
            api_key=api_key,
        )
        receipt = scanner.scan(tmp_path)
        return receipt.to_dict()
    except Exception as e:
        st.error(f"שגיאה בסריקת קבלה: {e}")
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


# ───────────────────────── Charts (Plotly) ─────────────────────────

def make_pie_chart(report: ExpenseReport) -> go.Figure:
    breakdown = report.by_category()
    fig = px.pie(
        names=list(breakdown.keys()),
        values=list(breakdown.values()),
        title=f"פילוח הוצאות — {report.label}",
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Set3,
    )
    fig.update_traces(textinfo="percent+label", textfont_size=13)
    fig.update_layout(
        font=dict(family="Arial, sans-serif", size=14),
        legend=dict(font=dict(size=12)),
        margin=dict(t=60, b=20, l=20, r=20),
    )
    return fig


def make_budget_chart(report: ExpenseReport, budgets: dict[str, float]) -> go.Figure:
    breakdown = report.by_category()
    categories = list(budgets.keys())
    spent = [breakdown.get(c, 0) for c in categories]
    budget_vals = [budgets[c] for c in categories]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="הוצאה בפועל", x=categories, y=spent,
        marker_color="#e74c3c", text=[f"{v:,.0f}" for v in spent], textposition="auto",
    ))
    fig.add_trace(go.Bar(
        name="תקציב", x=categories, y=budget_vals,
        marker_color="#2ecc71", opacity=0.7,
        text=[f"{v:,.0f}" for v in budget_vals], textposition="auto",
    ))
    fig.update_layout(
        title=f"הוצאה מול תקציב — {report.label}",
        barmode="group",
        font=dict(family="Arial, sans-serif", size=13),
        xaxis_tickangle=-45,
        margin=dict(t=60, b=100, l=40, r=20),
        yaxis_title='סכום (ש"ח)',
    )
    return fig


def make_income_expense_chart(
    reports: list[ExpenseReport], income_map: dict[str, float], default_income: float
) -> go.Figure:
    labels = [r.label for r in reports]
    expenses = [r.total for r in reports]
    incomes = [income_map.get(r.label, default_income) for r in reports]
    savings = [i - e for i, e in zip(incomes, expenses)]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="הכנסה", x=labels, y=incomes, marker_color="#2ecc71",
                         text=[f"{v:,.0f}" for v in incomes], textposition="auto"))
    fig.add_trace(go.Bar(name="הוצאות", x=labels, y=expenses, marker_color="#e74c3c",
                         text=[f"{v:,.0f}" for v in expenses], textposition="auto"))
    fig.add_trace(go.Scatter(name="חיסכון", x=labels, y=savings, mode="lines+markers+text",
                             line=dict(color="#3498db", width=3), marker=dict(size=10),
                             text=[f"{v:,.0f}" for v in savings], textposition="top center"))
    fig.update_layout(
        title="הכנסה מול הוצאות",
        barmode="group",
        font=dict(family="Arial, sans-serif", size=13),
        margin=dict(t=60, b=40, l=40, r=20),
        yaxis_title='סכום (ש"ח)',
    )
    return fig


def make_monthly_comparison(reports: list[ExpenseReport]) -> go.Figure:
    if len(reports) < 2:
        return None
    labels = [r.label for r in reports]
    totals = [r.total for r in reports]
    colors = ["#3498db" if t <= min(totals) * 1.2 else "#e74c3c" for t in totals]
    fig = go.Figure(go.Bar(
        x=labels, y=totals, marker_color=colors,
        text=[f"{v:,.0f}" for v in totals], textposition="auto",
    ))
    fig.update_layout(
        title="השוואת הוצאות לפי תקופה",
        font=dict(family="Arial, sans-serif", size=13),
        margin=dict(t=60, b=40, l=40, r=20),
        yaxis_title='סכום (ש"ח)',
    )
    return fig


# ───────────────────────── HTML Export ─────────────────────────

def generate_export_html(
    reports: list[ExpenseReport], budgets: dict[str, float],
    insights: dict[str, str], income_map: dict[str, float], default_income: float,
) -> str:
    from report_generator import generate_html_report
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import visualizer
    chart_data: dict[str, str] = {}
    for report in reports:
        _, pie_b64 = visualizer.pie_chart(report)
        chart_data[f"pie_{report.label}"] = pie_b64
        _, budget_b64 = visualizer.budget_bar_chart(report, budgets)
        chart_data[f"budget_{report.label}"] = budget_b64

    if len(reports) >= 2:
        _, comp_b64 = visualizer.monthly_comparison_chart(reports)
        if comp_b64:
            chart_data["comparison"] = comp_b64

    path = generate_html_report(
        reports=reports, budgets=budgets, insights=insights,
        charts=chart_data, open_in_browser=False,
        income_map=income_map, default_income=default_income,
    )
    return path.read_text(encoding="utf-8")


# ───────────────────────── Streamlit App ─────────────────────────

def main():
    st.set_page_config(
        page_title="מנתח הוצאות AI",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if not check_password():
        st.stop()

    st.markdown("""
    <style>
        [data-testid="stSidebar"] { direction: rtl; }
        .main .block-container { direction: rtl; text-align: right; }
        h1, h2, h3, p, span { direction: rtl; text-align: right; }
        .stMetric label, .stMetric [data-testid="stMetricValue"] { direction: rtl; }

        .rtl-table {
            width: 100%;
            border-collapse: collapse;
            direction: rtl;
            text-align: right;
            font-size: 0.95em;
            margin: 12px 0;
        }
        .rtl-table th {
            background: #1a1a2e;
            color: white;
            padding: 12px 16px;
            text-align: right;
            font-weight: 600;
            white-space: nowrap;
        }
        .rtl-table td {
            padding: 10px 16px;
            border-bottom: 1px solid #e8e8e8;
            white-space: nowrap;
        }
        .rtl-table tr:hover td { background: #f5f7fa; }
        .rtl-table tr:nth-child(even) td { background: #fafbfc; }
        .rtl-table .amount { font-weight: 600; font-variant-numeric: tabular-nums; direction: ltr; text-align: right; }
        .badge-ok { background: #d4edda; color: #155724; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; font-weight: 600; }
        .badge-over { background: #f8d7da; color: #721c24; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; font-weight: 600; }
        .cat-tag { background: #e8eaf6; color: #283593; padding: 3px 10px; border-radius: 12px; font-size: 0.85em; }
        .source-tag { background: #f0f0f0; color: #555; padding: 3px 8px; border-radius: 8px; font-size: 0.82em; }
        .total-row td { font-weight: bold; border-top: 2px solid #1a1a2e; background: #f0f2f5 !important; }
        .progress-bg { height: 8px; background: #e9ecef; border-radius: 4px; overflow: hidden; margin-top: 4px; }
        .progress-fill { height: 100%; border-radius: 4px; }
    </style>
    """, unsafe_allow_html=True)

    config = load_config()

    # ── Sidebar ──
    with st.sidebar:
        st.title("⚙️ הגדרות")

        st.header("📁 העלאת קבצים")
        uploaded_files = st.file_uploader(
            "גרור קבצי Excel/CSV/PDF של חיובי אשראי",
            type=["csv", "xls", "xlsx", "xlsm", "pdf"],
            accept_multiple_files=True,
            key="expense_files",
        )

        st.divider()

        st.header("💰 הכנסה חודשית")
        default_income = st.number_input(
            "הכנסה חודשית ברירת מחדל (₪)",
            value=int(config.get("income", {}).get("default_monthly", 25000)),
            step=500,
            min_value=0,
            key="default_income",
        )

        st.divider()

        st.header("🏠 הוצאות קבועות")
        fixed_expenses = config.get("fixed_expenses", [])
        edited_fixed = []
        for i, fe in enumerate(fixed_expenses):
            cols = st.columns([3, 2, 2])
            desc = cols[0].text_input("תיאור", value=fe["description"], key=f"fe_desc_{i}", label_visibility="collapsed")
            amt = cols[1].number_input("סכום", value=int(fe["amount"]), step=100, key=f"fe_amt_{i}", label_visibility="collapsed")
            cat = cols[2].selectbox("קטגוריה", config.get("categories", []),
                                   index=config.get("categories", []).index(fe["category"]) if fe.get("category") in config.get("categories", []) else 0,
                                   key=f"fe_cat_{i}", label_visibility="collapsed")
            edited_fixed.append({"description": desc, "amount": amt, "category": cat})

        if st.button("➕ הוסף הוצאה קבועה", key="add_fixed"):
            edited_fixed.append({"description": "חדש", "amount": 0, "category": config.get("categories", ["אחר"])[0]})

        st.divider()

        st.header("📋 תקציבים")
        budgets = config.get("budgets", {})
        edited_budgets = {}
        for cat, limit in budgets.items():
            edited_budgets[cat] = st.number_input(
                cat, value=int(limit), step=100, min_value=0, key=f"budget_{cat}",
            )

        st.divider()

        if st.button("💾 שמור הגדרות", type="primary", use_container_width=True):
            config["income"]["default_monthly"] = default_income
            config["fixed_expenses"] = edited_fixed
            config["budgets"] = edited_budgets
            save_config(config)
            st.success("ההגדרות נשמרו!")
            st.rerun()

        st.divider()

        st.header("📷 סריקת קבלה")
        receipt_photo = st.file_uploader(
            "העלה תמונת קבלה",
            type=["jpg", "jpeg", "png", "webp", "heic"],
            key="receipt_photo",
        )
        if receipt_photo and st.button("🔍 סרוק קבלה"):
            with st.spinner("סורק קבלה עם AI Vision..."):
                result = scan_receipt(receipt_photo.getvalue(), receipt_photo.name, config)
                if result:
                    st.session_state["scanned_receipt"] = result

    # ── Main Area ──
    st.title("📊 מנתח הוצאות AI")

    if "scanned_receipt" in st.session_state:
        r = st.session_state["scanned_receipt"]
        with st.expander("📷 קבלה שנסרקה", expanded=True):
            c1, c2, c3 = st.columns(3)
            c1.metric("חנות", r["store_name"])
            c2.metric("סכום", f'₪{r["total"]:,.0f}')
            c3.metric("קטגוריה", r.get("suggested_category", "—"))

    if not uploaded_files:
        st.info("👈 העלה קבצי Excel/CSV בסרגל הצד כדי להתחיל")
        st.stop()

    # Parse files
    with st.spinner("מנתח קבצים..."):
        grouped = parse_uploaded_files(uploaded_files)

    if not grouped:
        st.error("לא נמצאו עסקאות בקבצים")
        st.stop()

    inject_fixed_expenses(grouped, edited_fixed)

    all_tx = [tx for txs in grouped.values() for tx in txs]

    # Per-period income
    st.subheader("💰 הכנסה לפי תקופה")
    income_map: dict[str, float] = {}
    income_cols = st.columns(min(len(grouped), 4))
    for idx, label in enumerate(sorted(grouped.keys())):
        with income_cols[idx % len(income_cols)]:
            saved = config.get("income", {}).get("per_month", {}).get(label, default_income)
            income_map[label] = st.number_input(
                f"הכנסה — {label}", value=int(saved), step=500, min_value=0, key=f"income_{label}",
            )

    st.divider()

    # Categorize
    recategorize = st.checkbox("סיווג מחדש (התעלם ממטמון)", value=False)
    if st.button("🚀 נתח הוצאות", type="primary", use_container_width=True):
        with st.spinner("מסווג עסקאות עם AI..."):
            all_tx = categorize_transactions(all_tx, config, force=recategorize)
        st.session_state["categorized"] = True
        st.session_state["all_tx"] = all_tx
        st.session_state["grouped"] = grouped
        st.session_state["income_map"] = income_map

    if not st.session_state.get("categorized"):
        st.info("לחץ על 'נתח הוצאות' כדי להתחיל בסיווג AI")
        st.stop()

    grouped = st.session_state["grouped"]
    all_tx = st.session_state["all_tx"]
    income_map = st.session_state.get("income_map", income_map)

    reports = [ExpenseReport(label=label, transactions=txs) for label, txs in grouped.items()]
    reports.sort(key=lambda r: r.label)

    # ── Summary Cards ──
    total_expenses = sum(r.total for r in reports)
    total_income = sum(income_map.get(r.label, default_income) for r in reports)
    total_savings = total_income - total_expenses
    savings_pct = (total_savings / total_income * 100) if total_income else 0

    st.subheader("📈 סיכום כללי")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("סה\"כ הוצאות", f"₪{total_expenses:,.0f}")
    m2.metric("סה\"כ הכנסה", f"₪{total_income:,.0f}")
    m3.metric("חיסכון / גירעון", f"₪{total_savings:,.0f}",
              delta=f"{savings_pct:+.1f}%")
    m4.metric("עסקאות", f"{len(all_tx)}")

    st.divider()

    # ── Income vs Expenses ──
    if len(reports) >= 1:
        fig_income = make_income_expense_chart(reports, income_map, default_income)
        st.plotly_chart(fig_income, use_container_width=True)

    # ── Monthly Comparison ──
    if len(reports) >= 2:
        fig_compare = make_monthly_comparison(reports)
        if fig_compare:
            st.plotly_chart(fig_compare, use_container_width=True)

    st.divider()

    # ── Per-Period Analysis ──
    for report in reports:
        income = income_map.get(report.label, default_income)
        surplus = income - report.total
        surplus_class = "savings-positive" if surplus >= 0 else "savings-negative"

        st.subheader(f"📅 {report.label}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("הוצאות", f"₪{report.total:,.0f}")
        c2.metric("הכנסה", f"₪{income:,.0f}")
        c3.metric("חיסכון", f"₪{surplus:,.0f}", delta=f"{surplus / income * 100:+.1f}%" if income else "")
        c4.metric("עסקאות", str(len(report.transactions)))

        tab_charts, tab_budget, tab_transactions, tab_insights = st.tabs(
            ["📊 תרשימים", "💳 תקציב", "📋 עסקאות", "🧠 תובנות AI"]
        )

        with tab_charts:
            col_pie, col_bar = st.columns(2)
            with col_pie:
                st.plotly_chart(make_pie_chart(report), use_container_width=True)
            with col_bar:
                st.plotly_chart(make_budget_chart(report, edited_budgets), use_container_width=True)

        with tab_budget:
            breakdown = report.by_category()
            budget_rows_html = ""
            total_spent_all = 0
            total_budget_all = 0
            for cat, budget_limit in edited_budgets.items():
                spent = breakdown.get(cat, 0)
                total_spent_all += spent
                total_budget_all += budget_limit
                diff = spent - budget_limit
                pct = (spent / budget_limit * 100) if budget_limit else 0
                bar_pct = min(pct, 100)
                bar_color = "#2ecc71" if diff <= 0 else "#e74c3c"
                badge = f'<span class="badge-ok">בתקציב ({pct:.0f}%)</span>' if diff <= 0 else f'<span class="badge-over">חריגה של ₪{diff:,.0f}</span>'
                progress = f'<div class="progress-bg"><div class="progress-fill" style="width:{bar_pct}%;background:{bar_color}"></div></div>'
                budget_rows_html += f"""<tr>
                    <td>{cat}</td>
                    <td class="amount">₪{spent:,.0f}</td>
                    <td class="amount">₪{budget_limit:,.0f}</td>
                    <td>{badge}{progress}</td>
                </tr>"""
            budget_rows_html += f"""<tr class="total-row">
                <td>סה"כ</td>
                <td class="amount">₪{total_spent_all:,.0f}</td>
                <td class="amount">₪{total_budget_all:,.0f}</td>
                <td></td>
            </tr>"""
            st.markdown(f"""<table class="rtl-table">
                <thead><tr><th>קטגוריה</th><th>הוצאה</th><th>תקציב</th><th>סטטוס</th></tr></thead>
                <tbody>{budget_rows_html}</tbody>
            </table>""", unsafe_allow_html=True)

        with tab_transactions:
            all_cats = sorted(set(tx.category or "אחר" for tx in report.transactions))
            view_mode = st.radio(
                "תצוגה", ["הכל", "לפי קטגוריה"],
                horizontal=True, key=f"view_mode_{report.label}",
            )

            if view_mode == "הכל":
                selected_cats = st.multiselect(
                    "סינון לפי קטגוריה",
                    options=all_cats, default=all_cats,
                    key=f"cat_filter_{report.label}",
                )
                filtered = [tx for tx in report.transactions if (tx.category or "אחר") in selected_cats]
                filtered.sort(key=lambda t: t.date, reverse=True)
                total_filtered = sum(tx.amount for tx in filtered)
                st.caption(f"{len(filtered)} עסקאות | סה\"כ ₪{total_filtered:,.0f}")
                tx_rows_html = ""
                for tx in filtered:
                    cat_tag = f'<span class="cat-tag">{tx.category or "—"}</span>'
                    src_tag = f'<span class="source-tag">{tx.source_bank}</span>'
                    tx_rows_html += f"""<tr>
                        <td>{tx.date.strftime("%d/%m/%Y")}</td>
                        <td>{tx.description}</td>
                        <td class="amount">₪{tx.amount:,.0f}</td>
                        <td>{cat_tag}</td>
                        <td>{src_tag}</td>
                    </tr>"""
                st.markdown(f"""<table class="rtl-table">
                    <thead><tr><th>תאריך</th><th>תיאור</th><th>סכום</th><th>קטגוריה</th><th>מקור</th></tr></thead>
                    <tbody>{tx_rows_html}</tbody>
                </table>""", unsafe_allow_html=True)

            else:
                for cat in all_cats:
                    cat_txs = sorted(
                        [tx for tx in report.transactions if (tx.category or "אחר") == cat],
                        key=lambda t: t.date, reverse=True,
                    )
                    cat_total = sum(tx.amount for tx in cat_txs)
                    with st.expander(f"{cat}  —  {len(cat_txs)} עסקאות  |  ₪{cat_total:,.0f}"):
                        rows_html = ""
                        for tx in cat_txs:
                            src_tag = f'<span class="source-tag">{tx.source_bank}</span>'
                            rows_html += f"""<tr>
                                <td>{tx.date.strftime("%d/%m/%Y")}</td>
                                <td>{tx.description}</td>
                                <td class="amount">₪{tx.amount:,.0f}</td>
                                <td>{src_tag}</td>
                            </tr>"""
                        st.markdown(f"""<table class="rtl-table">
                            <thead><tr><th>תאריך</th><th>תיאור</th><th>סכום</th><th>מקור</th></tr></thead>
                            <tbody>{rows_html}</tbody>
                        </table>""", unsafe_allow_html=True)

        with tab_insights:
            if st.button(f"🧠 צור תובנות AI עבור {report.label}", key=f"insights_{report.label}"):
                with st.spinner("מייצר תובנות..."):
                    insight = generate_insights(report, config)
                    st.session_state[f"insight_{report.label}"] = insight
            if f"insight_{report.label}" in st.session_state:
                st.markdown(st.session_state[f"insight_{report.label}"])

        st.divider()

    # ── Export ──
    st.subheader("📄 ייצוא דוח")
    col_export1, col_export2 = st.columns(2)
    with col_export1:
        if st.button("📄 ייצר דוח HTML", use_container_width=True):
            with st.spinner("מייצר דוח..."):
                insights_data = {
                    label: st.session_state.get(f"insight_{label}", "")
                    for label in [r.label for r in reports]
                }
                html = generate_export_html(
                    reports, edited_budgets, insights_data, income_map, default_income,
                )
                st.session_state["export_html"] = html
                st.success("הדוח מוכן!")

    if "export_html" in st.session_state:
        with col_export2:
            st.download_button(
                "⬇️ הורד דוח HTML",
                data=st.session_state["export_html"],
                file_name="expense_report.html",
                mime="text/html",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
