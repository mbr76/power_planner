import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import math
import json
from pacing_optimizer import AdvancedPacingOptimizer

# Seitenkonfiguration für den Power-Planner
st.set_page_config(page_title="Power-Planner", layout="wide", page_icon="🚴‍♂️")

st.title("🚴‍♂️ Power-Planner — Pacing & Nutrition Strategy")
st.markdown("Physikbasierte Routenplanung gekoppelt mit W'-Akku, Glykogentank und Karoo-Extension Export.")

# Hilfsfunktion für die ISO-Zeitformatierung (hh:mm:ss)
def format_to_iso_duration(minutes):
    total_seconds = int(float(minutes) * 60)
    hours = total_seconds // 3600
    minutes_rem = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes_rem:02d}:{seconds:02d}"
    return f"{minutes_rem:02d}:{seconds:02d}"

# ==========================================
# 1. SEITENLEISTE (EINGABEPARAMETER)
# ==========================================
st.sidebar.header("🔧 Fahrereinstellungen")

initial_ftp = st.sidebar.number_input(
    "Start-FTP (Watt)", min_value=100, max_value=500, value=310, step=5,
    help="Functional Threshold Power: Die maximale Leistung (in Watt), die du theoretisch über eine Stunde konstant halten kannst."
)

w_prime = st.sidebar.slider(
    "W'-Kapazität (Joule)", 10000, 30000, 20000, step=1000,
    help="Dein anaerober 'Akku' in Joule. Jede Sekunde, die du über deiner FTP fährst, leert diesen Tank. Fährst du unter FTP, lädt er sich wieder auf. Typische Werte: 15.000 (Einstieg) bis 25.000+ (Sprinter/Pro)."
)

rider_w = st.sidebar.number_input(
    "Fahrergewicht (kg)", min_value=40.0, max_value=130.0, value=76.0, step=0.5,
    help="Dein nacktes Körpergewicht. Wichtig für die präzise Berechnung des Steigungswiderstands am Berg."
)

bike_w = st.sidebar.number_input(
    "Fahrrad- & Ausrüstungsgewicht (kg)", min_value=5.0, max_value=20.0, value=8.0, step=0.1,
    help="Das Gesamtgewicht deines Fahrrads inklusive gefüllter Trinkflaschen, Bekleidung, Helm, Schuhen und Werkzeug (ca. 8-10 kg)."
)

st.sidebar.header("🍏 Ernährungsstrategie")
carbs_per_hour = st.sidebar.slider(
    "Kohlenhydrate pro Stunde (g)", 20, 120, 90, step=5,
    help="Die Menge an Kohlenhydraten, die du pro Stunde zuführst. Mehr KH verzögern den Glykogen-Abfall und schützen dich vor dem Leistungseinbruch (Hungerast) am letzten Berg. Empfehlung für Marathons: 80-100g/h."
)

st.sidebar.header("🛣️ Routen-Konfiguration")
target_f = st.sidebar.slider(
    "Intensitätsfaktor (Target Factor)", 0.60, 1.00, 0.82, step=0.01,
    help="Der prozentuale Anteil deiner FTP, den du im flachen Gelände als Basis anstrebst. Höhere Werte verringern die Fahrzeit, leeren aber die Speicher schneller."
)

# Visuelle Orientierungsskala für den Target Factor in der Sidebar
if target_f < 0.71:
    st.sidebar.caption("🟢 **Aktuelle Einstufung: Sehr defensiv (Genussfahrt)**")
elif target_f < 0.78:
    st.sidebar.caption("🟢 **Aktuelle Einstufung: Solide Ausdauer Pace**")
elif target_f < 0.84:
    st.sidebar.caption("🟡 **Aktuelle Einstufung: Ambitioniert / Sportlich**")
else:
    st.sidebar.caption("🔴 **Aktuelle Einstufung: Renn-Pace / Elite (Sehr hart)**")

uploaded_file = st.sidebar.file_uploader("GPX-Datei hochladen", type=["gpx"])

# Session State für den Basis-Dateinamen initialisieren
if "base_filename" not in st.session_state:
    st.session_state.base_filename = "oetztaler_route"

gpx_path = "oetztaler_route.gpx"

if uploaded_file is not None:
    with open("temp_route.gpx", "wb") as f:
        f.write(uploaded_file.getbuffer())
    gpx_path = "temp_route.gpx"
    # Basisnamen ohne die .gpx Endung extrahieren und im Session State sichern
    st.session_state.base_filename = os.path.splitext(uploaded_file.name)[0]

# ==========================================
# 2. BERECHNUNG & SCOPE
# ==========================================
optimizer = AdvancedPacingOptimizer(
    initial_ftp=initial_ftp, w_prime_max=w_prime, target_factor=target_f,
    carb_intake_per_hour=carbs_per_hour, rider_weight=rider_w, bike_weight=bike_w
)

try:
    df_route = optimizer.parse_gpx(gpx_path)
    df_raw_pacing = optimizer.generate_raw_pacing_dataframe(df_route)
    df_intervals = optimizer._segment_intervals(df_raw_pacing)

    total_hours = df_raw_pacing['duration_sec'].sum() / 3600.0
    h = math.floor(total_hours)
    m = round((total_hours % 1) * 60)
    sys_weight = rider_w + bike_w

    # Metriken
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Prognostizierte Fahrzeit", f"{h:02d}:{m:02d} Std")
    col2.metric("Systemgewicht Gesamt", f"{sys_weight:.1f} kg")
    col3.metric("Relative FTP", f"{initial_ftp / rider_w:.2f} W/kg")
    col4.metric("Gesamtbedarf KH", f"{total_hours * carbs_per_hour:.1f} g")

    # Map preview
    st.subheader("🗺️ Routen-Vorschau (Geografischer Verlauf)")
    if 'latitude' in df_route.columns and 'longitude' in df_route.columns:
        fig_map = go.Figure(go.Scattermapbox(
            lat=df_route['latitude'], lon=df_route['longitude'],
            mode='lines', line=dict(width=4, color='#FF4B4B'), name="Streckenverlauf"
        ))
        fig_map.update_layout(
            mapbox_style="open-street-map", mapbox_zoom=8.5,
            mapbox_center={"lat": df_route['latitude'].mean(), "lon": df_route['longitude'].mean()},
            margin={"r":0,"t":0,"l":0,"b":0}, height=350
        )
        st.plotly_chart(fig_map, use_container_width=True)

    # Elevation chart
    st.subheader("📊 Höhenprofil & Segment-Leistung")
    fig_elevation = make_subplots(specs=[[{"secondary_y": True}]])
    fig_elevation.add_trace(go.Bar(
        x=df_raw_pacing['distance_km'], y=df_raw_pacing['target_power'], name="Ziel-Leistung (Watt)",
        marker=dict(color=df_raw_pacing['target_power'], colorscale='Turbo'), opacity=0.65
    ), secondary_y=False)
    
    if 'elevation' in df_route.columns and not df_route['elevation'].isna().all():
        y_ele = df_route['elevation']
    else:
        y_ele = (df_route['slope'] * (df_route['segment_len_m'] / 100.0)).cumsum() + 1377
        
    fig_elevation.add_trace(go.Scatter(
        x=df_route['distance_km'], y=y_ele, name="Höhenprofil (m)", line=dict(color="#4A4A4A", width=3)
    ), secondary_y=True)
    fig_elevation.update_layout(
        barmode='overlay',
        xaxis_title="Distanz (km)",
        yaxis=dict(title="Ziel-Leistung (Watt)", range=[0, max(450, int(initial_ftp * 1.4))]),
        yaxis2=dict(title="Höhe über NN (m)")
    )
    st.plotly_chart(fig_elevation, use_container_width=True)

    # Energy chart
    st.subheader("🔋 Energiespeicher & Ermüdungsverlauf")
    fig_energy = go.Figure()
    fig_energy.add_trace(go.Scatter(x=df_raw_pacing['distance_km'], y=df_raw_pacing['w_prime_pct'], name="W'-Akku (Anaerob) %", line=dict(color="#FF4B4B", width=2)))
    fig_energy.add_trace(go.Scatter(x=df_raw_pacing['distance_km'], y=df_raw_pacing['glycogen_pct'], name="Glykogentank (Metabolisch) %", line=dict(color="#00CC96", width=2.5, dash='dash')))
    fig_energy.update_layout(xaxis_title="Distanz (km)", yaxis_title="Speicher-Füllstand (%)", yaxis=dict(range=[0, 105]))
    st.plotly_chart(fig_energy, use_container_width=True)

    # Intervals table
    st.subheader("📋 Berechnete Intervall-Blöcke (Farbcodiert nach Intensitätszonen)")
    df_display = df_intervals.copy()
    df_display['duration_min'] = df_display['duration_min'].apply(format_to_iso_duration)
    df_display.columns = ['Start (km)', 'Ende (km)', 'Dauer (hh:mm:ss)', 'Ziel-Leistung (W)', 'Intensität (% FTP)']

    def style_zones(row):
        pct = row['Intensität (% FTP)']
        if pct < 55: color = '#E5E7EB; color: #374151'
        elif pct < 75: color = '#D1FAE5; color: #065F46'
        elif pct < 90: color = '#FEF3C7; color: #92400E'
        elif pct < 105: color = '#FFEDD5; color: #9A3412'
        elif pct < 120: color = '#FEE2E2; color: #991B1B'
        else: color = '#F3E8FF; color: #6B21A8'
        return [f'background-color: {color}' for _ in row]

    styled_df = df_display.style.format({
        'Start (km)': '{:.2f}',
        'Ende (km)': '{:.2f}',
        'Intensität (% FTP)': '{:.0f}%'
    }).apply(style_zones, axis=1)
    st.dataframe(styled_df, use_container_width=True)

    # Workout exports
    st.subheader("💾 Workout- & Karoo-Exporte")
    
    karoo_json_str = optimizer.export_to_karoo_json(df_route, route_name=st.session_state.base_filename)
    karoo_filename = f"{st.session_state.base_filename}_power_track.json"

    optimizer.export_to_zwift(df_intervals, "app_workout.zwo")
    with open("app_workout.zwo", "r", encoding="utf-8") as f:
        zwo_data = f.read()
    zwift_filename = f"{st.session_state.base_filename}_workout.zwo"

    optimizer.export_to_garmin_fit(df_intervals, "app_workout.fit")
    with open("app_workout.fit", "r", encoding="utf-8") as f:
        fit_data = f.read()
    garmin_filename = f"{st.session_state.base_filename}_workout.fit"

    btn_col1, btn_col2, btn_col3 = st.columns(3)
    
    with btn_col1:
        st.download_button(
            label=f"📱 Karoo Extension JSON ({karoo_filename})",
            data=karoo_json_str,
            file_name=karoo_filename,
            mime="application/json",
            use_container_width=True
        )

    with btn_col2:
        st.download_button(
            label=f"📥 Zwift-Workout ({zwift_filename})",
            data=zwo_data,
            file_name=zwift_filename,
            mime="application/xml",
            use_container_width=True
        )

    with btn_col3:
        st.download_button(
            label=f"📥 Garmin-Workout ({garmin_filename})",
            data=fit_data,
            file_name=garmin_filename,
            mime="text/plain",
            use_container_width=True
        )

except Exception as e:
    st.error(f"Fehler im Power-Planner Core-Modul. Details: {e}")
