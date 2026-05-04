import streamlit as st
import os
import json
import requests
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv
import google.generativeai as genai

# .env yükle
load_dotenv()

st.set_page_config(page_title="GHL Advanced BI Agent", page_icon="🔬", layout="wide")

# API Keys
GHL_API_KEY = os.getenv("GOHIGHLEVEL_API_KEY")
GHL_LOCATION_ID = os.getenv("GOHIGHLEVEL_LOCATION_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Gemini
genai.configure(api_key=GOOGLE_API_KEY)
MODEL_NAME = "gemini-2.5-flash"

if "data" not in st.session_state: st.session_state.data = {"opps": None}
if "messages" not in st.session_state: st.session_state.messages = []

# --- GHL ENGINE ---
HEADERS = {"Authorization": f"Bearer {GHL_API_KEY}", "Version": "2021-07-28", "Accept": "application/json"}

def fetch_deep_data():
    """Özel olarak last_attribution ve utm_medium verilerini içeren derin çekim."""
    try:
        # 1. Custom Field Tanımlarını Çek (last_attribution ve utm_medium ID'lerini bul)
        cf_res = requests.get(f"https://services.leadconnectorhq.com/locations/{GHL_LOCATION_ID}/customFields", headers=HEADERS)
        cf_map = {}
        last_attr_id = None
        utm_medium_id = None
        
        if cf_res.status_code == 200:
            fields = cf_res.json().get('customFields', [])
            for f in fields:
                key = f.get('fieldKey', '').lower()
                name = f.get('name', '').lower()
                if key == 'last_attribution' or name == 'last_attribution':
                    last_attr_id = f['id']
                if key == 'utm_medium' or name == 'utm_medium':
                    utm_medium_id = f['id']
                cf_map[f['id']] = f['name']

        # 2. Satışçılar
        u_res = requests.get("https://services.leadconnectorhq.com/users/", headers=HEADERS, params={"locationId": GHL_LOCATION_ID})
        users = {u['id']: f"{u.get('firstName', '')} {u.get('lastName', '')}" for u in u_res.json().get('users', [])} if u_res.status_code == 200 else {}

        # 3. Fırsatlar
        o_res = requests.get("https://services.leadconnectorhq.com/opportunities/search", headers=HEADERS, params={"location_id": GHL_LOCATION_ID, "limit": 100})
        if o_res.status_code != 200: return f"API Hatası: {o_res.status_code}"
        
        opps_raw = o_res.json().get('opportunities', [])
        results = []
        for o in opps_raw:
            contact = o.get('contact', {})
            custom_fields = o.get('customFields', [])
            
            # last_attribution ve utm_medium değerlerini ayıkla
            last_attr_val = "Bilinmiyor"
            utm_medium_val = "Bilinmiyor"
            
            for cf in custom_fields:
                if cf['id'] == last_attr_id: last_attr_val = cf['value']
                if cf['id'] == utm_medium_id: utm_medium_val = cf['value']
            
            # Eğer özel alanda yoksa standart attribution'a bak (fallback)
            if last_attr_val == "Bilinmiyor":
                last_attr_val = (o.get('attribution') or {}).get('adSetName') or "Organik"

            results.append({
                "Müşteri": contact.get('name'),
                "Telefon": contact.get('phone') or "Yok",
                "Durum": o.get('status'),
                "Değer": o.get('monetaryValue', 0),
                "Last_Attribution": last_attr_val,
                "UTM_Medium": utm_medium_val,
                "Kaynak": o.get('source') or "Bilinmiyor",
                "Satışçı": users.get(o.get('assignedTo'), "Atanmamış"),
                "Tarih": o.get('createdAt')
            })
        
        st.session_state.data['opps'] = pd.DataFrame(results)
        return f"Başarıyla {len(results)} lead çekildi. last_attribution ve utm_medium verileri analiz edildi."
    except Exception as e:
        return f"Hata: {str(e)}"

# --- UI ---
c1, c2 = st.columns([1, 1.2])

with c1:
    st.subheader("🤖 BI Asistanı (Attribution Odaklı)")
    for m in st.session_state.messages:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if p := st.chat_input("Attribution analizi yap..."):
        st.session_state.messages.append({"role": "user", "content": p})
        with st.chat_message("user"): st.markdown(p)
        
        with st.chat_message("assistant"):
            with st.spinner("Veriler işleniyor..."):
                status = fetch_deep_data()
                st.info(status)
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    df = st.session_state.data['opps']
                    stats = f"Toplam: {len(df)}, Won: {len(df[df['Durum']=='won'])}"
                    prompt = f"Soru: {p}\n\nİstatistik: {stats}\nVeriler:\n{df.to_string()}\n\nLütfen 'last_attribution' ve 'utm_medium' verilerini temel alarak raporla."
                    response = model.generate_content(prompt)
                    st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                except Exception as e: st.error(f"AI Hatası: {str(e)}")

with c2:
    st.subheader("📊 Gelişmiş Attribution Paneli")
    if st.session_state.data['opps'] is not None:
        df = st.session_state.data['opps']
        # Metrikler
        m1, m2, m3 = st.columns(3)
        m1.metric("Toplam Lead", len(df))
        m2.metric("Satış Oranı", f"%{(len(df[df['Durum']=='won'])/len(df)*100):.1f}")
        m3.metric("UTM Kayıtlı", len(df[df['UTM_Medium'] != "Bilinmiyor"]))
        
        st.plotly_chart(px.pie(df, names='Last_Attribution', title="Last Attribution Dağılımı"), use_container_width=True)
        st.plotly_chart(px.bar(df.groupby('UTM_Medium').size().reset_index(name='N'), x='UTM_Medium', y='N', title="UTM Medium Dağılımı"), use_container_width=True)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Veri yok.")
