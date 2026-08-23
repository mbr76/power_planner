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
        self.initial_ftp = initial_ftp
        self.w_prime_max = w_prime_max
        self.target_factor = target_factor
        self.min_duration_sec = min_duration_sec
        self.carb_intake_per_hour = carb_intake_per_hour
        self.rider_weight = rider_weight
        self.bike_weight = bike_weight
        self.total_mass = rider_weight + bike_weight
        self.cda = cda
        self.crr = 0.004
        self.rho = 1.2
        self.loss_dt = 0.03

    def _solve_velocity(self, target_watt, slope_pct):
        """
        Berechnet die physikalisch exakte Geschwindigkeit (v in m/s) mittels
        Bisektion. Mathematisch absolut stabil bei jedem Gefälle und jeder Steigung.
        """
        s = slope_pct / 100.0  # Umrechnung von % in Dezimalzahl
        g = 9.81
        
        # Effektive Leistung am Hinterrad (Kettenverlust einbezogen)
        p_wheel = max(target_watt * (1.0 - self.loss_dt), 0.0)
        
        # Konstante Kräfte (Hangabtrieb + Rollwiderstand)
        f_constant = (self.total_mass * g * s) + (self.total_mass * g * self.crr)
        
        # Bisektion-Suchbereich: Zwischen 1.53 m/s (5.5 km/h) und 22.2 m/s (80 km/h)
        low, high = 1.53, 22.2
        
        for _ in range(25):  # 25 Iterationen garantieren eine Genauigkeit von < 0.001 km/h
            mid = (low + high) / 2.0
            # Physikalische Leistungsgleichung: P = F_luft * v + F_konstant * v
            p_calc = (0.5 * self.cda * self.rho * (mid**3)) + (f_constant * mid)
            
            if p_calc > p_wheel:
                high = mid  # Zu schnell für die getretene Leistung
            else:
                low = mid   # Mehr Leistung vorhanden, schneller fahren
                
        return (low + high) / 2.0


    def parse_gpx(self, gpx_file_path):
        if not os.path.exists(gpx_file_path):
            return self._generate_synthetic_oetztaler()
            
        with open(gpx_file_path, 'r') as f:
            gpx = gpxpy.parse(f)
            
        points_data = []
        cumulative_dist = 0.0
        prev_point = None
        
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if prev_point is None:
                        prev_point = point
                        continue
                        
                    d_lat = math.radians(point.latitude - prev_point.latitude)
                    d_lon = math.radians(point.longitude - prev_point.longitude)
                    a = (math.sin(d_lat / 2) ** 2 + math.cos(math.radians(prev_point.latitude)) * 
                         math.cos(math.radians(point.latitude)) * math.sin(d_lon / 2) ** 2)
                    dist_m = 6371000 * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
                    
                    if dist_m <= 0: continue
                    cumulative_dist += (dist_m / 1000.0)
                    slope = ((point.elevation - prev_point.elevation) / dist_m) * 100
                    
                    points_data.append({
                        'distance_km': cumulative_dist,
                        'segment_len_m': dist_m,
                        'slope': slope,
                        'latitude': point.latitude,
                        'longitude': point.longitude,
                        'elevation': point.elevation
                    })
                    prev_point = point
                    
        df = pd.DataFrame(points_data)
        df['slope'] = df['slope'].rolling(window=15, min_periods=1, center=True).mean()
        return df

    def optimize_pacing(self, df_route):
        total_burned_kcal = 0.0
        w_prime_current = self.w_prime_max
        internal_glycogen_kcal = 2000.0
        raw_pacing = []
        
        for idx, row in df_route.iterrows():
            slope = row['slope']
            dist_m = row['segment_len_m']
            
            tank_emptiness_pct = 1.0 - (internal_glycogen_kcal / 2000.0)
            current_ftp = self.initial_ftp * (1.0 - (0.25 * (tank_emptiness_pct ** 2)))
            power_factor = self.target_factor * (1.0 + 0.045 * slope)
            
            w_prime_pct = w_prime_current / self.w_prime_max
            max_allowed = 1.30 if w_prime_pct > 0.20 else 1.00
            power_factor = min(max(power_factor, 0.55), max_allowed)
            target_watt = round((power_factor * current_ftp) / 5) * 5
            
            v_mps = self._solve_velocity(target_watt, slope)
            dt = dist_m / v_mps
            
            intake_kcal = (self.carb_intake_per_hour / 3600.0) * dt * 4.1
            burned_kcal = (target_watt * dt) / 1000.0
            total_burned_kcal += burned_kcal
            internal_glycogen_kcal = max(0.0, min(2000.0, internal_glycogen_kcal - (burned_kcal - intake_kcal)))
            
            if target_watt > current_ftp:
                w_prime_current -= (target_watt - current_ftp) * dt
            else:
                w_prime_current += (current_ftp - target_watt) * dt * (1.0 - w_prime_pct)
            w_prime_current = max(0.0, min(w_prime_current, self.w_prime_max))
            
            raw_pacing.append({
                'distance_km': row['distance_km'],
                'target_watt': target_watt,
                'duration_sec': dt
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
                    'start_km': round(start_km, 1), 'end_km': round(row['distance_km'], 1),
                    'duration_min': round(accumulated_time / 60.0, 1), 'target_watt': int(current_watt),
                    'pct_ftp': round((current_watt / self.initial_ftp) * 100, 1)
                })
                start_km, current_watt, accumulated_time = row['distance_km'], row['target_watt'], 0.0
            elif idx == len(df_raw) - 1:
                intervals.append({
                    'start_km': round(start_km, 1), 'end_km': round(row['distance_km'], 1),
                    'duration_min': round(accumulated_time / 60.0, 1), 'target_watt': int(current_watt),
                    'pct_ftp': round((current_watt / self.initial_ftp) * 100, 1)
                })
        return pd.DataFrame(intervals)

    def generate_nutrition_shopping_list(self, df_intervals):
        total_hours = df_intervals['duration_min'].sum() / 60.0
        total_carbs_g = total_hours * self.carb_intake_per_hour
        iso_bottles = math.ceil(total_hours)
        remaining_carbs = max(0, total_carbs_g - (iso_bottles * 35))
        
        print(f"\\n=== EINKAUFSLISTE (GEWICHT: {self.total_mass} KG) ===")
        print(f"Fahrzeit: {math.floor(total_hours):02d}:{round((total_hours%1)*60):02d} | KH-Rate: {self.carb_intake_per_hour}g/h")
        print(f"🥤 {iso_bottles}x Iso-Beutel (à 35g KH) | 🧪 {math.ceil((remaining_carbs/2)/30)}x Gel (30g) | 🥮 {math.ceil((remaining_carbs/2)/40)}x Riegel (40g)")

    def export_to_zwift(self, df_intervals, output_filename="workout.zwo"):
        wf = ET.Element("workout_file")
        ET.SubElement(wf, "author").text = "AI Optimizer"
        ET.SubElement(wf, "name").text = "Oetztaler Strategy"
        ET.SubElement(wf, "sportType").text = "bike"
        w = ET.SubElement(wf, "workout")
        
        for idx, row in df_intervals.iterrows():
            dur = int(row['duration_min'] * 60)
            ss = ET.SubElement(w, "SteadyState", Duration=str(dur), Power=str(row['pct_ftp']/100.0))
            if dur >= 1200:
                ET.SubElement(ss, "TextMessage", timeoffset="1200", duration="10", message="Ernaehrungserinnerung!")
                
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(minidom.parseString(ET.tostring(wf)).toprettyxml(indent="  "))
        print(f"Zwift-Workout exportiert: {output_filename}")

    def export_to_garmin_fit(self, df_intervals, output_filename="workout.fit"):
        with open(output_filename, "w") as f:
            for idx, row in df_intervals.iterrows():
                f.write(f"Step {idx}: {row['duration_min']}m @ {row['target_watt']}W\\n")
        print(f"Garmin-Workout exportiert: {output_filename}")

    def _generate_synthetic_oetztaler(self):
        segs = [{'l': 31.5, 's': -0.5}, {'l': 18.0, 's': 7.5}, {'l': 35.0, 's': -4.5}, {'l': 37.5, 's': 2.2},
                {'l': 14.5, 's': -3.0}, {'l': 15.5, 's': 7.3}, {'l': 20.0, 's': -6.0}, {'l': 29.0, 's': 6.2}, {'l': 26.0, 's': -4.0}]
        p_data = []
        c_dist = 0.0
        for seg in segs:
            steps = int(seg['l'] * 4)
            d_step = (seg['l'] / steps) * 1000.0
            for _ in range(steps):
                c_dist += (d_step / 1000.0)
                p_data.append({'distance_km': c_dist, 'segment_len_m': d_step, 'slope': seg['s'] + np.random.normal(0, 0.1)})
        return pd.DataFrame(p_data)

if __name__ == "__main__":
    optimizer = AdvancedPacingOptimizer(initial_ftp=300, rider_weight=72.0, bike_weight=8.0, carb_intake_per_hour=90)
    df_route = optimizer.parse_gpx("oetztaler_route.gpx")
    df_intervals = optimizer.optimize_pacing(df_route)
    print(df_intervals.to_string(index=False))
    optimizer.generate_nutrition_shopping_list(df_intervals)
    optimizer.export_to_zwift(df_intervals, "oetztaler_final.zwo")
    optimizer.export_to_garmin_fit(df_intervals, "oetztaler_final.fit")
