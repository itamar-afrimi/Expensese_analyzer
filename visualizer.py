from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from bidi.algorithm import get_display
from rich.console import Console

from models import ExpenseReport

console = Console()
OUTPUT_DIR = Path(__file__).parent / "output"


def _hebrew(text: str) -> str:
    """Reorder Hebrew text for matplotlib (LTR renderer)."""
    return get_display(text)


def _safe_filename(label: str) -> str:
    """Sanitize a label for use in filenames."""
    return label.replace("/", "-").replace("\\", "-").replace(" ", "_")


def _setup_hebrew_font() -> None:
    """Use a font that supports both Hebrew and Latin on macOS."""
    import matplotlib.font_manager as fm
    hebrew_fonts = ["Arial", "Lucida Grande", "Arial Hebrew", "Tahoma", "David", "Miriam"]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in hebrew_fonts:
        if font in available:
            plt.rcParams["font.family"] = font
            return
    plt.rcParams["font.family"] = "sans-serif"


_setup_hebrew_font()


def ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _fig_to_base64(fig) -> str:
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def pie_chart(report: ExpenseReport, output_path: Optional[Path] = None) -> tuple[Path, str]:
    """Generate a pie chart. Returns (file_path, base64_png)."""
    out = output_path or ensure_output_dir() / f"pie_{_safe_filename(report.label)}.png"
    breakdown = report.by_category()

    if not breakdown:
        return out, ""

    labels = [_hebrew(cat) for cat in breakdown.keys()]
    sizes = list(breakdown.values())
    colors = plt.cm.Set3.colors[:len(labels)]

    fig, ax = plt.subplots(figsize=(10, 8))
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        colors=colors,
        textprops={"fontsize": 11},
    )
    for autotext in autotexts:
        autotext.set_fontsize(9)
        autotext.set_color("white")
        autotext.set_fontweight("bold")
    ax.set_title(_hebrew(f"פילוח הוצאות — {report.label}"), fontsize=16, fontweight="bold", pad=20)
    plt.tight_layout()
    b64 = _fig_to_base64(fig)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out, b64


def budget_bar_chart(
    report: ExpenseReport, budgets: dict[str, float], output_path: Optional[Path] = None
) -> tuple[Path, str]:
    """Generate a budget vs spending bar chart. Returns (file_path, base64_png)."""
    out = output_path or ensure_output_dir() / f"budget_{_safe_filename(report.label)}.png"
    breakdown = report.by_category()

    categories = list(budgets.keys())
    spent_vals = [breakdown.get(cat, 0) for cat in categories]
    budget_vals = [budgets[cat] for cat in categories]
    hebrew_labels = [_hebrew(cat) for cat in categories]

    fig, ax = plt.subplots(figsize=(14, 7))
    x = range(len(categories))
    bar_width = 0.35

    ax.bar(
        [i - bar_width / 2 for i in x], spent_vals, bar_width,
        label=_hebrew("הוצאה בפועל"), color="#e74c3c",
    )
    ax.bar(
        [i + bar_width / 2 for i in x], budget_vals, bar_width,
        label=_hebrew("תקציב"), color="#2ecc71", alpha=0.7,
    )

    ax.set_xlabel(_hebrew("קטגוריה"), fontsize=12)
    ax.set_ylabel(_hebrew('סכום (ש"ח)'), fontsize=12)
    ax.set_title(
        _hebrew(f"הוצאה מול תקציב — {report.label}"), fontsize=16, fontweight="bold", pad=20,
    )
    ax.set_xticks(list(x))
    ax.set_xticklabels(hebrew_labels, rotation=45, ha="right", fontsize=9)
    ax.legend(fontsize=11, loc="upper left")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    b64 = _fig_to_base64(fig)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out, b64


def monthly_comparison_chart(
    reports: list[ExpenseReport], output_path: Optional[Path] = None
) -> tuple[Path, str]:
    """Generate a comparison bar chart across multiple billing periods."""
    out = output_path or ensure_output_dir() / "monthly_comparison.png"

    if len(reports) < 2:
        return out, ""

    labels = [r.label for r in reports]
    totals = [r.total for r in reports]

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["#3498db" if t <= min(totals) * 1.2 else "#e74c3c" for t in totals]
    bars = ax.bar(labels, totals, color=colors, edgecolor="white", linewidth=0.5)

    for bar, total in zip(bars, totals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(totals) * 0.01,
            f"{total:,.0f}",
            ha="center", va="bottom", fontsize=11, fontweight="bold",
        )

    ax.set_xlabel(_hebrew("תקופה"), fontsize=12)
    ax.set_ylabel(_hebrew('סכום (ש"ח)'), fontsize=12)
    ax.set_title(_hebrew("השוואת הוצאות"), fontsize=16, fontweight="bold", pad=20)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    b64 = _fig_to_base64(fig)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out, b64
