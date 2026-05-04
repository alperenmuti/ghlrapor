import requests
import json
import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

def fetch_opportunities():
    # API anahtarı ve Location ID'yi al
    api_key = os.getenv("GOHIGHLEVEL_API_KEY")
    location_id = os.getenv("GOHIGHLEVEL_LOCATION_ID")

    if not api_key or not location_id:
        print("Hata: .env dosyasında GOHIGHLEVEL_API_KEY veya GOHIGHLEVEL_LOCATION_ID eksik!")
        return

    # GHL API V2 Opportunities search endpoint
    url = "https://services.leadconnectorhq.com/opportunities/search"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": "2021-07-28",
        "Accept": "application/json"
    }
    
    params = {
        "location_id": location_id,
        "limit": 100  # Daha fazla veri çekmek için limit artırıldı
    }

    try:
        print(f"Opportunities verileri çekiliyor (Location ID: {location_id})...")
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        opps = data.get('opportunities', [])
        
        # Veriyi veriler.json olarak kaydet
        with open("veriler.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        print(f"Başarılı! Veriler 'veriler.json' dosyasına kaydedildi.")
        print(f"Bulunan toplam fırsat sayısı: {data.get('total', len(opps))}")
        print(f"Çekilen fırsat sayısı: {len(opps)}")
        
        if opps:
            print("\nSon çekilen fırsatlardan bazıları (Lead İsimleri):")
            for i, opp in enumerate(opps[:10]):  # İlk 10 tanesini terminalde göster
                contact_name = opp.get('contact', {}).get('name', 'İsimsiz')
                opp_name = opp.get('name', 'Başlıksız')
                print(f"{i+1}. Fırsat: {opp_name} | Kişi: {contact_name}")

    except requests.exceptions.RequestException as e:
        print(f"API isteği sırasında bir hata oluştu: {e}")
        if hasattr(e.response, 'text'):
            print(f"Hata detayı: {e.response.text}")

if __name__ == "__main__":
    fetch_opportunities()
