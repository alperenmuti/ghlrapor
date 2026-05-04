import json
from collections import defaultdict

def analyze_opportunities(file_path='veriler.json'):
    """
    veriler.json dosyasını analiz eder ve terminale bir özet rapor yazdırır.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Hata: '{file_path}' dosyası bulunamadı. Lütfen önce 'fetch_opportunities.py' scriptini çalıştırdığınızdan emin olun.")
        return
    except json.JSONDecodeError:
        print(f"Hata: '{file_path}' dosyası geçerli bir JSON formatında değil.")
        return

    opportunities = data.get('opportunities', [])
    if not opportunities:
        print("Analiz edilecek fırsat bulunamadı.")
        return

    # Analiz için değişkenleri hazırla
    total_opportunities = len(opportunities)
    status_counts = defaultdict(int)
    value_by_status = defaultdict(float)
    total_value = 0.0
    pipeline_counts = defaultdict(int)
    pipeline_values = defaultdict(float)
    currency = opportunities[0].get('currency', 'USD') if opportunities else 'USD'

    # Verileri işle
    for opp in opportunities:
        status = opp.get('status', 'unknown')
        value = float(opp.get('monetaryValue', 0))
        pipeline_name = opp.get('pipelineName', 'Bilinmeyen Pipeline')

        status_counts[status] += 1
        value_by_status[status] += value
        total_value += value
        pipeline_counts[pipeline_name] += 1
        pipeline_values[pipeline_name] += value

    # Raporu oluştur ve yazdır
    print("--- Fırsat Analiz Raporu ---")
    print(f"\nToplam Fırsat Sayısı: {total_opportunities}")
    print(f"Tüm Fırsatların Toplam Değeri: {total_value:,.2f} {currency}")

    print("\nDuruma Göre Dağılım:")
    for status, count in sorted(status_counts.items()):
        value = value_by_status[status]
        print(f"- {status.capitalize():<10}: {count:<4} adet, Toplam Değer: {value:,.2f} {currency}")

    print("\nPipeline'a Göre Dağılım:")
    for name, count in sorted(pipeline_counts.items()):
        value = pipeline_values[name]
        print(f"- {name}: {count:<4} adet, Toplam Değer: {value:,.2f} {currency}")

if __name__ == "__main__":
    analyze_opportunities()