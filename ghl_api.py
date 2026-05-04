import requests
import pandas as pd
import logging

# n8n'den aldığın Webhook URL'sini buraya yapıştır
N8N_WEBHOOK_URL = "https://papatyadental.app.n8n.cloud/webhook-test/ghl-data"
OUTPUT_CSV_PATH = "ghl_context.csv"

# Loglama yapılandırması
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_ghl_data():
    """n8n webhook'undan GHL verilerini çeker ve bir DataFrame olarak döndürür."""
    logging.info("n8n üzerinden veriler çekiliyor...")
    try:
        response = requests.get(N8N_WEBHOOK_URL, timeout=30)
        response.raise_for_status()  # HTTP hatalarını kontrol et

        data = response.json()
        # n8n çıktısındaki 'opportunities' listesine erişim.
        # Veri yapısının beklenen gibi olduğundan emin olmak için kontrol ekleyelim.
        if isinstance(data, list) and len(data) > 0 and 'opportunities' in data[0]:
            opps = data[0]['opportunities']
            return pd.DataFrame(opps)
        else:
            logging.warning("Beklenen 'opportunities' verisi n8n yanıtında bulunamadı.")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"n8n webhook'una erişirken hata oluştu: {e}")
        return None
    except (KeyError, IndexError, TypeError) as e:
        logging.error(f"n8n'den gelen veri işlenirken bir hata oluştu (beklenmeyen format): {e}")
        return None

def main():
    """Ana fonksiyon: Veriyi çeker ve CSV dosyasına kaydeder."""
    df = fetch_ghl_data()
    if df is not None and not df.empty:
        logging.info(f"Başarıyla {len(df)} adet fırsat verisi çekildi.")
        df.to_csv(OUTPUT_CSV_PATH, index=False)
        logging.info(f"Veri '{OUTPUT_CSV_PATH}' dosyasına kaydedildi.")

if __name__ == "__main__":
    main()
