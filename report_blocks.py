"""
Rapor sayfalarında ortak kullanılan UI bileşenleri (PDF tarzı).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

GLOBAL_CSS = """
<style>
.stApp { background: #f4f6f9; }

.report-header {
    background: linear-gradient(135deg, #16213d 0%, #2a3f6d 50%, #3b5998 100%);
    border-radius: 14px;
    padding: 32px 40px;
    color: white;
    margin: 4px 0 22px 0;
    box-shadow: 0 6px 20px rgba(22,33,61,.18);
}
.report-header h1 { margin: 0 0 4px 0; font-weight: 700; font-size: 26px; line-height: 1.2; }
.report-header p { margin: 0; opacity: .85; font-size: 14px; }
.report-header .badges { margin-top: 14px; }
.report-header .badge {
    display: inline-block;
    background: rgba(255,255,255,.16);
    padding: 5px 14px; border-radius: 20px;
    font-size: 12px; margin-right: 8px;
}

.metric-card {
    background: #fff;
    border-left: 4px solid #2a3f6d;
    padding: 18px 20px;
    border-radius: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,.05);
    height: 100%;
    margin-bottom: 12px;
}
.metric-card .lbl {
    font-size: 11px; letter-spacing: 1.2px; color: #889;
    text-transform: uppercase; font-weight: 600;
}
.metric-card .val {
    font-size: 28px; font-weight: 700; color: #16213d;
    margin-top: 6px; line-height: 1.1;
}
.metric-card.alt { border-color: #7c5fb8; }
.metric-card.alt .val { color: #6b4ba0; }
.metric-card.win { border-color: #2ecc71; }
.metric-card.win .val { color: #1f8e4d; }
.metric-card.warn { border-color: #f39c12; }
.metric-card.warn .val { color: #b97506; }
.metric-card.danger { border-color: #e74c3c; }
.metric-card.danger .val { color: #c0392b; }

.section-title {
    border-bottom: 2px solid #16213d;
    padding-bottom: 8px;
    margin: 26px 0 14px 0;
    color: #16213d;
    font-size: 18px;
    font-weight: 700;
}

.report-card {
    background: #fff;
    border-radius: 12px;
    padding: 22px 22px 18px;
    box-shadow: 0 2px 8px rgba(0,0,0,.06);
    border-top: 4px solid var(--accent, #3b5998);
    text-decoration: none;
    color: #16213d;
    display: block;
    transition: transform .15s, box-shadow .15s;
    height: 100%;
}
.report-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 20px rgba(0,0,0,.10);
    text-decoration: none;
    color: #16213d;
}
.report-card .icon { font-size: 32px; }
.report-card .title { font-size: 16px; font-weight: 700; margin-top: 10px; }
.report-card .desc { font-size: 12px; color: #667; margin-top: 6px; line-height: 1.45; }

.fab-ai {
    position: fixed; bottom: 26px; right: 26px;
    background: linear-gradient(135deg, #FF4B4B 0%, #c93636 100%);
    color: white !important;
    padding: 14px 22px; border-radius: 50px;
    text-decoration: none !important;
    font-size: 15px; font-weight: 600;
    box-shadow: 0 6px 22px rgba(255,75,75,.42);
    z-index: 9999;
    display: inline-flex; align-items: center; gap: 8px;
    transition: transform .15s, box-shadow .15s;
}
.fab-ai:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 28px rgba(255,75,75,.55);
    color: white !important;
}
.fab-ai .pulse { font-size: 18px; }

.cat-badge {
    display: inline-block; padding: 1px 8px; border-radius: 10px;
    font-size: 10px; font-weight: 700; letter-spacing: .3px; margin-left: 6px;
}
.cat-DEAL    { background: #dcfce7; color: #15803d; }
.cat-POZITIF { background: #ccfbf1; color: #0f766e; }
.cat-TEKLIF  { background: #dbeafe; color: #1e3a8a; }
.cat-KAYIP   { background: #fee2e2; color: #b91c1c; }
</style>
"""


def inject_css() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def render_header(title: str, subtitle: str, badges: list[str] | None = None) -> None:
    badge_html = ""
    if badges:
        badge_html = '<div class="badges">' + "".join(
            f'<span class="badge">{b}</span>' for b in badges
        ) + "</div>"
    st.markdown(
        f'<div class="report-header"><h1>{title}</h1><p>{subtitle}</p>{badge_html}</div>',
        unsafe_allow_html=True,
    )


def metric_tile(label: str, value: str, kind: str = "default") -> str:
    cls = "metric-card" if kind == "default" else f"metric-card {kind}"
    return f'<div class="{cls}"><div class="lbl">{label}</div><div class="val">{value}</div></div>'


def render_metric_row(items: list[tuple]) -> None:
    """items: [(label, value), (label, value, kind), ...]"""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        if len(item) == 2:
            label, value = item
            kind = "default"
        else:
            label, value, kind = item[0], item[1], item[2]
        col.markdown(metric_tile(label, str(value), kind), unsafe_allow_html=True)


def section_title(text: str) -> None:
    st.markdown(f'<div class="section-title">{text}</div>', unsafe_allow_html=True)


def render_distribution_table(
    df: pd.DataFrame,
    label_col: str,
    *,
    show_columns: list[str] | None = None,
    height: int = 420,
    money_col: str | None = "Gelir",
    selectable: bool = True,
    key: str | None = None,
) -> int | None:
    """Lead / Dağılım / Teklif / Pozitif / Deal / Gelir / Teklif % tablosu.

    selectable=True iken tek satır seçilebilir; tıklanan satırın index'ini
    döndürür (yoksa None).
    """
    if df.empty:
        st.info("Bu kapsamda veri yok.")
        return None
    show_columns = show_columns or [
        label_col, "Lead", "Dağılım", "Teklif", "Pozitif", "Deal", "Gelir", "Teklif %"
    ]
    show_columns = [c for c in show_columns if c in df.columns]
    cfg: dict = {
        "Dağılım": st.column_config.ProgressColumn(
            "Dağılım", format="%.1f%%", min_value=0.0, max_value=100.0,
        ),
        "Teklif %": st.column_config.NumberColumn("Teklif %", format="%.1f%%"),
    }
    if money_col and money_col in df.columns:
        cfg[money_col] = st.column_config.NumberColumn(money_col, format="$%d")

    kwargs: dict = dict(
        column_config=cfg, use_container_width=True, height=height, hide_index=True,
    )
    if selectable:
        kwargs.update(on_select="rerun", selection_mode="single-row")
    if key:
        kwargs["key"] = key

    event = st.dataframe(df[show_columns], **kwargs)
    if not selectable:
        return None
    try:
        sel = event.selection if hasattr(event, "selection") else (event or {}).get("selection", {})
        rows = sel.rows if hasattr(sel, "rows") else (sel or {}).get("rows", [])
    except Exception:
        rows = []
    return rows[0] if rows else None


def render_simple_table(
    df: pd.DataFrame,
    *,
    column_config: dict | None = None,
    height: int = 420,
    selectable: bool = False,
    key: str | None = None,
) -> int | None:
    """Generik tıklanabilir tablo (custom column_config destekli)."""
    if df.empty:
        st.info("Bu kapsamda veri yok.")
        return None
    kwargs: dict = dict(
        column_config=column_config or {},
        use_container_width=True, height=height, hide_index=True,
    )
    if selectable:
        kwargs.update(on_select="rerun", selection_mode="single-row")
    if key:
        kwargs["key"] = key
    event = st.dataframe(df, **kwargs)
    if not selectable:
        return None
    try:
        sel = event.selection if hasattr(event, "selection") else (event or {}).get("selection", {})
        rows = sel.rows if hasattr(sel, "rows") else (sel or {}).get("rows", [])
    except Exception:
        rows = []
    return rows[0] if rows else None


def fab_ai_button() -> None:
    """Sağ alt köşede sabit AI butonu — tıklayınca ?nav=ai ile yönlendirir."""
    st.markdown(
        '<a href="?nav=ai" target="_self" class="fab-ai">'
        '<span class="pulse">🤖</span> AI Asistan</a>',
        unsafe_allow_html=True,
    )


def report_card(
    title: str,
    desc: str,
    page_key: str,
    icon: str = "📊",
    accent: str = "#3b5998",
) -> str:
    return (
        f'<a href="?nav={page_key}" target="_self" class="report-card" style="--accent:{accent}">'
        f'<div class="icon">{icon}</div>'
        f'<div class="title">{title}</div>'
        f'<div class="desc">{desc}</div>'
        f"</a>"
    )


def category_badge(cat: str | None) -> str:
    if not cat:
        return ""
    return f'<span class="cat-badge cat-{cat}">{cat}</span>'
