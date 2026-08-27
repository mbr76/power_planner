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
    help="Functional Threshold Power: Die maximale Leistung (in Watt), die du theoretisch über eine Stunde konstant halten kannst. Basis für alle aeroben Berechnungen."
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
        
        raw_points.append({
            'distance_km': row['distance_km'], 'slope': slope, 'target_watt': target_watt, 'duration_sec': dt,
            'w_prime_pct': w_prime_pct * 100, 'glycogen_pct': (internal_glycogen_kcal / 2000.0) * 100
        })
        
    df_raw_pacing = pd.DataFrame(raw_points)
    df_intervals = optimizer.optimize_pacing(df_route)

    total_hours = df_intervals['duration_min'].sum() / 60.0
    h = math.floor(total_hours)
    m = round((total_hours % 1) * 60)
    sys_weight = rider_w + bike_w

    # Metriken
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Prognostizierte Fahrzeit", f"{h:02d}:{m:02d} Std")
    col2.metric("Systemgewicht Gesamt", f"{sys_weight:.1f} kg")
    col3.metric("Relative FTP", f"{initial_ftp / rider_w:.2f} W/kg")
    col4.metric("Gesamtbedarf KH", f"{total_hours * carbs_per_hour:.1f} g")

    # FEATURE 3: GEOGRAFISCHE MAP VORSCHAU
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

    # FEATURE 2: ELEVATION BARS VS POWER LINE
    st.subheader("📊 Höhenprofil & Segment-Leistung")
    fig_elevation = make_subplots(specs=[[{"secondary_y": True}]])
    fig_elevation.add_trace(go.Bar(
        x=df_raw_pacing['distance_km'], y=df_raw_pacing['target_watt'], name="Ziel-Leistung (Watt)",
        marker=dict(color=df_raw_pacing['target_watt'], colorscale='Turbo'), opacity=0.65
    ), secondary_y=False)
    
    if 'elevation' in df_route.columns and not df_route['elevation'].isna().all():
        y_ele = df_route['elevation']
    else:
        y_ele = (df_route['slope'] * (df_route['segment_len_m'] / 100.0)).cumsum() + 1377
        
    fig_elevation.add_trace(go.Scatter(
        x=df_route['distance_km'], y=y_ele, name="Höhenprofil (m)", line=dict(color="#4A4A4A", width=3)
    ), secondary_y=True)
    st.plotly_chart(fig_elevation, use_container_width=True)

    # FEATURE 1: W' AND GLYCOGEN FATIGUE CHART
    st.subheader("🔋 Energiespeicher & Ermüdungsverlauf")
    fig_energy = go.Figure()
    fig_energy.add_trace(go.Scatter(x=df_raw_pacing['distance_km'], y=df_raw_pacing['w_prime_pct'], name="W'-Akku (Anaerob) %", line=dict(color="#FF4B4B", width=2)))
    fig_energy.add_trace(go.Scatter(x=df_raw_pacing['distance_km'], y=df_raw_pacing['glycogen_pct'], name="Glykogentank (Metabolisch) %", line=dict(color="#00CC96", width=2.5, dash='dash')))
    fig_energy.update_layout(xaxis_title="Distanz (km)", yaxis_title="Speicher-Füllstand (%)", yaxis=dict(range=[0, 105]))
    st.plotly_chart(fig_energy, use_container_width=True)

    # ==========================================
    # 3. INTERVALL-TABELLE MIT FORMATIERUNG (KILOMETER, PROZENT, ISO-ZEIT)
    # ==========================================
    st.subheader("📋 Berechnete Intervall-Blöcke (Farbcodiert nach Intensitätszonen)")

    # Vorbereitung der Formatierung: Zeit-Minuten in ISO-Strings umwandeln
    df_display = df_intervals.copy()
    df_display['duration_min'] = df_display['duration_min'].apply(format_to_iso_duration)

    # Spalten umbenennen, damit es in der Tabelle gut aussieht
    df_display.columns = ['Start (km)', 'Ende (km)', 'Dauer (hh:mm:ss)', 'Ziel-Leistung (W)', 'Intensität (% FTP)']

    def style_zones(row):
        # Wir greifen auf den numerischen Wert der Intensität zu
        pct = row['Intensität (% FTP)']
        if pct < 55: color = '#E5E7EB; color: #374151'
        elif pct < 75: color = '#D1FAE5; color: #065F46'
        elif pct < 90: color = '#FEF3C7; color: #92400E'
        elif pct < 105: color = '#FFEDD5; color: #9A3412'
        elif pct < 120: color = '#FEE2E2; color: #991B1B'
        else: color = '#F3E8FF; color: #6B21A8'
        return [f'background-color: {color}' for _ in row]

    # Formatierungs-Dictionary für Kilometer (2 Dezimalstellen) und Intensität (Ganzzahl + %)
    styled_df = df_display.style.format({
        'Start (km)': '{:.2f}',
        'Ende (km)': '{:.2f}',
        'Intensität (% FTP)': '{:.0f}%'
    }).apply(style_zones, axis=1)
    
    st.dataframe(styled_df, use_container_width=True)

    # Logistik (Einkaufsliste)
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
    # 6. DOWNLOAD BUTTONS (DYNAMISCHE DATEINAMEN)
    # ==========================================
    st.subheader("💾 Workout-Exporte")
    
    # 1. Zwift Export vorbereiten
    optimizer.export_to_zwift(df_intervals, "app_workout.zwo")
    with open("app_workout.zwo", "r", encoding="utf-8") as f:
        zwo_data = f.read()
        
    zwift_filename = f"{st.session_state.base_filename}_workout.zwo"
    
    # 2. Garmin Export vorbereiten
    optimizer.export_to_garmin_fit(df_intervals, "app_workout.fit")
    with open("app_workout.fit", "r", encoding="utf-8") as f:
        fit_data = f.read()
        
    garmin_filename = f"{st.session_state.base_filename}_workout.fit"
    
    # Buttons nebeneinander platzieren
    btn_col1, btn_col2 = st.columns(2)
    
    with btn_col1:
        st.download_button(
            label=f"📥 Zwift-Workout ({zwift_filename})", data=zwo_data,
            file_name=zwift_filename, mime="application/xml",
            use_container_width=True
        )
        
    with btn_col2:
        st.download_button(
            label=f"📥 Garmin-Workout ({garmin_filename})", data=fit_data,
            file_name=garmin_filename, mime="text/plain",
            use_container_width=True
        )


except Exception as e:
    st.error(f"Fehler im Power-Planner Core-Modul. Details: {e}")