import requests

# Değişkenleri direkt buraya yazıyoruz (Dosya okuma hatasını elemek için)
api_key = "pit-7cd5d8a6-94e8-4ae0-8a3f-a46c4db6ab80"
loc_id = "c4CsT0TnyU8iARVHZxuB"

# URL'den 'v1'den sonrasını temizleyip en basit endpoint'i deneyelim
url = "https://rest.gohighlevel.com/v1/pipelines/"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

# n8n'in yaptığı gibi ID'yi parametre olarak ekleyelim
params = {"locationId": loc_id}

print("--- n8n Simülasyon Testi ---")
response = requests.get(url, headers=headers, params=params)

print(f"Status: {response.status_code}")
print(f"Body: {response.text}")
