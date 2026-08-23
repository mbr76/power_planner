import os
import math
import numpy as np
import pandas as pd
import gpxpy
import xml.etree.ElementTree as ET
from xml.dom import minidom

class AdvancedPacingOptimizer:
    def __init__(self, initial_ftp=300, w_prime_max=20000, target_factor=0.82, 
                 min_duration_sec=300, carb_intake_per_hour=90,
                 rider_weight=75.0, bike_weight=8.5, cda=0.32):
        """
        Initialisiert den physikalisch erweiterten Pacing- und Ernährungsplaner.
        """
        self.initial_ftp = initial_ftp
        self.w_prime_max = w_prime_max
        self.target_factor = target_factor
        self.min_duration_sec = min_duration_sec
        self.carb_intake_per_hour = carb_intake_per_hour
        
        # Neue physikalische Parameter
        self.rider_weight = rider_weight
        self.bike_weight = bike_weight
        self.total_mass = rider_weight + bike_weight
        self.cda = cda               # Luftwiderstandsfläche (Aero-Wert)
        self.crr = 0.004             # Rollwiderstandskoeffizient (gute Rennradreifen)
        self.rho = 1.2               # Luftdichte (Schnitt auf Meereshöhe/Mittelgebirge)
        self.loss_dt = 0.03          # 3% Antriebsverlust (Kette, Schaltung)

    def _solve_velocity(self, target_watt, slope_pct):
        """
        Berechnet die physikalisch exakte Geschwindigkeit (v in m/s) für eine 
        gegebene Leistung und Steigung mittels numerischer Annäherung (Newton-Verfahren).
        """
        s = slope_pct / 100.0
        g = 9.81
        
        # Verfügbare Leistung am Hinterrad nach Antriebsverlusten
        p_wheel = target_watt * (1.0 - self.loss_dt)
        
        # Konstante Kräfte (Gravitation + Rollwiderstand)
        f_constant = (self.total_mass * g * s) + (self.total_mass * g * self.crr)
        
        # Wenn es zu steil bergab geht, rollt man von alleine
        if f_constant < 0 and p_wheel == 0:
            # Vereinfachte Terminal-Geschwindigkeit bergab
            v = math.sqrt(abs(f_constant) / (0.5 * self.cda * self.rho))
            return min(v, 18.0) # Deckelung bei ca. 65 km/h aus Sicherheitsgründen
            
        # Numerische Lösung der kubischen Gleichung: P = F_constant * v + 0.5 * cda * rho * v^3
        v = 5.0 # Startwert für die Iteration (18 km/h)
        for _ in range(10):
            f_v = (0.5 * self.cda * self.rho * (v**3)) + (f_constant * v) - p_wheel
            f_prime_v = (1.5 * self.cda * self.rho * (v**2)) + f_constant
            if f_prime_v == 0: break
            v_next = v - f_v / f_prime_v
            if abs(v_next - v) < 0.01:
                v = v_next
                break
            v = v_next
            
        # Sicherheitsgrenzen für die Realität einhalten
        return min(max(v, 1.66), 18.0) # Zwischen 6 km/h and 65 km/h

    def parse_gpx(self, gpx_file_path):
        """
        Liest eine GPX-Datei ein, berechnet Distanzen und glättet das Höhenprofil.
        """
        if not os.path.exists(gpx_file_path):
            print(f"Datei {gpx_file_path} nicht gefunden. Starte stattdessen Test-Simulation...")
            return self._generate_synthetic_oetztaler()
            
        with open(gpx_file_path, 'r') as f:
            gpx = gpxpy.parse(f)
            
        points_data = []
        cumulative_dist = 0.0
        
        for track in gpx.tracks:
            for segment in track.segments:
                for i, point in enumerate(segment.points):
                    if i == 0:
                        prev_point = point
                        continue
                        
                    d_lat = math.radians(point.latitude - prev_point.latitude)
                    d_lon = math.radians(point.longitude - prev_point.longitude)
                    a = (math.sin(d_lat / 2) ** 2 + 
                         math.cos(math.radians(prev_point.latitude)) * 
                         math.cos(math.radians(point.latitude)) * math.sin(d_lon / 2) ** 2)
                    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    dist_m = 6371000 * c
                    
                    if dist_m <= 0: continue
                    
                    dist_km = dist_m / 1000.0
                    cumulative_dist += dist_km
                    
                    ele_diff = point.elevation - prev_point.elevation if point.elevation and prev_point.elevation else 0
                    slope = (ele_diff / dist_m) * 100
                    
                    points_data.append({
                        'distance_km': cumulative_dist,
                        'segment_len_m': dist_m,
                        'slope': slope,
                        'elevation': point.elevation
                    })
                    prev_point = point
                    
        df = pd.DataFrame(points_data)
        df['slope'] = df['slope'].rolling(window=15, min_periods=1, center=True).mean()
        return df

    def optimize_pacing(self, df_route):
        """
        Berechnet das physikalische Pacing unter Berücksichtigung von W', Glykogen und Systemgewicht.
        """
        total_burned_kcal = 0.0
        w_prime_current = self.w_prime_max
        internal_glycogen_kcal = 2000.0
        kcal_per_gram_carb = 4.1
        
        raw_pacing = []
        
        for idx, row in df_route.iterrows():
            slope = row['slope']
            dist_m = row['segment_len_m']
            
            # 1. FTP-Verfall anhand des Glykogentanks berechnen
            tank_emptiness_pct = 1.0 - (internal_glycogen_kcal / 2000.0)
            fatigue_factor = 1.0 - (0.25 * (tank_emptiness_pct ** 2))
            current_ftp = self.initial_ftp * fatigue_factor
            
            # 2. Leistungs-Soll ermitteln (Gewichtet nach Steigung)
            power_factor = self.target_factor * (1.0 + 0.045 * slope)
            
            w_prime_pct = w_prime_current / self.w_prime_max
            max_allowed_pct = 1.30 if w_prime_pct > 0.20 else 1.00
            power_factor = min(max(power_factor, 0.55), max_allowed_pct)
            
            target_watt = round((power_factor * current_ftp) / 5) * 5
            
            # 3. PHYSIK-UPGRADE: Berechne exakte Dauer für dieses Segment über v
            v_mps = self._solve_velocity(target_watt, slope)
            dt = dist_m / v_mps  # Zeitdauer für dieses Segment in Sekunden
            
            # 4. Kcal-Verbrauch und Nahrungsaufnahme bilanzieren
            intake_kcal = (self.carb_intake_per_hour / 3600.0) * dt * kcal_per_gram_carb
            burned_kcal = (target_watt * dt) / 1000.0
            total_burned_kcal += burned_kcal
            
            internal_glycogen_kcal -= (burned_kcal - intake_kcal)
            internal_glycogen_kcal = max(0.0, min(internal_glycogen_kcal, 2000.0))
            
            # 5. W'-Akku updaten
            if target_watt > current_ftp:
                w_prime_current -= (target_watt - current_ftp) * dt
            else:
                reconstitution = current_ftp - target_watt
                w_prime_current += reconstitution * dt * (1.0 - w_prime_pct)
            w_prime_current = max(0.0, min(w_prime_current, self.w_prime_max))
            
            raw_pacing.append({
                'distance_km': row['distance_km'],
                'target_watt': target_watt,
                'duration_sec': dt,
                'speed_kmh': v_mps * 3.6,
                'w_prime_pct': w_prime_pct * 100
            })
            
        return self._segment_intervals(pd.DataFrame(raw_pacing))

    def _segment_intervals(self, df_raw):
        intervals = []
        current_watt = df_raw.iloc[0]['target_watt'] if not df_raw.empty else 0
        start_km = 0.0
        accumulated_time = 0.0
        
        for idx, row in df_raw.iterrows():
            accumulated_time += row['duration_sec']
            if abs(row['target_watt'] - current_watt) > (self.initial_ftp * 0.08) and accumulated_time >= self.min_duration_sec:
                intervals.append({
                    'start_km': round(start_km, 1),
                    'end_km': round(row['distance_km'], 1),
                    'duration_min': round(accumulated_time / 60.0, 1),
                    'target_watt': int(current_watt),
                    'pct_ftp': round((current_watt / self.initial_ftp) * 100, 1)
                })
                start_km = row['distance_km']
                current_watt = row['target_watt']
                accumulated_time = 0.0
            elif idx == len(df_raw) - 1:
                intervals.append({
                    'start_km': round(start_km, 1),
                    'end_km': round(row['distance_km'], 1),
                    'duration_min': round(accumulated_time / 60.0, 1),
                    'target_watt': int(current_watt),
                    'pct_ftp': round((current_watt / self.initial_ftp) * 100, 1)
                })
                
        return pd.DataFrame(intervals)

    def generate_nutrition_shopping_list(self, df_intervals):
        total_hours = df_intervals['duration_min'].sum() / 60.0
        total_carbs_g = total_hours * self.carb_intake_per_hour
        total_kcal = total_carbs_g * 4.1
        
        iso_bottles = math.ceil(total_hours)
        carbs_from_iso = iso_bottles * 35
        remaining_carbs = max(0, total_carbs_g - carbs_from_iso)
        
        standard_gels = math.ceil((remaining_carbs / 2.0) / 30.0)
        hydro_bars = math.ceil((remaining_carbs / 2.0) / 40.0)
        
        print("\n" + "="*80)
        print(f"          SPORTSNAHRUNG-EINKAUFSLISTE (SYSTEMGEWICHT: {self.total_mass} KG)")
        print("="*80)
        print(f"Berechnete Gesamtfahrzeit:  {math.floor(total_hours):02d}:{round((total_hours%1)*60):02d} Stunden")
        print(f"Geplante Kohlenhydratrate:  {self.carb_intake_per_hour} g / Stunde")
        print(f"Gesamtbedarf Kohlenhydrate: {round(total_carbs_g, 1)} Gramm (ca. {round(total_kcal)} kcal)")
        print("\nEmpfohlene Packliste für das Rennen:")
        print(f" 🥤 {iso_bottles}x Portionsbeutel Iso-Pulver (à 35g KH für je 500ml Wasser)")
        print(f" 🧪 {standard_gels}x Standard-Gel (à 30g KH)")
        print(f" 🥮 {hydro_bars}x Hydro-Gel oder Sportriegel (à 40g KH)")
        print("="*80 + "\n")

    def _generate_synthetic_oetztaler(self):
        segments = [
            {'length_km': 31.5, 'slope': -0.5}, {'length_km': 18.0, 'slope': 7.5},
            {'length_km': 35.0, 'slope': -4.5}, {'length_km': 37.5, 'slope': 2.2},
            {'length_km': 14.5, 'slope': -3.0}, {'length_km': 15.5, 'slope': 7.3},
            {'length_km': 20.0, 'slope': -6.0}, {'length_km': 29.0, 'slope': 6.2},
            {'length_km': 26.0, 'slope': -4.0}
        ]
        points_data = []
        cumulative_dist = 0.0
        for seg in segments:
            steps = int(seg['length_km'] * 4)
            dist_step = (seg['length_km'] / steps) * 1000.0
            for _ in range(steps):
                cumulative_dist += (dist_step / 1000.0)
                points_data.append({
                    'distance_km': cumulative_dist,
                    'segment_len_m': dist_step,
                    'slope': seg['slope'] + np.random.normal(0, 0.2)
                })
        return pd.DataFrame(points_data)

if __name__ == "__main__":
    optimizer = AdvancedPacingOptimizer(
        initial_ftp=300, w_prime_max=20000, target_factor=0.82,
        rider_weight=72.0, bike_weight=8.0
    )
    df_route = optimizer.parse_gpx("oetztaler_route.gpx")
    df_intervals = optimizer.optimize_pacing(df_route)
    optimizer.generate_nutrition_shopping_list(df_intervals)
