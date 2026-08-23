import os
import math
import numpy as np
import pandas as pd
import gpxpy
import xml.etree.ElementTree as ET
from xml.dom import minidom

class AdvancedPacingOptimizer:
    def __init__(self, initial_ftp=300, w_prime_max=20000, target_factor=0.82, 
                 min_duration_sec=300, carb_intake_per_hour=90):
        self.initial_ftp = initial_ftp
        self.w_prime_max = w_prime_max
        self.target_factor = target_factor
        self.min_duration_sec = min_duration_sec
        self.carb_intake_per_hour = carb_intake_per_hour
        
    def parse_gpx(self, gpx_file_path):
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
                    
                    dist_km = dist_m / 1000.0
                    cumulative_dist += dist_km
                    
                    ele_diff = point.elevation - prev_point.elevation if point.elevation and prev_point.elevation else 0
                    slope = (ele_diff / dist_m) * 100 if dist_m > 0 else 0
                    
                    if slope > 0:
                        speed_kmh = max(6.0, 30.0 - (slope * 2.2))
                    else:
                        speed_kmh = min(65.0, 30.0 - (slope * 1.5))
                        
                    duration_sec = (dist_km / speed_kmh) * 3600
                    
                    points_data.append({
                        'distance_km': cumulative_dist,
                        'slope': slope,
                        'duration_sec': duration_sec,
                        'elevation': point.elevation
                    })
                    prev_point = point
                    
        df = pd.DataFrame(points_data)
        df['slope'] = df['slope'].rolling(window=20, min_periods=1, center=True).mean()
        return df

    def optimize_pacing(self, df_route):
        total_burned_kcal = 0.0
        w_prime_current = self.w_prime_max
        internal_glycogen_kcal = 2000.0
        kcal_per_gram_carb = 4.1
        
        raw_pacing = []
        
        for idx, row in df_route.iterrows():
            dt = row['duration_sec']
            slope = row['slope']
            
            intake_kcal = (self.carb_intake_per_hour / 3600.0) * dt * kcal_per_gram_carb
            temp_factor = self.target_factor * (1.0 + 0.04 * slope)
            temp_watt = self.initial_ftp * temp_factor
            
            burned_kcal = (temp_watt * dt) / 1000.0
            total_burned_kcal += burned_kcal
            
            internal_glycogen_kcal -= (burned_kcal - intake_kcal)
            internal_glycogen_kcal = max(0.0, min(internal_glycogen_kcal, 2000.0))
            
            tank_emptiness_pct = 1.0 - (internal_glycogen_kcal / 2000.0)
            fatigue_factor = 1.0 - (0.25 * (tank_emptiness_pct ** 2))
            current_ftp = self.initial_ftp * fatigue_factor
            
            w_prime_pct = w_prime_current / self.w_prime_max
            max_allowed_pct = 1.30 if w_prime_pct > 0.20 else 1.00
            
            power_factor = min(max(temp_factor, 0.55), max_allowed_pct)
            target_watt = round((power_factor * current_ftp) / 5) * 5
            
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
                'w_prime_pct': (w_prime_current / self.w_prime_max) * 100
            })
            
        return self._segment_intervals(pd.DataFrame(raw_pacing))

    def _segment_intervals(self, df_raw):
        intervals = []
        current_watt = df_raw.iloc[0]['target_watt']
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
        
        half_remaining = remaining_carbs / 2.0
        standard_gels = math.ceil(half_remaining / 30.0)
        hydro_bars = math.ceil(half_remaining / 40.0)
        
        print("\n" + "="*80)
        print("          SPORTSNAHRUNG-EINKAUFSLISTE & ERNÄHRUNGSSTRATEGIE")
        print("="*80)
        print(f"Berechnete Gesamtfahrzeit:  {math.floor(total_hours):02d}:{round((total_hours%1)*60):02d} Stunden")
        print(f"Geplante Kohlenhydratrate:  {self.carb_intake_per_hour} g / Stunde")
        print(f"Gesamtbedarf Kohlenhydrate: {round(total_carbs_g, 1)} Gramm (ca. {round(total_kcal)} kcal)")
        print("\nEmpfohlene Packliste für die Trikottaschen:")
        print(f" 🥤 {iso_bottles}x Portionsbeutel Iso-Pulver (à 35g KH für je 500ml Wasser)")
        print(f" 🧪 {standard_gels}x Standard-Gel (à 30g KH)")
        print(f" 🥮 {hydro_bars}x Hydro-Gel oder Sportriegel (à 40g KH)")
        print("\nStrategie-Hinweis:")
        print(f"-> Trinken Sie jede Stunde konstant eine Flasche (500ml) mit dem Iso-Mix.")
        print(f"-> Nehmen Sie zusätzlich alle 20 Minuten abwechselnd ein Gel oder einen Riegel.")
        print("="*80 + "\n")

    def export_to_zwift(self, df_intervals, output_filename="workout.zwo"):
        workout_file = ET.Element("workout_file")
        author = ET.SubElement(workout_file, "author")
        author.text = "AI Pacing Optimizer"
        name = ET.SubElement(workout_file, "name")
        name.text = f"Oetztaler Pacing Strategy ({self.carb_intake_per_hour}g KH/h)"
        description = ET.SubElement(workout_file, "description")
        description.text = "Automatisch generiertes, ermüdungsbasiertes Pacing-Profil."
        ET.SubElement(workout_file, "sportType").text = "bike"
        workout = ET.SubElement(workout_file, "workout")
        carb_per_20min = round(self.carb_intake_per_hour / 3.0)
        
        for idx, row in df_intervals.iterrows():
            duration_sec = int(row['duration_min'] * 60)
            ftp_fraction = row['pct_ftp'] / 100.0
            steady_state = ET.SubElement(workout, "SteadyState", Duration=str(duration_sec), Power=str(ftp_fraction))
            intervals_of_20 = duration_sec // 1200
            for i in range(1, intervals_of_20 + 1):
                offset = i * 1200
                ET.SubElement(steady_state, "TextMessage", timeoffset=str(offset), duration="10", message=f"Ernährungserinnerung: Jetzt {carb_per_20min}g Kohlenhydrate zuführen!")
                
        xml_str = minidom.parseString(ET.tostring(workout_file)).toprettyxml(indent="  ")
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(xml_str)
        print(f"Zwift-Workout erfolgreich exportiert: {output_filename}")

    def export_to_garmin_fit(self, df_intervals, output_filename="workout.fit"):
        with open(output_filename, "w") as f:
            f.write("TARGET_POWER_PLAN_STEPS:\n")
            for idx, row in df_intervals.iterrows():
                f.write(f"Step {idx}: Duration {row['duration_min']}m, Target {row['target_watt']}W\n")
        print(f"Garmin-Workout Steuerungsdatei generiert: {output_filename}")

    def _generate_synthetic_oetztaler(self):
        segments = [
            {'length_km': 31.5, 'slope': -0.5},
            {'length_km': 18.0, 'slope': 7.5},
            {'length_km': 35.0, 'slope': -4.5},
            {'length_km': 37.5, 'slope': 2.2},
            {'length_km': 14.5, 'slope': -3.0},
            {'length_km': 15.5, 'slope': 7.3},
            {'length_km': 20.0, 'slope': -6.0},
            {'length_km': 29.0, 'slope': 6.2},
            {'length_km': 26.0, 'slope': -4.0}
        ]
        points_data = []
        cumulative_dist = 0.0
        for seg in segments:
            steps = int(seg['length_km'] * 2)
            dist_step = seg['length_km'] / steps
            for _ in range(steps):
                cumulative_dist += dist_step
                noisy_slope = seg['slope'] + np.random.normal(0, 0.4)
                if noisy_slope > 0:
                    speed = max(6.0, 30.0 - (noisy_slope * 2.2))
                else:
                    speed = min(65.0, 30.0 - (noisy_slope * 1.5))
                duration_sec = (dist_step / speed) * 3600
                points_data.append({'distance_km': cumulative_dist, 'slope': noisy_slope, 'duration_sec': duration_sec})
        return pd.DataFrame(points_data)

if __name__ == "__main__":
    optimizer = AdvancedPacingOptimizer(initial_ftp=300, w_prime_max=20000, target_factor=0.82, min_duration_sec=300, carb_intake_per_hour=90)
    df_route = optimizer.parse_gpx("oetztaler_route.gpx")
    df_intervals = optimizer.optimize_pacing(df_route)
    print("\n" + "="*80)
    print("                      BERECHNETE LEISTUNGSINTERVALLE")
    print("="*80)
    print(df_intervals.to_string(index=False))
    optimizer.generate_nutrition_shopping_list(df_intervals)
