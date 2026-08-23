import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import math
from pacing_optimizer import AdvancedPacingOptimizer

# Seitenkonfiguration für den Power-Planner
st.set_page_config(page_title="Power-Planner", layout="wide", page_icon="🚴‍♂️")

st.title("🚴‍♂️ Power-Planner — Pacing & Nutrition Strategy")
st.markdown("Physikbasierte Routenplanung gekoppelt mit W'-Akku, Glykogentank und Fahrzeitprognose.")

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

uploaded_file = st.sidebar.file_uploader("GPX-Datei hochladen", type=["gpx"])
gpx_path = "oetztaler_route.gpx"

if uploaded_file is not None:
    with open("temp_route.gpx", "wb") as f:
        f.write(uploaded_file.getbuffer())
    gpx_path = "temp_route.gpx"

# ==========================================
# 2. BERECHNUNG & INTELLIGENTE SCHLEIFE
# ==========================================
optimizer = AdvancedPacingOptimizer(
    initial_ftp=initial_ftp,
    w_prime_max=w_prime,
    target_factor=target_f,
    carb_intake_per_hour=carbs_per_hour,
    rider_weight=rider_w,
    bike_weight=bike_w
)

try:
    # Route über den Parser der pacing_optimizer.py einlesen
    df_route = optimizer.parse_gpx(gpx_path)
    
    # Sekunden- und Segmentdaten für die interaktiven Dashboard-Charts generieren
    total_burned_kcal = 0.0
    w_prime_current = w_prime
    internal_glycogen_kcal = 2000.0
    raw_points = []
    
    for idx, row in df_route.iterrows():
        slope = row['slope']
        dist_m = row['segment_len_m']
        
        tank_emptiness_pct = 1.0 - (internal_glycogen_kcal / 2000.0)
        current_ftp = initial_ftp * (1.0 - (0.25 * (tank_emptiness_pct ** 2)))
        power_factor = target_f * (1.0 + 0.045 * slope)
        
        w_prime_pct = w_prime_current / w_prime
        max_allowed = 1.30 if w_prime_pct > 0.20 else 1.00
        power_factor = min(max(power_factor, 0.55), max_allowed)
        target_watt = round((power_factor * current_ftp) / 5) * 5
        
        v_mps = optimizer._solve_velocity(target_watt, slope)
        dt = dist_m / v_mps
        
        intake_kcal = (carbs_per_hour / 3600.0) * dt * 4.1
        burned_kcal = (target_watt * dt) / 1000.0
        total_burned_kcal += burned_kcal
        internal_glycogen_kcal = max(0.0, min(2000.0, internal_glycogen_kcal - (burned_kcal - intake_kcal)))
        
        if target_watt > current_ftp:
            w_prime_current -= (target_watt - current_ftp) * dt
        else:
            w_prime_current += (current_ftp - target_watt) * dt * (1.0 - w_prime_pct)
        w_prime_current = max(0.0, min(w_prime_current, w_prime))
        
        # HIER WURDE NUN 'duration_sec' ERGÄNZT
        raw_points.append({
            'distance_km': row['distance_km'],
            'slope': slope,
            'target_watt': target_watt,
            'duration_sec': dt,
            'w_prime_pct': w_prime_pct * 100,
            'glycogen_pct': (internal_glycogen_kcal / 2000.0) * 100
        })
        
    df_raw_pacing = pd.DataFrame(raw_points)
    
    # Saubere Intervalle über das Core-Skript aggregieren
    df_intervals = optimizer.optimize_pacing(df_route)

    # Zeiten und Kennzahlen kalkulieren
    total_hours = df_intervals['duration_min'].sum() / 60.0
    h = math.floor(total_hours)
    m = round((total_hours % 1) * 60)
    sys_weight = rider_w + bike_w

    # ==========================================
    # 3. DASHBOARD METRIKEN
    # ==========================================
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Prognostizierte Fahrzeit", f"{h:02d}:{m:02d} Std")
    col2.metric("Systemgewicht Gesamt", f"{sys_weight:.1f} kg")
    col3.metric("Relative FTP", f"{initial_ftp / rider_w:.2f} W/kg")
    col4.metric("Gesamtbedarf KH", f"{total_hours * carbs_per_hour:.1f} g")

    # ==========================================
    # FEATURE 3: REALISTISCHE GPX-KARTEN VORSCHAU
    # ==========================================
    st.subheader("🗺️ Routen-Vorschau (Geografischer Verlauf)")
    
    # Prüfen, ob Koordinaten in der GPX-Datei vorhanden sind
    if 'latitude' in df_route.columns and 'longitude' in df_route.columns:
        fig_map = go.Figure(go.Scattermapbox(
            lat=df_route['latitude'],
            lon=df_route['longitude'],
            mode='lines',
            line=dict(width=4, color='#FF4B4B'),
            name="Streckenverlauf"
        ))
        
        # Karte zentrieren basierend auf den Streckendaten
        center_lat = df_route['latitude'].mean()
        center_lon = df_route['longitude'].mean()
        
        fig_map.update_layout(
            mapbox_style="open-street-map", # Kostenlose, interaktive Karte
            mapbox_zoom=8.5,
            mapbox_center={"lat": center_lat, "lon": center_lon},
            margin={"r":0,"t":0,"l":0,"b":0},
            height=400
        )
        st.plotly_chart(fig_map, use_container_width=True)
    else:
        # Falls synthetische Testdaten geladen sind, zeigen wir einen schicken Hinweis
        st.info("ℹ️ Für die künstliche Ötztaler-Testsimulation sind keine GPS-Koordinaten hinterlegt. Sobald du eine echte GPX-Datei hochlädst, erscheint hier die interaktive Landkarte.")


    # ==========================================
    # FEATURE 2: ELEVATION BARS VS POWER LINE
    # ==========================================
    st.subheader("📊 Höhenprofil & Segment-Leistung")
    
    fig_elevation = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig_elevation.add_trace(
        go.Bar(
            x=df_raw_pacing['distance_km'], 
            y=df_raw_pacing['target_watt'],
            name="Ziel-Leistung (Watt)",
            marker=dict(color=df_raw_pacing['target_watt'], colorscale='Turbo'),
            opacity=0.65
        ),
        secondary_y=False
    )
    
    if 'elevation' in df_route.columns and not df_route['elevation'].isna().all():
        y_ele = df_route['elevation']
    else:
        y_ele = (df_route['slope'] * (df_route['segment_len_m'] / 100.0)).cumsum() + 1377
        
    fig_elevation.add_trace(
        go.Scatter(
            x=df_route['distance_km'], 
            y=y_ele,
            name="Höhenprofil (m)",
            line=dict(color="#4A4A4A", width=3)
        ),
        secondary_y=True
    )
    
    fig_elevation.update_xaxes(title_text="Distanz (km)")
    fig_elevation.update_yaxes(title_text="Leistung (Watt)", secondary_y=False)
    fig_elevation.update_yaxes(title_text="Höhe über NN (m)", secondary_y=True)
    st.plotly_chart(fig_elevation, use_container_width=True)

    # ==========================================
    # FEATURE 1: W' AND GLYCOGEN FATIGUE CHART
    # ==========================================
    st.subheader("🔋 Energiespeicher & Ermüdungsverlauf")
    
    fig_energy = go.Figure()
    fig_energy.add_trace(go.Scatter(
        x=df_raw_pacing['distance_km'], 
        y=df_raw_pacing['w_prime_pct'],
        name="W'-Akku (Anaerob) %",
        line=dict(color="#FF4B4B", width=2)
    ))
    fig_energy.add_trace(go.Scatter(
        x=df_raw_pacing['distance_km'], 
        y=df_raw_pacing['glycogen_pct'],
        name="Glykogentank (Metabolisch) %",
        line=dict(color="#00CC96", width=2.5, dash='dash')
    ))
    # FEHLER BEHOBEN: range=[0, 100] komplettiert
    fig_energy.update_layout(xaxis_title="Distanz (km)", yaxis_title="Speicher-Füllstand (%)", yaxis=dict(range=[0, 105]))
    st.plotly_chart(fig_energy, use_container_width=True)

    # ==========================================
    # 5. TABELLE & LOGISTIK (EINKAUFSLISTE)
    # ==========================================
    st.subheader("📋 Berechnete Intervall-Blöcke")
    st.dataframe(df_intervals, use_container_width=True)

    st.subheader("🛒 Deine Sportnahrungs-Einkaufsliste")
    iso_bottles = math.ceil(total_hours)
    remaining_carbs = max(0, (total_hours * carbs_per_hour) - (iso_bottles * 35))
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
    optimizer.export_to_zwift(df_intervals, "app_workout.zwo")
    with open("app_workout.zwo", "r", encoding="utf-8") as f:
        zwo_data = f.read()
        
    st.download_button(
        label="📥 Zwift-Workout (.zwo) herunterladen",
        data=zwo_data,
        file_name="power_planner_workout.zwo",
        mime="application/xml"
    )

except Exception as e:
    st.error(f"Fehler im Power-Planner Core-Modul. Details: {e}")
