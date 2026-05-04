"""
Papatya Dental — BI Merkezi.

Çok sayfalı yapı:
  • Ana sayfa: 6 raporun kart grid'i
  • 6 rapor sayfası: kaynak / satıcı / total lead / teklif & satış / reklam seti / ülke
  • AI Agent sayfası: chat + Plotly + sohbet enjeksiyonu

Sağ alt köşedeki kırmızı "🤖 AI Asistan" butonu her sayfada AI'a sıçramayı sağlar.
Sayfa geçişlerinde chat history korunur (st.session_state).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from chart_renderer import extract_chart_specs, render_chart
from data_loader import (
    ABSOLUTE_MAX,
    aggregate_by,
    cached_count_for_range,
    cached_opportunities,
    cached_pipeline_counts,
    cached_pipelines,
    cached_recent_messages,
    cached_total_count,
    cached_users,
    chats_to_context,
    df_compact_sample,
    df_to_agent_context,
    fetch_chats_bulk,
    maybe_fetch_chats_for_prompt,
    opportunities_to_df,
)
from ghl_client import GHLAPIError, GHLAuthError
from report_blocks import (
    category_badge,
    fab_ai_button,
    inject_css,
    render_distribution_table,
    render_header,
    render_metric_row,
    render_simple_table,
    report_card,
    section_title,
)

load_dotenv()

st.set_page_config(
    page_title="Papatya Dental — BI",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

# ========================================================
# Router state
# ========================================================
if "page" not in st.session_state:
    st.session_state.page = "home"

# Query param ile sayfa geçişi (kart click + floating button)
qp_nav = st.query_params.get("nav")
if qp_nav and qp_nav != st.session_state.page:
    st.session_state.page = qp_nav
    st.query_params.clear()
    st.rerun()

NAV = [
    ("home", "🏠 Ana Sayfa"),
    ("kaynak", "📡 Kaynak"),
    ("satici", "👥 Satıcı"),
    ("total", "📊 Total Lead"),
    ("teklif", "💼 Teklif & Satış"),
    ("reklam_seti", "📣 Reklam Seti"),
    ("ulke", "🌍 Ülke"),
    ("ai", "🤖 AI Agent"),
]

nav_cols = st.columns(len(NAV))
for i, (key, label) in enumerate(NAV):
    btn_type = "primary" if st.session_state.page == key else "secondary"
    if nav_cols[i].button(label, key=f"nav_{key}", use_container_width=True, type=btn_type):
        st.session_state.page = key
        st.rerun()

# ========================================================
# Sidebar — global veri kapsamı
# ========================================================
st.sidebar.header("📂 Veri Kapsamı")

try:
    pipelines = cached_pipelines()
    users = cached_users()
except GHLAuthError as e:
    st.sidebar.error(f"Auth: {e}")
    st.stop()
except GHLAPIError as e:
    st.sidebar.error(f"API: {e}")
    st.stop()

pipeline_lookup = {p["id"]: p for p in pipelines}

# Pipeline başına toplam sayım (selectbox label'larında gösterilir)
try:
    pl_counts = cached_pipeline_counts()
except GHLAPIError:
    pl_counts = {}

pipeline_id_options = [None] + [p["id"] for p in pipelines]
pipeline_id_to_name = {None: "(Tüm pipeline'lar)"}
for p in pipelines:
    pipeline_id_to_name[p["id"]] = p["name"]

# --- Sidebar widget'ları için kalıcı session_state default'ları ---
if "pipe_id" not in st.session_state:
    st.session_state["pipe_id"] = None
if "lc_persist" not in st.session_state:
    st.session_state["lc_persist"] = 0
_VALID_SFM = {
    "Tümü", "Sadece Teklif Aşaması", "Sadece Pozitif (Açık)",
    "Sadece Deal", "Sadece Negatif Teklif", "Sadece Kayıp (Teklif Öncesi)",
}
if st.session_state.get("sfm") not in _VALID_SFM:
    st.session_state["sfm"] = "Tümü"

def _pipe_label(pid: str | None) -> str:
    name = pipeline_id_to_name.get(pid, "?")
    cnt = pl_counts.get(pid, 0)
    return f"{name}  ·  {cnt:,} lead"

selected_pipeline_id = st.sidebar.selectbox(
    "Pipeline",
    options=pipeline_id_options,
    format_func=_pipe_label,
    key="pipe_id",
)
selected_pipeline = pipeline_id_to_name[selected_pipeline_id]
total_in_ghl = pl_counts.get(selected_pipeline_id, 0)

# --- Tarih aralığı (kalıcı, sayfa değişiminde sıfırlanmaz) ---
today = datetime.now(timezone.utc).date()
if "dr" not in st.session_state:
    st.session_state["dr"] = (today - timedelta(days=30), today)

DATE_PRESETS = {
    "Son 7 gün": 7,
    "Son 14 gün": 14,
    "Son 30 gün": 30,
    "Son 60 gün": 60,
    "Son 90 gün": 90,
    "Son 180 gün": 180,
    "Son 1 yıl": 365,
}

with st.sidebar.expander("📅 Tarih aralığı", expanded=True):
    st.caption("Hızlı seç:")
    preset_cols = st.columns(2)
    for i, (label, days) in enumerate(DATE_PRESETS.items()):
        if preset_cols[i % 2].button(label, key=f"preset_{days}", use_container_width=True):
            st.session_state["dr"] = (today - timedelta(days=days), today)
            st.rerun()
    date_range = st.date_input("Veya özel aralık", key="dr")

# Tarih aralığını UTC ms'e çevir (server-side date filtresi için)
if isinstance(date_range, tuple) and len(date_range) == 2:
    s_date, e_date = date_range
    date_after_ms = int(
        datetime.combine(s_date, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000
    )
    date_before_ms = int(
        datetime.combine(e_date, datetime.max.time(), tzinfo=timezone.utc).timestamp() * 1000
    )
else:
    date_after_ms = None
    date_before_ms = None

# Tarih aralığında gerçek lead sayısı (server-side count)
try:
    range_total = cached_count_for_range(selected_pipeline_id, date_after_ms, date_before_ms)
except GHLAPIError:
    range_total = 0

st.sidebar.caption(
    f"📅 Bu tarih aralığında **{range_total:,}** lead var "
    f"(pipeline toplamı {total_in_ghl:,})."
)

# --- Lead çekme: tarih aralığı baz alınır; opsiyonel manuel üst sınır ---
with st.sidebar.form("lead_form", clear_on_submit=False, border=True):
    st.caption(
        "Varsayılan: tarih aralığındaki **tüm** leadler çekilir. "
        "Hız için aşağıdan üst sınır verebilirsin (0 = sınır yok)."
    )
    new_lc = st.number_input(
        "Üst sınır (0 = aralıktaki tümü)",
        min_value=0, max_value=ABSOLUTE_MAX,
        value=st.session_state["lc_persist"],
        step=50,
    )
    submitted = st.form_submit_button(
        "🔍 Aralıktaki leadleri getir", use_container_width=True, type="primary",
    )
if submitted:
    st.session_state["lc_persist"] = int(new_lc)

override_lc = int(st.session_state["lc_persist"])
hard_cap = ABSOLUTE_MAX
if override_lc > 0:
    effective_max = min(override_lc, hard_cap, range_total or hard_cap)
    cap_msg = f"📌 Çekiliyor: **{effective_max:,}** lead (manuel üst sınır: {override_lc:,})"
else:
    effective_max = min(range_total or hard_cap, hard_cap)
    if range_total > hard_cap:
        cap_msg = (
            f"⚠️ Aralıkta {range_total:,} lead var; güvenlik için {hard_cap:,} ile "
            f"sınırlandı. Tarihi daralt veya manuel sınır gir."
        )
    else:
        cap_msg = f"📌 Çekiliyor: **{effective_max:,}** lead (aralıktaki tümü)"
st.sidebar.caption(cap_msg)

if st.sidebar.button("🔄 Önbelleği temizle", key="clear"):
    st.cache_data.clear()
    st.rerun()

if effective_max <= 0:
    st.warning(
        "👈 Soldan bir **tarih aralığı** seç ve **'🔍 Aralıktaki leadleri getir'** "
        "butonuna bas. Bu aralıktaki tüm leadler otomatik çekilir."
    )
    fab_ai_button()
    st.stop()

# ========================================================
# Veri çek (tarih bazlı server-side filtreli)
# ========================================================
with st.spinner(f"GHL'den {effective_max:,} fırsat çekiliyor…"):
    try:
        opps_raw = cached_opportunities(
            selected_pipeline_id,
            effective_max,
            date_after_ms,
            date_before_ms,
        )
    except GHLAPIError as e:
        st.error(f"API hatası: {e}")
        st.stop()
df = opportunities_to_df(opps_raw, pipeline_lookup, users)

# Tarih server-side filtreli geldi — burada ekstra filter etmiyoruz.
# Aşama filtresi sayımları df üzerinde hesaplanır.
_stage_counts = {
    "Tümü": len(df),
    "Sadece Teklif Aşaması": int(df["is_offer"].sum()) if not df.empty else 0,
    "Sadece Pozitif (Açık)": int(df["is_pozitif"].sum()) if not df.empty else 0,
    "Sadece Deal": int(df["is_deal"].sum()) if not df.empty else 0,
    "Sadece Negatif Teklif": int(df.get("is_negative_offer", pd.Series(dtype=bool)).sum()) if not df.empty else 0,
    "Sadece Kayıp (Teklif Öncesi)": int(df["is_lost"].sum()) if not df.empty else 0,
}
stage_filter_options = list(_stage_counts.keys())

with st.sidebar.expander("🔖 Aşama Filtresi", expanded=False):
    stage_filter_mode = st.radio(
        "Stage kategorisi",
        options=stage_filter_options,
        format_func=lambda x: f"{x}  ({_stage_counts[x]:,})",
        key="sfm",
        help=(
            "'Sadece Teklif Aşaması' = 9 stage:\n"
            "Offer Sent · Offer Sent Follow Up 1/2/3 · Negative · Price Negative · "
            "Thinking Ahead · Positive Ticket Expected · Deal Completed.\n\n"
            "'Sadece Kayıp' = teklif aşamasına gelmeden kaybedilen "
            "(Bad Leads · Not Interest · Cancel Deal)."
        ),
    )

filtered = df.copy()
if stage_filter_mode == "Sadece Teklif Aşaması":
    filtered = filtered[filtered["is_offer"]]
elif stage_filter_mode == "Sadece Pozitif (Açık)":
    filtered = filtered[filtered["is_pozitif"]]
elif stage_filter_mode == "Sadece Deal":
    filtered = filtered[filtered["is_deal"]]
elif stage_filter_mode == "Sadece Negatif Teklif":
    filtered = filtered[filtered.get("is_negative_offer", False)]
elif stage_filter_mode == "Sadece Kayıp (Teklif Öncesi)":
    filtered = filtered[filtered["is_lost"]]

# Tarih badge metni
date_badge = (
    f"{date_range[0].strftime('%d.%m.%Y')} – {date_range[1].strftime('%d.%m.%Y')}"
    if isinstance(date_range, tuple) and len(date_range) == 2
    else "—"
)
pipe_badge = selected_pipeline


# ========================================================
# Sayfa: Ana sayfa (kart grid)
# ========================================================

def page_home(filtered: pd.DataFrame) -> None:
    render_header(
        "Papatya Dental — BI Merkezi",
        "Tüm raporlara ve AI asistana tek noktadan erişim",
        [date_badge, pipe_badge, f"Lead kapsamı: {len(filtered):,}"],
    )

    render_metric_row([
        ("Toplam Lead", f"{len(filtered):,}"),
        ("Toplam Teklif", f"{int(filtered['is_offer'].sum()):,}", "alt"),
        ("Toplam Deal", f"{int(filtered['is_deal'].sum()):,}", "win"),
        ("Toplam Gelir", f"${filtered['deal_revenue'].sum():,.0f}", "win"),
    ])

    section_title("Raporlar")
    cards = [
        ("Kaynak Bazlı Lead", "Lead kaynaklarının (Facebook, TikTok, Organik vs.) performans analizi", "kaynak", "📡", "#3b5998"),
        ("Satıcı Bazlı Lead", "Satışçı bazında lead, teklif, deal, gelir ve no-answer kırılımı", "satici", "👥", "#7c5fb8"),
        ("Total Lead", "Toplam, günlük ortalama, en yüksek/düşük gün, haftalık + günlük dağılım", "total", "📊", "#1abc9c"),
        ("Teklif & Satış", "Pipeline stage funnel'ı, teklif/deal oranları, gelir dağılımı", "teklif", "💼", "#e67e22"),
        ("Reklam Seti", "Meta reklam seti (utmMedium) bazında lead, teklif, deal, gelir top-N", "reklam_seti", "📣", "#e74c3c"),
        ("Ülke Bazlı", "Telefon ülke kodundan türetilmiş ülke dağılımı + performans", "ulke", "🌍", "#16a085"),
    ]
    rows = [cards[:3], cards[3:]]
    for row in rows:
        cols = st.columns(3)
        for col, (title, desc, key, icon, accent) in zip(cols, row):
            col.markdown(report_card(title, desc, key, icon, accent), unsafe_allow_html=True)

    section_title("AI Asistan")
    st.markdown(
        '<a href="?nav=ai" target="_self" class="report-card" style="--accent:#FF4B4B">'
        '<div class="icon">🤖</div>'
        '<div class="title">Gemini 2.5 — Doğal dilde sorgula</div>'
        '<div class="desc">Reklam setlerini, kampanyaları, ülke bazlı dönüşümleri sohbet ile sorgula. '
        'Sohbet geçmişi, etkileşimli grafikler, modal pop-up\'larda lead detayı.</div>'
        '</a>',
        unsafe_allow_html=True,
    )


# ========================================================
# Sayfa: Kaynak Bazlı
# ========================================================

def page_kaynak(filtered: pd.DataFrame) -> None:
    render_header("Kaynak Bazlı Lead Raporu", "Lead kaynaklarının performans analizi", [date_badge, pipe_badge])
    if filtered.empty:
        st.warning("Bu kapsamda veri yok.")
        return

    agg = aggregate_by(filtered, "source")
    top_src = agg.iloc[0]["source"] if not agg.empty else "—"
    top_share = agg.iloc[0]["Dağılım"] if not agg.empty else 0

    render_metric_row([
        ("Toplam Lead", f"{len(filtered):,}"),
        ("Kaynak Sayısı", f"{filtered['source'].nunique():,}"),
        ("#1 Kaynak", top_src, "alt"),
        ("#1 Kaynak Oranı", f"%{top_share:.1f}", "alt"),
    ])
    section_title("Kaynak Bazlı Dağılım")
    st.caption("ℹ️ Bir satıra tıklayarak o kaynağın detaylarını ve sohbetlerini görüntüleyebilirsin.")
    idx = render_distribution_table(agg, "source", key="t_kaynak")
    handle_table_click("kaynak", "source", agg, idx, filtered)


# ========================================================
# Sayfa: Satıcı Bazlı
# ========================================================

def page_satici(filtered: pd.DataFrame) -> None:
    render_header("Satıcı Bazlı Lead Raporu", "Satışçı performans karşılaştırması", [date_badge, pipe_badge])
    if filtered.empty:
        st.warning("Bu kapsamda veri yok.")
        return

    agg = aggregate_by(filtered, "assigned_to")
    # No Answer: stage'inde "No Answer" geçenler
    if not agg.empty:
        no_ans = (
            filtered[filtered["stage"].fillna("").str.contains("No Answer", case=False, na=False)]
            .groupby("assigned_to").size().to_dict()
        )
        agg["No Answer"] = agg["assigned_to"].map(no_ans).fillna(0).astype(int)

    render_metric_row([
        ("Toplam Lead", f"{len(filtered):,}"),
        ("Aktif Satıcı", f"{filtered['assigned_to'].nunique():,}"),
        ("Toplam Deal", f"{int(filtered['is_deal'].sum()):,}", "win"),
        ("Toplam Gelir", f"${filtered['deal_revenue'].sum():,.0f}", "win"),
    ])
    section_title("Satıcı Bazlı Performans")
    st.caption("ℹ️ Bir satıcıya tıklayarak portföyünü ve sohbetlerini görüntüleyebilirsin.")
    idx = render_distribution_table(
        agg, "assigned_to",
        show_columns=["assigned_to", "Lead", "Dağılım", "Teklif", "Pozitif", "Deal", "Gelir", "No Answer", "Teklif %"],
        key="t_satici",
    )
    handle_table_click("satici", "assigned_to", agg, idx, filtered)


# ========================================================
# Sayfa: Total Lead
# ========================================================

def page_total(filtered: pd.DataFrame) -> None:
    render_header(
        "Total Lead Raporu",
        f"{date_badge} aralığında toplam lead analizi",
        [date_badge, pipe_badge],
    )
    if filtered.empty or filtered["created_at"].notna().sum() == 0:
        st.warning("Tarih bilgisi olan kayıt yok.")
        return

    daily = (
        filtered.dropna(subset=["created_at"])
        .assign(day=lambda d: d["created_at"].dt.tz_convert("UTC").dt.date)
        .groupby("day").size().reset_index(name="Lead")
        .sort_values("day")
    )
    weekly = (
        filtered.dropna(subset=["created_at"])
        .assign(week=lambda d: d["created_at"].dt.tz_convert("UTC").dt.isocalendar().week)
        .groupby("week").size().reset_index(name="Lead")
        .sort_values("week")
    )
    weekly["Hafta"] = weekly["week"].apply(lambda w: f"Hafta {int(w)}")
    weekly_total = weekly["Lead"].sum()
    weekly["Dağılım"] = (weekly["Lead"] / max(weekly_total, 1) * 100).round(2)

    daily_total = daily["Lead"].sum()
    daily["Dağılım"] = (daily["Lead"] / max(daily_total, 1) * 100).round(2)
    daily["Tarih"] = daily["day"].astype(str)

    avg = round(daily["Lead"].mean()) if not daily.empty else 0
    hi = int(daily["Lead"].max()) if not daily.empty else 0
    lo = int(daily["Lead"].min()) if not daily.empty else 0

    render_metric_row([
        ("Toplam Lead", f"{len(filtered):,}"),
        ("Günlük Ort.", f"{avg:,}", "alt"),
        ("En Yüksek Gün", f"{hi:,}", "win"),
        ("En Düşük Gün", f"{lo:,}", "warn"),
    ])

    section_title("Haftalık Dağılım")
    st.caption("ℹ️ Bir haftaya tıklayarak o haftanın lead detaylarını görebilirsin.")
    w_idx = render_simple_table(
        weekly[["Hafta", "Lead", "Dağılım"]],
        column_config={
            "Dağılım": st.column_config.ProgressColumn(
                "Dağılım", format="%.1f%%", min_value=0.0, max_value=100.0,
            ),
        },
        height=260, selectable=True, key="t_hafta",
    )
    if w_idx is not None and w_idx < len(weekly):
        wk = int(weekly.iloc[w_idx]["week"])
        seen = st.session_state.get("_seen_total_w")
        if seen != wk:
            st.session_state["_seen_total_w"] = wk
            sub = filtered[filtered["created_at"].dt.tz_convert("UTC").dt.isocalendar().week == wk]
            open_segment_dialog(f"Hafta {wk}", sub)

    section_title("Günlük Dağılım")
    st.caption("ℹ️ Bir güne tıklayarak o günün lead detaylarını görebilirsin.")
    d_idx = render_simple_table(
        daily[["Tarih", "Lead", "Dağılım"]],
        column_config={
            "Dağılım": st.column_config.ProgressColumn(
                "Dağılım", format="%.1f%%", min_value=0.0, max_value=100.0,
            ),
        },
        height=420, selectable=True, key="t_gun",
    )
    if d_idx is not None and d_idx < len(daily):
        day_val = daily.iloc[d_idx]["day"]
        seen = st.session_state.get("_seen_total_d")
        if seen != str(day_val):
            st.session_state["_seen_total_d"] = str(day_val)
            sub = filtered[filtered["created_at"].dt.tz_convert("UTC").dt.date == day_val]
            open_segment_dialog(f"Tarih: {day_val}", sub)


# ========================================================
# Sayfa: Teklif & Satış
# ========================================================

def page_teklif(filtered: pd.DataFrame) -> None:
    render_header("Teklif & Satış Raporu", "Stage bazlı satış funnel analizi", [date_badge, pipe_badge])
    if filtered.empty:
        st.warning("Bu kapsamda veri yok.")
        return

    total = len(filtered)
    # Teklif aşaması (kullanıcı tanımı): 9 stage
    teklif = int(filtered["is_offer"].sum())
    pozitif = int(filtered["is_pozitif"].sum())
    deal = int(filtered["is_deal"].sum())
    negatif_teklif = int(filtered.get("is_negative_offer", pd.Series(dtype=bool)).sum())
    revenue = float(filtered["deal_revenue"].sum())
    teklif_to_deal_pct = (deal / max(teklif, 1)) * 100

    render_metric_row([
        ("Toplam Lead", f"{total:,}"),
        ("Teklif Aşamasında", f"{teklif:,}", "alt"),
        ("Pozitif (Açık)", f"{pozitif:,}", "alt"),
        ("Deal", f"{deal:,}", "win"),
        ("Teklif → Deal %", f"%{teklif_to_deal_pct:.1f}", "warn"),
    ])

    section_title("Pipeline Stage Dağılımı")
    st.caption("ℹ️ Bir stage'e tıklayarak o stage'deki lead'leri ve sohbetleri görebilirsin.")
    stage_grp = (
        filtered.groupby(["stage", "stage_category"], dropna=False)
        .agg(Adet=("id", "count"), Gelir=("deal_revenue", "sum"))
        .reset_index()
        .sort_values("Adet", ascending=False)
    )
    stage_grp["Oran"] = (stage_grp["Adet"] / max(total, 1) * 100).round(2)
    stage_disp = stage_grp[["stage", "stage_category", "Adet", "Oran", "Gelir"]].rename(
        columns={"stage": "Stage", "stage_category": "Kategori"}
    )
    s_idx = render_simple_table(
        stage_disp,
        column_config={
            "Oran": st.column_config.ProgressColumn("Oran", format="%.1f%%", min_value=0.0, max_value=100.0),
            "Gelir": st.column_config.NumberColumn("Gelir", format="$%d"),
        },
        height=520, selectable=True, key="t_stage",
    )
    if s_idx is not None and s_idx < len(stage_grp):
        stage_name = str(stage_grp.iloc[s_idx]["stage"])
        seen = st.session_state.get("_seen_teklif_stage")
        if seen != stage_name:
            st.session_state["_seen_teklif_stage"] = stage_name
            sub = filtered[filtered["stage"] == stage_name]
            open_segment_dialog(f"Stage: {stage_name}", sub)

    section_title("Teklif Aşaması — Stage Detayı (9 stage)")
    st.caption(
        "Teklif aşaması = Offer Sent · Offer Sent Follow Up 1/2/3 · "
        "Negative · Price Negative · Thinking Ahead · Positive Ticket Expected · "
        "Deal Completed · ℹ️ Tıklanabilir."
    )
    teklif_only = filtered[filtered["stage_category"] == "TEKLIF"]
    teklif_breakdown = (
        teklif_only.groupby("stage", dropna=False)
        .agg(Adet=("id", "count"), Gelir=("monetary_value", "sum"))
        .reset_index()
        .sort_values("Adet", ascending=False)
    )
    teklif_breakdown["Oran (Teklif İçi)"] = (
        teklif_breakdown["Adet"] / max(teklif_breakdown["Adet"].sum(), 1) * 100
    ).round(1)
    teklif_disp = teklif_breakdown[["stage", "Adet", "Oran (Teklif İçi)", "Gelir"]].rename(
        columns={"stage": "Stage"}
    )
    tk_idx = render_simple_table(
        teklif_disp,
        column_config={
            "Oran (Teklif İçi)": st.column_config.ProgressColumn(
                "Oran (Teklif İçi)", format="%.1f%%", min_value=0.0, max_value=100.0,
            ),
            "Gelir": st.column_config.NumberColumn("Gelir", format="$%d"),
        },
        height=240, selectable=True, key="t_teklif_alt",
    )
    if tk_idx is not None and tk_idx < len(teklif_breakdown):
        stg = str(teklif_breakdown.iloc[tk_idx]["stage"])
        seen = st.session_state.get("_seen_teklif_alt")
        if seen != stg:
            st.session_state["_seen_teklif_alt"] = stg
            sub = filtered[filtered["stage"] == stg]
            open_segment_dialog(f"Teklif aşaması: {stg}", sub)

    section_title("Funnel Özeti")
    funnel = pd.DataFrame({
        "Metrik": [
            "Toplam Lead",
            "Teklif Aşamasında (9 stage)",
            "  • Açık Teklif (Offer Sent + FU 1/2/3)",
            "  • Pozitif Sonuç (Thinking Ahead + Positive Ticket Expected)",
            "  • Negatif Teklif (Negative + Price Negative)",
            "  • Deal Completed",
            "Kayıp (Teklif Öncesi)",
            "Toplam Gelir (Deal)",
        ],
        "Değer": [
            f"{total:,}",
            f"{teklif:,} (%{teklif/max(total,1)*100:.1f})",
            (
                f"{teklif - pozitif - deal - negatif_teklif:,}"
                if teklif >= pozitif + deal + negatif_teklif else f"{teklif:,}"
            ),
            f"{pozitif:,} (%{pozitif/max(total,1)*100:.1f})",
            f"{negatif_teklif:,} (%{negatif_teklif/max(total,1)*100:.1f})",
            f"{deal:,} (%{deal/max(total,1)*100:.1f})",
            f"{int(filtered['is_lost'].sum()):,}",
            f"${revenue:,.0f}",
        ],
    })
    st.dataframe(funnel, use_container_width=True, hide_index=True)


# ========================================================
# Sayfa: Reklam Seti
# ========================================================

def page_reklam_seti(filtered: pd.DataFrame) -> None:
    render_header("Reklam Seti Bazlı Lead Raporu", "Meta reklam seti (utmMedium) performans analizi", [date_badge, pipe_badge])
    if filtered.empty:
        st.warning("Bu kapsamda veri yok.")
        return

    agg = aggregate_by(filtered, "last_ad_set", top=30)
    total_sets = filtered["last_ad_set"].fillna("Bilinmiyor").nunique()
    top_set = agg.iloc[0]["last_ad_set"] if not agg.empty else "—"
    top_lead = int(agg.iloc[0]["Lead"]) if not agg.empty else 0

    render_metric_row([
        ("Toplam Lead", f"{len(filtered):,}"),
        ("Toplam Reklam Seti", f"{total_sets:,}"),
        ("#1 Reklam Seti", str(top_set)[:32], "alt"),
        ("#1 Lead Sayısı", f"{top_lead:,}", "win"),
    ])

    section_title("Reklam Seti Bazlı Lead Performansı (Top 30)")
    st.caption("ℹ️ Bir reklam setine tıklayarak o setin tüm lead'lerini ve sohbetlerini görebilirsin.")
    agg_disp = agg.rename(columns={"last_ad_set": "Reklam Seti"})
    idx = render_distribution_table(
        agg_disp,
        "Reklam Seti",
        show_columns=["Reklam Seti", "Lead", "Dağılım", "Teklif", "Pozitif", "Deal", "Gelir", "Teklif %"],
        height=720,
        key="t_adset",
    )
    if idx is not None and idx < len(agg_disp):
        ad_set_label = str(agg_disp.iloc[idx]["Reklam Seti"])
        seen = st.session_state.get("_seen_adset")
        if seen != ad_set_label:
            st.session_state["_seen_adset"] = ad_set_label
            open_dialog_for_segment("last_ad_set", ad_set_label, filtered)


# ========================================================
# Sayfa: Ülke
# ========================================================

def page_ulke(filtered: pd.DataFrame) -> None:
    render_header("Ülke Bazlı Rapor", "Telefon kodundan türetilen ülke dağılımı + performans", [date_badge, pipe_badge])
    if filtered.empty:
        st.warning("Bu kapsamda veri yok.")
        return

    work = filtered.copy()
    work["Ülke"] = work.apply(
        lambda r: f"{r.get('country_flag') or '🏳️'} {r.get('country') or 'Bilinmiyor'}".strip(),
        axis=1,
    )
    agg = aggregate_by(work, "Ülke")
    top_country = agg.iloc[0]["Ülke"] if not agg.empty else "—"
    top_lead = int(agg.iloc[0]["Lead"]) if not agg.empty else 0

    render_metric_row([
        ("Toplam Lead", f"{len(filtered):,}"),
        ("Toplam Ülke", f"{work['country_iso'].nunique():,}"),
        ("#1 Ülke", top_country, "alt"),
        ("#1 Ülke Lead", f"{top_lead:,}", "win"),
    ])
    section_title("Ülke Bazlı Lead Dağılımı")
    st.caption("ℹ️ Bir ülkeye tıklayarak o ülkedeki lead'leri ve sohbetleri görebilirsin.")
    idx = render_distribution_table(agg, "Ülke", key="t_ulke")
    if idx is not None and idx < len(agg):
        ulke_label = str(agg.iloc[idx]["Ülke"])
        seen = st.session_state.get("_seen_ulke")
        if seen != ulke_label:
            st.session_state["_seen_ulke"] = ulke_label
            open_dialog_for_segment("Ülke", ulke_label, work)


# ========================================================
# AI Agent sayfası
# ========================================================

SYSTEM_INSTRUCTIONS = """Sen GoHighLevel CRM verilerini analiz eden Türkçe konuşan bir BI ajansısın.

# Veri sözlüğü (DataFrame kolonları)
- status: open / won / lost / abandoned
- pipeline / stage / source / assigned_to
- stage_category: "TEKLIF" / "KAYIP" / null
- monetary_value, deal_revenue (sadece deal'lerde dolu)
- is_offer            → TEKLIF kategorisi (aşağıdaki 9 stage)
- is_pozitif          → Thinking Ahead + Positive Ticket Expected (TEKLIF alt kümesi)
- is_deal             → Deal Completed + status == "won" (TEKLIF alt kümesi)
- is_negative_offer   → Negative + Price Negative (TEKLIF alt kümesi)
- is_lost             → KAYIP kategorisi (Bad Leads, Not Interest, Cancel Deal) veya status=="lost"
- created_at (tarih)

## Teklif aşaması — KRİTİK kural (9 stage)
"Teklif aşaması" / "teklif aşamasındaki lead'ler" / "teklif veren" denildiğinde
SADECE şu 9 stage işaretlenir (is_offer == True ve stage_category == "TEKLIF"):
  • Offer Sent
  • Offer Sent Follow Up 1
  • Offer Sent Follow Up 2
  • Offer Sent Follow Up 3
  • Negative
  • Price Negative
  • Thinking Ahead
  • Positive Ticket Expected
  • Deal Completed

⚠️ "Waiting Offer" teklif aşamasında SAYILMAZ (lead henüz teklif almamış).
⚠️ "Negative" ve "Price Negative" KAYIP değildir — TEKLIF alt grubudur (teklif sonrası red).

Filtre:
```chart
{"filter": {"is_offer": true}}
```
veya
```chart
{"filter": {"stage_category": "TEKLIF"}}
```

Alt kırılımlar:
- "Pozitif" / "olumlu seyreden" → is_pozitif (Thinking Ahead + Positive Ticket Expected)
- "Deal" / "kazanılan" → is_deal (Deal Completed)
- "Negatif teklif" / "teklif sonrası red" → is_negative_offer (Negative + Price Negative)
- "Kayıp" / "teklif öncesi kayıp" → is_lost (Bad Leads, Not Interest, Cancel Deal)

Stage detayı sorulduğunda alt seviyede ayrı stage'leri saymaya devam et.
- traffic_type: paid / organic / unknown
- last_ad_set / first_ad_set: utmMedium = REKLAM SETİ ADI
- last_campaign / first_campaign, last_channel (facebook/tiktok/whatsapp), last_session_source
- country / country_iso / country_flag (telefon kodundan; GHL doğrudan country sunmuyor)

# Görselleştirme — ZORUNLU
Her cevabında 1-3 grafik yerleştir. Sayıları SEN hesaplama. ```chart``` JSON spec'i ver,
sistem dataframe üzerinden çizecek.

```chart
{
  "type": "bar" | "horizontal_bar" | "pie" | "funnel" | "line" | "scatter" | "table",
  "title": "Başlık",
  "groupby": "kolon_adı",
  "agg": "count" | "sum" | "mean",
  "value_col": "monetary_value" | "deal_revenue",
  "filter": {"traffic_type": "paid", "is_deal": true},
  "top": 10,
  "orientation": "h",
  "x": "kolon", "color": "kolon", "freq": "D" | "W" | "M"
}
```

# Yanıt yapısı
1. 2-4 cümle sayısal yorum
2. ```chart``` blok(lar)ı
3. 2-3 maddelik aksiyon önerisi

# Sohbet geçmişleri
"## Sohbet geçmişleri" bölümü gelirse — bu gerçek WhatsApp/SMS mesajları. Özet, trend,
sık ilgi konusu çıkar. Mesajların orijinal dilini koru, yorumu Türkçe ver.

# Etkileşim
Grafikteki çubuğa/dilime tıklanınca lead detayı + sohbetleri popup'ta açılır — bunu kullanıcıya hatırlat.
"""


def build_data_message(df: pd.DataFrame, user_prompt: str, chats: dict[str, list[dict]]) -> str:
    ctx = df_to_agent_context(df)
    sample = df_compact_sample(df, 30)
    chat_block = chats_to_context(chats, df)
    return (
        "## Mevcut filtrelenmiş veri context'i\n\n"
        f"### Yapılandırılmış metrikler\n```json\n{json.dumps(ctx, ensure_ascii=False, indent=2, default=str)}\n```\n\n"
        f"### Örneklem (ilk 30)\n```json\n{json.dumps(sample, ensure_ascii=False, indent=2, default=str)}\n```\n\n"
        + (chat_block + "\n\n" if chat_block else "")
        + "## Kullanıcı sorusu\n" + user_prompt + "\n\n"
        + "Lütfen kısa metin yorumu + uygun chart spec(ler)i + 2-3 aksiyon önerisi şeklinde cevap ver."
    )


def _spec_groupby_col(spec: dict) -> str | None:
    return spec.get("groupby") or spec.get("color") or spec.get("x")


def _label_from_point(pt: dict) -> str | None:
    for k in ("label", "y", "x"):
        v = pt.get(k)
        if v not in (None, ""):
            return str(v)
    return None


@st.dialog("🔍 Segment Detayı", width="large")
def open_segment_dialog(
    title: str,
    sub_df: pd.DataFrame,
    *,
    include_chats: bool = True,
    max_chat_leads: int = 5,
    extra_meta: str | None = None,
) -> None:
    """Genel amaçlı detay popup'ı: metrikler + lead listesi + sohbetler."""
    if sub_df is None or sub_df.empty:
        st.warning(f"`{title}` için kayıt bulunamadı.")
        return

    st.markdown(f"### {title}")
    if extra_meta:
        st.caption(extra_meta)

    cA, cB, cC, cD, cE = st.columns(5)
    cA.metric("Lead", f"{len(sub_df):,}")
    cB.metric("Teklif", int(sub_df.get("is_offer", pd.Series(dtype=bool)).sum()))
    cC.metric("Pozitif", int(sub_df.get("is_pozitif", pd.Series(dtype=bool)).sum()))
    cD.metric("Deal", int(sub_df.get("is_deal", pd.Series(dtype=bool)).sum()))
    cE.metric("Gelir", f"${sub_df.get('deal_revenue', pd.Series([0])).sum():,.0f}")

    show_cols = [
        "name", "country_flag", "country", "status", "stage", "monetary_value",
        "assigned_to", "last_ad_set", "last_campaign", "last_channel", "created_at",
    ]
    show_cols = [c for c in show_cols if c in sub_df.columns]
    table_view = sub_df[show_cols].copy()
    if "created_at" in table_view.columns:
        table_view["created_at"] = table_view["created_at"].astype(str).str[:16]
    st.dataframe(table_view, use_container_width=True, height=320, hide_index=True)

    csv = sub_df.to_csv(index=False).encode("utf-8")
    safe_title = "".join(c if c.isalnum() else "_" for c in title)[:50]
    st.download_button(
        "Bu segmenti CSV indir", csv,
        file_name=f"segment_{safe_title}.csv",
        mime="text/csv", key=f"dl_{safe_title}",
    )

    if include_chats and "contact_id" in sub_df.columns:
        st.markdown("### 💬 Son sohbetler")
        chosen = sub_df.dropna(subset=["contact_id"]).head(max_chat_leads)
        if chosen.empty:
            st.caption("Bu segmentte contact_id bulunan kayıt yok.")
        for _, row in chosen.iterrows():
            cid = str(row["contact_id"])
            line = (
                f"**{row.get('name','?')}** · "
                f"{row.get('contact_phone') or ''} · "
                f"{row.get('last_ad_set') or row.get('source') or ''}"
            )
            with st.expander(line):
                with st.spinner("Sohbet yükleniyor…"):
                    msgs = cached_recent_messages(cid, limit=10)
                if not msgs:
                    st.caption("Bu kişi için sohbet bulunamadı.")
                    continue
                for m in msgs:
                    arrow = "📤" if m.get("direction") == "outbound" else "📥"
                    mtype = (m.get("messageType") or "").replace("TYPE_", "").lower()
                    ts = (m.get("dateAdded") or "")[:19].replace("T", " ")
                    body = (m.get("body") or "(media/attachment)").strip()
                    st.markdown(f"{arrow} **{mtype}** · _{ts}_")
                    st.markdown(f"> {body}")


def open_dialog_for_segment(col: str, label: str, source_df: pd.DataFrame) -> None:
    """col/label'a göre filtreli alt-küme oluşturur ve dialog'u açar."""
    if col not in source_df.columns:
        st.error(f"Kolon yok: {col}")
        return
    if label in ("(boş)", "Bilinmiyor", "nan", "None"):
        sub = source_df[source_df[col].isna() | (source_df[col].astype(str) == label)]
    else:
        sub = source_df[source_df[col].astype(str) == str(label)]
    title = f"`{col}` = **{label}**"
    open_segment_dialog(title, sub)


def handle_table_click(
    page_key: str,
    col: str,
    agg: pd.DataFrame,
    idx: int | None,
    source_df: pd.DataFrame,
    label_col: str | None = None,
) -> None:
    """Tablo tıklamasında dialog açar. Aynı satıra art arda tıklamada açmaz (dedup)."""
    if idx is None or idx >= len(agg):
        return
    label_col = label_col or col
    if label_col not in agg.columns:
        return
    raw = agg.iloc[idx][label_col]
    label_str = "(boş)" if pd.isna(raw) else str(raw)
    seen_key = f"_seen_{page_key}"
    if st.session_state.get(seen_key) != label_str:
        st.session_state[seen_key] = label_str
        open_dialog_for_segment(col, label_str, source_df)


def render_assistant_message(text, specs, df, msg_idx, include_chats_in_modal, max_chat_leads):
    if text:
        st.markdown(text)
    for i, spec in enumerate(specs):
        fig = render_chart(spec, df)
        if fig is None:
            st.caption(f"_grafik render edilemedi: {spec.get('title') or spec.get('type')}_")
            continue
        chart_key = f"chart_m{msg_idx}_i{i}"
        event = st.plotly_chart(
            fig,
            use_container_width=True,
            on_select="rerun",
            selection_mode=("points",),
            key=chart_key,
        )
        try:
            points = (event.selection or {}).get("points") or []
        except AttributeError:
            points = (event.get("selection") or {}).get("points") or [] if isinstance(event, dict) else []
        if points:
            label = _label_from_point(points[0])
            seen_key = f"_seen_{chart_key}"
            if label and st.session_state.get(seen_key) != label:
                st.session_state[seen_key] = label
                col = _spec_groupby_col(spec)
                if col and col in df.columns:
                    open_dialog_for_segment(col, label, df)
        st.caption("ℹ️ Grafikteki bir öğeye tıklayarak o kategorinin lead detaylarını ve sohbetlerini açabilirsin.")


def page_ai(filtered: pd.DataFrame) -> None:
    render_header(
        "AI Agent — Sohbet Tabanlı Analiz",
        "Gemini 2.5 Flash · Etkileşimli grafikler · Sohbet geçmişlerine erişim",
        [date_badge, pipe_badge, f"Kapsam: {len(filtered):,} lead"],
    )

    # AI-spesifik filtre/ayar
    with st.sidebar.expander("💬 Sohbet Geçmişi", expanded=False):
        include_chats = st.checkbox("Sohbetleri AI'a gönder", value=True, key="ic")
        chat_max_leads = st.number_input(
            "Kaç lead için sohbet?", min_value=1, max_value=50, value=10, step=1, key="cml",
        )
    with st.sidebar.expander("🗑️ Konuşma", expanded=False):
        if st.button("Yeni konuşma başlat", key="reset"):
            st.session_state.pop("chat", None)
            st.session_state.pop("messages", None)
            st.rerun()
    with st.sidebar.expander("💡 Örnek prompt'lar"):
        st.markdown(
            "- En çok lead getiren 10 reklam setini grafikle göster\n"
            "- Reklam seti bazında toplam gelir top 10\n"
            "- US-IHDE-MBOF kampanyası sohbetlerini özetle\n"
            "- İngiltere lead'lerinin reklam seti dağılımı\n"
            "- Hangi reklam setlerinde win-rate %0?\n"
            "- Son 30 gün facebook trendi (line chart)"
        )

    if filtered.empty:
        st.warning("Veri yok.")
        return
    if not GOOGLE_API_KEY:
        st.error("GOOGLE_API_KEY .env'de yok.")
        return

    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)

    if "chat" not in st.session_state:
        model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=SYSTEM_INSTRUCTIONS)
        st.session_state.chat = model.start_chat(history=[])
        st.session_state.messages = []
    chat = st.session_state.chat

    # Geçmiş mesajlar
    for idx, m in enumerate(st.session_state.messages):
        with st.chat_message(m["role"]):
            if m["role"] == "assistant":
                render_assistant_message(
                    m.get("text", ""), m.get("specs", []), filtered,
                    msg_idx=idx,
                    include_chats_in_modal=include_chats,
                    max_chat_leads=int(chat_max_leads),
                )
            else:
                st.markdown(m["content"])

    if prompt := st.chat_input("Sorunu yaz: 'En iyi 10 reklam seti grafiği', 'Patient Lead pipeline son 30 gün trend'…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Gemini analiz ediyor…"):
                chats = (
                    maybe_fetch_chats_for_prompt(prompt, filtered, int(chat_max_leads))
                    if include_chats
                    else {}
                )
                try:
                    response = chat.send_message(build_data_message(filtered, prompt, chats))
                    raw = response.text
                except Exception as e:
                    raw = f"❌ Gemini hatası: {e}"
                    clean, specs = raw, []
                else:
                    clean, specs = extract_chart_specs(raw)
                render_assistant_message(
                    clean, specs, filtered,
                    msg_idx=len(st.session_state.messages),
                    include_chats_in_modal=include_chats,
                    max_chat_leads=int(chat_max_leads),
                )

        st.session_state.messages.append(
            {"role": "assistant", "text": clean, "specs": specs}
        )


# ========================================================
# Dispatch
# ========================================================
PAGES = {
    "home": page_home,
    "kaynak": page_kaynak,
    "satici": page_satici,
    "total": page_total,
    "teklif": page_teklif,
    "reklam_seti": page_reklam_seti,
    "ulke": page_ulke,
    "ai": page_ai,
}
PAGES.get(st.session_state.page, page_home)(filtered)

# Floating AI button (AI sayfasında zaten oradayız)
if st.session_state.page != "ai":
    fab_ai_button()
