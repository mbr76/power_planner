import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import os
import math
from pacing_optimizer import AdvancedPacingOptimizer

# Seitenkonfiguration für ein breites Layout
st.set_page_config(page_title="Radsport Pacing Optimizer", layout="wide")

st.title("🚴‍♂️ Physikbasierter Routen- & Pacing-Optimierer")
st.markdown("Kopplung aus Streckenphysik, W'-Akku (anaerob) und metabolischem Kohlenhydrat-Tank.")

# ==========================================
# 1. SEITENLEISTE (EINGABEPARAMETER)
# ==========================================
st.sidebar.header("🔧 Fahrereinstellungen")

initial_ftp = st.sidebar.number_input("Start-FTP (Watt)", min_value=100, max_value=500, value=310, step=5)
w_prime = st.sidebar.slider("W'-Kapazität (Joule)", 10000, 30000, 20000, step=1000)
rider_w = st.sidebar.number_input("Fahrergewicht (kg)", min_value=40.0, max_value=130.0, value=72.0, step=0.5)
bike_w = st.sidebar.number_input("Fahrrad- & Ausrüstungsgewicht (kg)", min_value=5.0, max_value=20.0, value=8.0, step=0.1)

st.sidebar.header("🍏 Ernährungsstrategie")
carbs_per_hour = st.sidebar.slider("Kohlenhydrate pro Stunde (g)", 20, 120, 90, step=5)

st.sidebar.header("🛣️ Routen-Konfiguration")
target_f = st.sidebar.slider("Intensitätsfaktor (Target Factor)", 0.60, 1.00, 0.82, step=0.01)

# GPX-Datei-Upload oder Standard-Simulation
uploaded_file = st.sidebar.file_saver = st.sidebar.file_uploader("GPX-Datei hochladen", type=["gpx"])
gpx_path = "oetztaler_route.gpx"

if uploaded_file is not None:
    # Temporär speichern
    with open("temp_route.gpx", "wb") as f:
        f.write(uploaded_file.getbuffer())
    gpx_path = "temp_route.gpx"

# ==========================================
# 2. BERECHNUNG IM HINTERGRUND (PYTHON)
# ==========================================
# Initialisiere deinen physikalischen Optimierer
optimizer = AdvancedPacingOptimizer(
    initial_ftp=initial_ftp,
    w_prime_max=w_prime,
    target_factor=target_f,
    carb_intake_per_hour=carbs_per_hour,
    rider_weight=rider_w,
    bike_weight=bike_w
)

# Lade Route & berechne Sekunden-Pacing (Wir brauchen die Rohdaten für die Charts!)
# Da optimize_pacing direkt die Intervalle ausgibt, fügen wir im Skript eine
# interne Methode hinzu oder nutzen den Optimizer, um die Daten zu holen.
# Für die App simulieren wir hier den Verlauf visuell basierend auf den Intervallen.

try:
    df_route = optimizer.parse_gpx(gpx_path)
    # Wichtig: Wir fangen hier die Intervalle ab
    df_intervals = optimizer.optimize_pacing(df_route)

    # Gesamtfahrzeit berechnen
    total_minutes = df_intervals['duration_min'].sum()
    total_hours = total_minutes / 60.0
    h = math.floor(total_hours)
    m = round((total_hours % 1) * 60)

    # ==========================================
    # 3. METRIKEN ANZEIGEN (DASHBOARD)
    # ==========================================
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Prognostizierte Fahrzeit", f"{h:02d}:{m:02d} Std")
    col2.metric("Systemgewicht Gesamt", f"{rider_w + bike_weight_calc := rider_w + bike_w:.1f} kg")
    col3.metric("Relative FTP", f"{initial_ftp / rider_w:.2f} W/kg")
    col4.metric("Gesamtbedarf KH", f"{total_hours * carbs_per_hour:.1f} g")

    # ==========================================
    # 4. INTERAKTIVE GRAFIKEN (PLOTLY)
    # ==========================================
    st.subheader("📊 Strategie- und Streckenverlauf")

    # Grafik 1: Leistungsintervalle über die Distanz
    fig_pacing = px.line(
        df_intervals,
        x="start_km",
        y="target_watt",
        title="Geplante Leistungsintervalle (Watt) im Streckenverlauf",
        labels={"start_km": "Distanz (km)", "target_watt": "Ziel-Leistung (Watt)"},
        line_shape="hv" # Treppenstufen-Fahrweise
    )
    fig_pacing.update_traces(line_color="#FF4B4B", line_width=3)
    st.plotly_chart(fig_pacing, use_container_width=True)

    # ==========================================
    # 5. TABELLE & LOGISTIK (EINKAUFSLISTE)
    # ==========================================
    st.subheader("📋 Intervall-Übersicht")
    st.dataframe(df_intervals, use_container_width=True)

    st.subheader("🛒 Deine Sportnahrungs-Einkaufsliste")

    iso_bottles = math.ceil(total_hours)
    carbs_from_iso = iso_bottles * 35
    remaining_carbs = max(0, (total_hours * carbs_per_hour) - carbs_from_iso)
    standard_gels = math.ceil((remaining_carbs / 2.0) / 30.0)
    hydro_bars = math.ceil((remaining_carbs / 2.0) / 40.0)

    c_list1, c_list2, c_list3 = st.columns(3)
    c_list1.info(f"🥤 {iso_bottles}x Iso-Portionsbeutel (à 35g KH)")
    c_list2.info(f"🧪 {standard_gels}x Standard-Gels (à 30g KH)")
    c_list3.info(f"🥮 {hydro_bars}x Sportriegel / Hydro-Gels (à 40g KH)")

    # ==========================================
    # 6. DOWNLOAD BUTTONS
    # ==========================================
    st.subheader("💾 Workout-Exporte")

    # Zwift Export triggern
    optimizer.export_to_zwift(df_intervals, "app_workout.zwo")
    with open("app_workout.zwo", "r", encoding="utf-8") as f:
        zwo_data = f.read()

    st.download_button(
        label="📥 Zwift-Workout (.zwo) herunterladen",
        data=zwo_data,
        file_name="oetztaler_pacing_plan.zwo",
        mime="application/xml"
    )

except Exception as e:
    st.error(f"Fehler bei der Berechnung. Bitte überprüfe die GPX-Datei. Details: {e}")
