"""
Telefon numarasından ülke ISO kodu, ülke adı ve bayrak emojisi türetir.
"""
from __future__ import annotations

import phonenumbers
from phonenumbers.geocoder import country_name_for_number


def iso_to_flag(iso: str | None) -> str:
    if not iso or len(iso) != 2 or not iso.isalpha():
        return ""
    return "".join(chr(ord(c) - ord("A") + 0x1F1E6) for c in iso.upper())


def phone_to_country(phone: str | None, default_region: str = "TR") -> tuple[str, str, str]:
    """(iso, name, flag) döner. Çözülemezse ('', '', '')."""
    if not phone or not isinstance(phone, str):
        return "", "", ""
    p = phone.strip()
    region = None if p.startswith("+") else default_region
    try:
        num = phonenumbers.parse(p, region)
    except phonenumbers.NumberParseException:
        return "", "", ""
    iso = phonenumbers.region_code_for_number(num) or ""
    if not iso:
        return "", "", ""
    name = country_name_for_number(num, "tr") or country_name_for_number(num, "en") or iso
    return iso, name, iso_to_flag(iso)
