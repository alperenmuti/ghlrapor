"""
GHL veri çekme + DataFrame oluşturma + agent context katmanı.
Tüm rapor sayfaları ve AI agent buradan veri okur.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from attribution import attribution_fields, classify_traffic, split_attributions
from country import phone_to_country
from ghl_client import GHLAPIError, GHLAuthError, GHLClient

load_dotenv()

ABSOLUTE_MAX = 10000

# ---------- stage kategorileri (PDF'lerle uyumlu) ----------

# TEKLIF AŞAMASI (kullanıcı tanımı — 9 stage):
#   Offer Sent + Offer Sent Follow Up 1/2/3 + Negative + Price Negative
#   + Thinking Ahead + Positive Ticket Expected + Deal Completed
# "Waiting Offer" BU LİSTEDE YOK — teklif henüz verilmemiş demek.
TEKLIF_STAGES = {
    "Offer Sent",
    "Offer Sent Follow Up 1", "Offer Sent Follow Up 2", "Offer Sent Follow Up 3",
    "Offer Follow Up 1", "Offer Follow Up 2", "Offer Follow Up 3",  # alternatif yazımlar
    "Negative", "Price Negative",
    "Thinking Ahead", "Positive Ticket Expected",
    "Deal Completed", "Treatment Complated", "Treatment Completed",
}

# Alt sınıflar (boolean flag'ler için, TEKLIF'in alt kümeleridir):
POZITIF_OFFER_STAGES = {"Thinking Ahead", "Positive Ticket Expected"}
NEGATIF_OFFER_STAGES = {"Negative", "Price Negative"}
DEAL_STAGES = {
    "Deal Completed", "Treatment Complated", "Treatment Completed",
    "1 Visit Completed", "2 Visit Completed",
}

# KAYIP: teklif aşamasına gelmeden kaybedilenler.
# (Negative ve Price Negative TEKLIF içinde sayıldığı için BURADA YOK.)
KAYIP_STAGES = {
    "Bad Leads(Göçmen)", "Bad Leads (Göçmen)",
    "Not Interest", "Not Interes", "Not interesed",
    "Cancel Deal",
}


def stage_category(stage_name: str | None) -> str | None:
    """TEKLIF / KAYIP / None döner. (POZITIF/DEAL artık ayrı kategori değil;
    is_pozitif ve is_deal flag'leriyle takip edilir; çünkü kullanıcı tanımı
    teklif aşaması bunları zaten kapsıyor.)"""
    if not stage_name:
        return None
    if stage_name in TEKLIF_STAGES:
        return "TEKLIF"
    if stage_name in KAYIP_STAGES:
        return "KAYIP"
    return None


# ---------- cached fetchers ----------

@st.cache_resource(show_spinner=False)
def get_client() -> GHLClient:
    return GHLClient()


@st.cache_data(ttl=300, show_spinner=False)
def cached_pipelines() -> list[dict]:
    return get_client().list_pipelines()


@st.cache_data(ttl=300, show_spinner=False)
def cached_users() -> dict[str, str]:
    return get_client().user_name_map()


@st.cache_data(ttl=120, show_spinner=False)
def cached_total_count(pipeline_id: str | None) -> int:
    data = get_client().search_opportunities(limit=1, pipeline_id=pipeline_id)
    return int((data.get("meta") or {}).get("total") or 0)


@st.cache_data(ttl=300, show_spinner=False)
def cached_pipeline_counts() -> dict:
    """Her pipeline için (ve None/tüm için) toplam fırsat sayısı."""
    client = get_client()
    out: dict = {}
    pls = client.list_pipelines()
    for p in pls:
        try:
            data = client.search_opportunities(limit=1, pipeline_id=p["id"])
            out[p["id"]] = int((data.get("meta") or {}).get("total") or 0)
        except Exception:
            out[p["id"]] = 0
    try:
        data = client.search_opportunities(limit=1, pipeline_id=None)
        out[None] = int((data.get("meta") or {}).get("total") or 0)
    except Exception:
        out[None] = sum(out.values())
    return out


@st.cache_data(ttl=180, show_spinner=False)
def cached_opportunities(
    pipeline_id: str | None,
    max_records: int,
    date_after_ms: int | None = None,
    date_before_ms: int | None = None,
) -> list[dict]:
    """Tarih aralığında server-side filtreli pagination ile fırsatları çeker."""
    return list(
        get_client().iter_all_opportunities(
            pipeline_id=pipeline_id,
            max_records=max_records,
            date_after_ms=date_after_ms,
            date_before_ms=date_before_ms,
        )
    )


@st.cache_data(ttl=120, show_spinner=False)
def cached_count_for_range(
    pipeline_id: str | None,
    date_after_ms: int | None,
    date_before_ms: int | None,
) -> int:
    """Verilen tarih aralığında ve pipeline'da kaç fırsat var (1 sayfa total)."""
    data = get_client().search_opportunities(
        limit=1,
        pipeline_id=pipeline_id,
        date_after_ms=date_after_ms,
        date_before_ms=date_before_ms,
    )
    return int((data.get("meta") or {}).get("total") or 0)


@st.cache_data(ttl=180, show_spinner=False)
def cached_recent_messages(contact_id: str, limit: int = 10) -> list[dict]:
    if not contact_id:
        return []
    try:
        return get_client().get_recent_messages_for_contact(contact_id, max_messages=limit)
    except GHLAPIError:
        return []


def parse_dt(s: str | None) -> pd.Timestamp | None:
    if not s:
        return None
    try:
        return pd.to_datetime(s, utc=True)
    except Exception:
        return None


# ---------- DataFrame builder ----------

def opportunities_to_df(
    opps: list[dict],
    pipeline_lookup: dict[str, dict],
    user_lookup: dict[str, str],
) -> pd.DataFrame:
    rows = []
    for o in opps:
        pl = pipeline_lookup.get(o.get("pipelineId")) or {}
        stage_name = next(
            (s["name"] for s in pl.get("stages", []) if s.get("id") == o.get("pipelineStageId")),
            "?",
        )
        contact = o.get("contact") or {}

        first, last = split_attributions(o.get("attributions"))
        first_fields = attribution_fields(first, "first")
        last_fields = attribution_fields(last, "last")
        traffic_type = classify_traffic(last)

        phone = contact.get("phone")
        country_iso, country_name, country_flag = phone_to_country(phone)

        cat = stage_category(stage_name)
        status = o.get("status")
        # is_offer: kullanıcı tanımı teklif aşaması = 9 stage (TEKLIF kategorisi)
        is_offer = cat == "TEKLIF"
        # Alt-sınıf flag'leri (TEKLIF'in alt kümesi):
        is_pozitif = stage_name in POZITIF_OFFER_STAGES
        is_deal = stage_name in DEAL_STAGES or status == "won"
        is_negative_offer = stage_name in NEGATIF_OFFER_STAGES
        # Kayıp = teklif aşamasına gelmeden kaybedilenler
        is_lost = cat == "KAYIP" or status == "lost"
        monetary = float(o.get("monetaryValue") or 0)

        row = {
            "id": o.get("id"),
            "contact_id": o.get("contactId") or contact.get("id"),
            "name": o.get("name") or contact.get("name") or "(adsız)",
            "contact_name": contact.get("name"),
            "contact_email": contact.get("email"),
            "contact_phone": phone,
            "country_iso": country_iso or None,
            "country": country_name or None,
            "country_flag": country_flag or None,
            "pipeline": pl.get("name", "?"),
            "stage": stage_name,
            "stage_category": cat,
            "status": status,
            "monetary_value": monetary,
            "deal_revenue": monetary if is_deal else 0.0,
            "is_offer": is_offer,
            "is_pozitif": is_pozitif,
            "is_deal": is_deal,
            "is_negative_offer": is_negative_offer,
            "is_lost": is_lost,
            "source": o.get("source") or "Bilinmiyor",
            "assigned_to": user_lookup.get(o.get("assignedTo"), "Atanmamış"),
            "created_at": parse_dt(o.get("createdAt")),
            "updated_at": parse_dt(o.get("updatedAt")),
            "last_status_change": parse_dt(o.get("lastStatusChangeAt")),
            "traffic_type": traffic_type,
        }
        row.update(first_fields)
        row.update(last_fields)
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_by(df: pd.DataFrame, group_col: str, top: int | None = None) -> pd.DataFrame:
    """Standart kırılım: Lead / Dağılım / Teklif / Pozitif / Deal / Gelir / Teklif %.

    Teklif  = is_offer (9 stage'lik TEKLIF aşaması)
    Pozitif = is_pozitif (Thinking Ahead + Positive Ticket Expected — Teklif'in alt kümesi)
    Deal    = is_deal (Deal Completed + status=won)
    Gelir   = deal_revenue (deal'lerin parasal toplamı)
    Teklif% = Teklif / Lead
    """
    if df.empty or group_col not in df.columns:
        return pd.DataFrame()
    sub = df.copy()
    sub[group_col] = sub[group_col].fillna("Bilinmiyor")
    out = (
        sub.groupby(group_col, dropna=False)
        .agg(
            Lead=("id", "count"),
            Teklif=("is_offer", "sum"),
            Pozitif=("is_pozitif", "sum"),
            Deal=("is_deal", "sum"),
            Gelir=("deal_revenue", "sum"),
        )
        .reset_index()
    )
    total = max(out["Lead"].sum(), 1)
    out["Dağılım"] = (out["Lead"] / total * 100).round(2)
    out["Teklif %"] = (out["Teklif"] / out["Lead"] * 100).round(1)
    out = out.sort_values("Lead", ascending=False)
    if top:
        out = out.head(top)
    return out


# ---------- agent context ----------

def topn(series: pd.Series, n: int = 15) -> dict[str, int]:
    if series.dropna().empty:
        return {}
    return series.fillna("(boş)").value_counts().head(n).to_dict()


def df_to_agent_context(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"empty": True}

    won = df[df["status"] == "won"]
    paid = df[df["traffic_type"] == "paid"]
    organic = df[df["traffic_type"] == "organic"]

    def perf_groupby(sub: pd.DataFrame, col: str, top: int = 25) -> list[dict]:
        if sub.empty or col not in sub.columns:
            return []
        agg = (
            sub.groupby(col, dropna=True)
            .agg(
                lead=("id", "count"),
                offer=("is_offer", "sum"),
                deal=("is_deal", "sum"),
                revenue=("deal_revenue", "sum"),
            )
            .sort_values("lead", ascending=False)
            .head(top)
            .reset_index()
        )
        return agg.to_dict(orient="records")

    daily: list[dict] = []
    if df["created_at"].notna().any():
        daily = (
            df.dropna(subset=["created_at"])
            .assign(gun=lambda d: d["created_at"].dt.date.astype(str))
            .groupby("gun")
            .size()
            .tail(30)
            .reset_index(name="lead")
            .to_dict(orient="records")
        )

    return {
        "kayit_sayisi": int(len(df)),
        "tarih_araligi": {
            "min": str(df["created_at"].min()) if df["created_at"].notna().any() else None,
            "max": str(df["created_at"].max()) if df["created_at"].notna().any() else None,
        },
        "status": {
            "won": int(len(won)),
            "lost": int((df["status"] == "lost").sum()),
            "open": int((df["status"] == "open").sum()),
            "abandoned": int((df["status"] == "abandoned").sum()),
        },
        "win_rate_yuzde": round(len(won) / len(df) * 100, 2) if len(df) else 0,
        "toplam_deger": float(df["monetary_value"].sum()),
        "kazanilan_deger": float(df["deal_revenue"].sum()),
        "toplam_teklif": int(df["is_offer"].sum()),
        "toplam_deal": int(df["is_deal"].sum()),
        "trafik": {
            "paid": int(len(paid)),
            "organic": int(len(organic)),
            "unknown": int(len(df) - len(paid) - len(organic)),
        },
        "pipeline": topn(df["pipeline"]),
        "stage_top15": topn(df["stage"]),
        "kaynak_perf": perf_groupby(df, "source", 15),
        "satisci_perf": perf_groupby(df, "assigned_to", 20),
        "ulke_perf": perf_groupby(df, "country", 20),
        "ilk_kanal_top10": topn(df["first_channel"], 10),
        "son_kanal_top10": topn(df["last_channel"], 10),
        "reklam_seti_perf": perf_groupby(paid, "last_ad_set", 25),
        "kampanya_perf": perf_groupby(paid, "last_campaign", 15),
        "son_30_gun_trend": daily,
    }


def df_compact_sample(df: pd.DataFrame, n: int = 30) -> list[dict]:
    if df.empty:
        return []
    cols = [
        "name", "status", "stage", "stage_category", "pipeline",
        "monetary_value", "is_offer", "is_deal",
        "assigned_to", "traffic_type", "country", "country_iso",
        "last_ad_set", "last_campaign", "last_channel", "source",
        "created_at",
    ]
    cols = [c for c in cols if c in df.columns]
    sample = df[cols].head(n).copy()
    if "created_at" in sample.columns:
        sample["created_at"] = sample["created_at"].astype(str)
    return sample.to_dict(orient="records")


# ---------- chats ----------

CHAT_TRIGGER_KEYWORDS = (
    "sohbet", "konuşma", "konusma", "mesaj", "chat", "whatsapp",
    "yazışma", "yazisma", "ne yazmış", "ne demiş", "konversasyon",
)


def fetch_chats_bulk(contact_ids: list[str], per_contact: int = 8) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for cid in contact_ids:
        out[cid] = cached_recent_messages(cid, limit=per_contact)
    return out


def maybe_fetch_chats_for_prompt(prompt: str, df: pd.DataFrame, max_leads: int) -> dict[str, list[dict]]:
    p = prompt.lower()
    if not any(kw in p for kw in CHAT_TRIGGER_KEYWORDS):
        return {}
    if df.empty or "contact_id" not in df.columns:
        return {}
    cids = df["contact_id"].dropna().astype(str).head(max_leads).tolist()
    return fetch_chats_bulk(cids, per_contact=8)


def chats_to_context(chats: dict[str, list[dict]], df: pd.DataFrame) -> str:
    if not chats:
        return ""
    lookup = (
        df.set_index("contact_id")[
            ["name", "last_ad_set", "last_campaign", "last_channel", "status", "country"]
        ].to_dict(orient="index")
        if not df.empty
        else {}
    )
    out = ["## Sohbet geçmişleri (filtrelenmiş lead'lerin son mesajları)\n"]
    for cid, msgs in chats.items():
        if not msgs:
            continue
        info = lookup.get(cid, {})
        out.append(
            f"### Lead: {info.get('name','?')} | "
            f"ülke={info.get('country')} | "
            f"reklam_seti={info.get('last_ad_set')} | "
            f"kampanya={info.get('last_campaign')} | "
            f"kanal={info.get('last_channel')} | "
            f"status={info.get('status')}"
        )
        for m in msgs[-8:]:
            direction = "→" if m.get("direction") == "outbound" else "←"
            mtype = (m.get("messageType") or "").replace("TYPE_", "").lower()
            body = (m.get("body") or "(media)").strip().replace("\n", " ")
            ts = (m.get("dateAdded") or "")[:19]
            out.append(f"- [{ts}] {direction} {mtype}: {body[:280]}")
        out.append("")
    return "\n".join(out)
