"""
GHL opportunity verisinden first/last attribution alanlarını çıkarma.

GHL'in attributions dizisi:
- isFirst=true   → ilk temas (lead nereden geldi)
- isLast=true    → son temas (deal'in kapanmasına en yakın kanal)

Ad set ismi GHL'de utmMedium alanında saklanıyor (kafa karıştırıcı ama böyle).
"""
from __future__ import annotations

from typing import Any


def split_attributions(attributions: list[dict] | None) -> tuple[dict, dict]:
    attributions = attributions or []
    first = next((a for a in attributions if a.get("isFirst")), {})
    last = next((a for a in attributions if a.get("isLast")), {})
    if not first and attributions:
        first = attributions[0]
    if not last and attributions:
        last = attributions[-1]
    return first, last


def attribution_fields(attr: dict, prefix: str) -> dict[str, Any]:
    """Tek bir attribution dict'ini düz alanlara açar.

    Anahtar eşleme:
      utmMedium       → ad_set       (GHL'de reklam seti adı bu alanda tutuluyor)
      utmCampaign     → campaign
      utmContent      → ad_content
      utmSource       → utm_source
      utmSessionSource→ session_source  (Paid Social / Social media / Organic ...)
      medium          → channel          (facebook / tiktok / whatsapp)
      adSource        → ad_platform
      utmAdId         → ad_id
      utmCampaignId   → campaign_id
    """
    return {
        f"{prefix}_ad_set": attr.get("utmMedium"),
        f"{prefix}_campaign": attr.get("utmCampaign"),
        f"{prefix}_ad_content": attr.get("utmContent"),
        f"{prefix}_utm_source": attr.get("utmSource"),
        f"{prefix}_session_source": attr.get("utmSessionSource"),
        f"{prefix}_channel": attr.get("medium"),
        f"{prefix}_ad_platform": attr.get("adSource"),
        f"{prefix}_ad_id": attr.get("utmAdId"),
        f"{prefix}_campaign_id": attr.get("utmCampaignId"),
        f"{prefix}_is_paid": bool(attr.get("utmMedium")),
    }


def classify_traffic(last_attr: dict) -> str:
    """Lead'i paid / organic / unknown olarak sınıfla.

    Mantık: utmMedium (reklam seti) dolu ise paid; değilse session_source/medium'a bak.
    """
    if last_attr.get("utmMedium"):
        return "paid"
    sess = (last_attr.get("utmSessionSource") or "").lower()
    if "paid" in sess:
        return "paid"
    if last_attr.get("medium") or sess:
        return "organic"
    return "unknown"
