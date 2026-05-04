import os
import requests
import json
import logging
from dotenv import load_dotenv

# Daha iyi loglama için temel yapılandırma
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_ghl_opportunities():
    """
    GHL API V2'den fırsatları (opportunities) çeker ve veriler.json dosyasına kaydeder.

    Returns:
        bool: İşlemin başarılı olup olmadığını belirten boolean bir değer.
    """
    # .env dosyasındaki ortam değişkenlerini yükle
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=dotenv_path)

    api_key = os.getenv("GOHIGHLEVEL_API_KEY")
    location_id = os.getenv("GOHIGHLEVEL_LOCATION_ID")

    if not api_key or not location_id:
        logging.error("Hata: GOHIGHLEVEL_API_KEY ve GOHIGHLEVEL_LOCATION_ID .env dosyasında bulunamadı.")
        return False

    logging.info(f"{location_id} ID'li konum için GHL API V2'den fırsatlar çekiliyor...")

    # GHL API V2 fırsat arama endpoint'i
    url = "https://services.gohighlevel.com/opportunities/search"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": "2021-07-28"  # Önerilen API versiyonu
    }

    # Konum ID'sine göre filtreleme yap
    params = {
        "location_id": location_id,
        "limit": 100,  # Tek seferde en fazla 100 fırsat çek
        "sort_by": "created_at",
        "order": "desc"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30) # Timeout eklemek iyi bir pratiktir
        response.raise_for_status()  # Olası HTTP hatalarını kontrol et

        data = response.json()
        output_filename = 'veriler.json'
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        logging.info(f"Başarılı! {len(data.get('opportunities', []))} adet fırsat '{output_filename}' dosyasına kaydedildi.")
        return True

    except requests.exceptions.RequestException as e:
        logging.error(f"API isteği sırasında bir hata oluştu: {e}")
        return False

if __name__ == "__main__":
    fetch_ghl_opportunities()