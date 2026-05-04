"""
GHL API V2 — Pipeline Test
En basit doğrulama: V2 endpoint + Version 2021-07-28 header ile pipeline listesi.
Başarılı yanıt = API key + Location ID + V2 erişimi sağlam demektir.
"""
import os
import sys
import json
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GOHIGHLEVEL_API_KEY")
LOCATION_ID = os.getenv("GOHIGHLEVEL_LOCATION_ID")
BASE_URL = "https://services.leadconnectorhq.com"

if not API_KEY or not LOCATION_ID:
    print("[HATA] .env dosyasında GOHIGHLEVEL_API_KEY veya GOHIGHLEVEL_LOCATION_ID eksik.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Version": "2021-07-28",
    "Accept": "application/json",
}

def test_pipelines():
    url = f"{BASE_URL}/opportunities/pipelines"
    params = {"locationId": LOCATION_ID}
    print(f"--- GHL V2 Pipeline Testi ---")
    print(f"URL    : {url}")
    print(f"LocID  : {LOCATION_ID}")
    print(f"KeyTag : {API_KEY[:8]}…{API_KEY[-4:]}")

    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    print(f"Status : {r.status_code}")

    if r.status_code != 200:
        print(f"[HATA] Body: {r.text[:500]}")
        return False

    data = r.json()
    pipelines = data.get("pipelines", [])
    print(f"Bulunan pipeline sayısı: {len(pipelines)}")
    for p in pipelines:
        stages = p.get("stages", [])
        print(f"  • {p.get('name', '(adsız)')}  [id={p.get('id')}]  → {len(stages)} stage")
        for s in stages:
            print(f"      - {s.get('name')}  (id={s.get('id')})")
    return True

if __name__ == "__main__":
    ok = test_pipelines()
    sys.exit(0 if ok else 2)
