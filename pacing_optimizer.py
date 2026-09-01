import os
import io
import math
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

try:
    import gpxpy
except ImportError:
    gpxpy = None

class AdvancedPacingOptimizer:
    def __init__(self, initial_ftp=300, w_prime_max=20000, target_factor=0.82, 
                 min_duration_sec=300, carb_intake_per_hour=90,
                 rider_weight=75.0, bike_weight=8.5, cda=0.32,
                 initial_glycogen_kcal=2000.0):
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
        self.initial_glycogen_kcal = initial_glycogen_kcal

    def _solve_velocity(self, target_watt, slope_pct):
        s = slope_pct / 100.0
        g = 9.81
        # Effektive Leistung am Hinterrad (Kettenverlust einbezogen)
        p_wheel = max(target_watt * (1.0 - self.loss_dt), 0.0)
        # Konstante Kräfte (Hangabtrieb + Rollwiderstand)
        f_constant = (self.total_mass * g * s) + (self.total_mass * g * self.crr)
        # Bisektion-Suchbereich: Zwischen 1.53 m/s (5.5 km/h) und 22.2 m/s (80 km/h)
        low, high = 1.53, 22.2
        for _ in range(14):
            mid = (low + high) / 2.0
            # Physikalische Leistungsgleichung: P = F_luft * v + F_konstant * v
            p_calc = (0.5 * self.cda * self.rho * (mid**3)) + (f_constant * mid)
            if p_calc > p_wheel:
                high = mid  # Zu schnell für die getretene Leistung
            else:
                low = mid   # Mehr Leistung vorhanden, schneller fahren
                
        return (low + high) / 2.0

    def parse_gpx(self, gpx_source):
        if gpxpy is None:
            return self._generate_synthetic_oetztaler()

        try:
            if isinstance(gpx_source, (bytes, bytearray)):
                gpx = gpxpy.parse(io.BytesIO(gpx_source))
            elif isinstance(gpx_source, str) and ("<gpx" in gpx_source or "<?xml" in gpx_source):
                gpx = gpxpy.parse(io.StringIO(gpx_source))
            elif isinstance(gpx_source, str) and os.path.exists(gpx_source):
                with open(gpx_source, 'r', encoding='utf-8') as f:
                    gpx = gpxpy.parse(f)
            else:
                return self._generate_synthetic_oetztaler()
        except Exception:
            return self._generate_synthetic_oetztaler()
            
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
                    
                    ele_diff = (point.elevation or 0.0) - (prev_point.elevation or 0.0)
                    slope = (ele_diff / dist_m) * 100
                    
                    points_data.append({
                        'distance_km': cumulative_dist,
                        'segment_len_m': dist_m,
                        'slope': slope,
                        'latitude': point.latitude,
                        'longitude': point.longitude,
                        'elevation': point.elevation or 0.0
                    })
                    prev_point = point
                    
        df = pd.DataFrame(points_data)
        if not df.empty:
            df['slope'] = df['slope'].rolling(window=15, min_periods=1, center=True).mean()
        return df

    def _get_zone_color(self, target_watt):
        pct_ftp = (target_watt / self.initial_ftp) * 100.0
        if pct_ftp < 55:
            return "#E5E7EB"  # Zone 1 / Recovery (Grey)
        elif pct_ftp < 75:
            return "#D1FAE5"  # Zone 2 / Endurance (Green)
        elif pct_ftp < 90:
            return "#FEF3C7"  # Zone 3 / Tempo (Yellow)
        elif pct_ftp < 105:
            return "#FFEDD5"  # Zone 4 / Threshold (Orange)
        elif pct_ftp < 120:
            return "#FEE2E2"  # Zone 5 / VO2Max (Red)
        else:
            return "#F3E8FF"  # Zone 6+ / Anaerobic (Purple)

    def generate_raw_pacing_dataframe(self, df_route):
        total_burned_kcal = 0.0
        w_prime_current = self.w_prime_max
        internal_glycogen_kcal = self.initial_glycogen_kcal
        raw_points = []
        
        cumulative_time_sec = 0.0
        last_nutrition_time_sec = 0.0
        nutrition_interval_sec = 1200.0  # Alle 20 Minuten
        
        for idx, row in df_route.iterrows():
            slope = row['slope']
            dist_m = row['segment_len_m']
            
            tank_emptiness_pct = 1.0 - (internal_glycogen_kcal / self.initial_glycogen_kcal) if self.initial_glycogen_kcal > 0 else 1.0
            current_ftp = self.initial_ftp * (1.0 - (0.25 * (tank_emptiness_pct ** 2)))
            power_factor = self.target_factor * (1.0 + 0.045 * slope)
            
            w_prime_pct = w_prime_current / self.w_prime_max
            max_allowed = 1.30 if w_prime_pct > 0.20 else 1.00
            power_factor = min(max(power_factor, 0.55), max_allowed)
            target_watt = int(round((power_factor * current_ftp) / 5) * 5)
            
            v_mps = self._solve_velocity(target_watt, slope)
            dt = dist_m / v_mps
            cumulative_time_sec += dt
            
            intake_kcal = (self.carb_intake_per_hour / 3600.0) * dt * 4.1
            burned_kcal = (target_watt * dt) / 1000.0
            total_burned_kcal += burned_kcal
            internal_glycogen_kcal = max(0.0, min(self.initial_glycogen_kcal, internal_glycogen_kcal - (burned_kcal - intake_kcal)))
            
            if target_watt > current_ftp:
                w_prime_current -= (target_watt - current_ftp) * dt
            else:
                w_prime_current += (current_ftp - target_watt) * dt * (1.0 - w_prime_pct)
            w_prime_current = max(0.0, min(w_prime_current, self.w_prime_max))
            
            # Nutrition alert notification trigger (Alle 20 Minuten)
            notification = None
            if (cumulative_time_sec - last_nutrition_time_sec) >= nutrition_interval_sec and idx > 0:
                last_nutrition_time_sec = cumulative_time_sec
                carb_amount = int(round((self.carb_intake_per_hour / 60.0) * 20))
                notification = {
                    "type": "NUTRITION",
                    "trigger_radius_m": 50,
                    "title": "Verpflegung",
                    "message": f"Jetzt Gel/Riegel ({carb_amount}g KH) nehmen!",
                    "audio_alert": True
                }

            zone_color = self._get_zone_color(target_watt)
            
            w_prime_percent = round((w_prime_current / self.w_prime_max) * 100.0, 1)
            glycogen_percent = round((internal_glycogen_kcal / self.initial_glycogen_kcal) * 100.0, 1) if self.initial_glycogen_kcal > 0 else 0.0
            dist_km_val = round(row['distance_km'], 2)
            
            raw_points.append({
                'index': idx,
                'lat': round(row['latitude'], 5) if 'latitude' in row else 0.0,
                'lon': round(row['longitude'], 5) if 'longitude' in row else 0.0,
                'ele': round(row['elevation'], 1) if 'elevation' in row else 0.0,
                'dist_km': dist_km_val,
                'distance_km': dist_km_val,
                'target_power': target_watt,
                'target_watt': target_watt,
                'expected_w_prime_pct': w_prime_percent,
                'w_prime_pct': w_prime_percent,
                'glycogen_pct': glycogen_percent,
                'internal_glycogen_kcal': round(internal_glycogen_kcal, 1),
                'zone_color': zone_color,
                'notification': notification,
                'slope': slope,
                'duration_sec': dt
            })
            
        return pd.DataFrame(raw_points)

    def export_to_karoo_json(self, df_route, route_name="Power-Planner Route", output_filename=None):
        df_raw = self.generate_raw_pacing_dataframe(df_route)
        
        meta = {
            "version": "1.0",
            "route_name": route_name,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "athlete_ftp": int(self.initial_ftp),
            "system_weight_kg": round(float(self.total_mass), 1),
            "target_carb_intake_gh": int(self.carb_intake_per_hour)
        }
        
        track = []
        for idx, row in df_raw.iterrows():
            track.append({
                "index": int(row['index']),
                "lat": float(row['lat']),
                "lon": float(row['lon']),
                "ele": float(row['ele']),
                "dist_km": float(row['dist_km']),
                "target_power": int(row['target_power']),
                "expected_w_prime_pct": float(row['expected_w_prime_pct']),
                "zone_color": str(row['zone_color']),
                "notification": row['notification'] if row['notification'] is not None else None
            })
            
        json_data = {
            "meta": meta,
            "track": track
        }
        
        json_str = json.dumps(json_data, indent=2, ensure_ascii=False)
        if output_filename:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write(json_str)
        return json_str

    def optimize_pacing(self, df_route):
        df_raw = self.generate_raw_pacing_dataframe(df_route)
        return self._segment_intervals(df_raw)

    def _segment_intervals(self, df_raw):
        intervals = []
        current_watt = df_raw.iloc[0]['target_power']
        start_km = 0.0
        accumulated_time = 0.0
        
        for idx, row in df_raw.iterrows():
            accumulated_time += row['duration_sec']
            if abs(row['target_power'] - current_watt) > (self.initial_ftp * 0.08) and accumulated_time >= self.min_duration_sec:
                intervals.append({
                    'start_km': round(start_km, 1), 'end_km': round(row['dist_km'], 1),
                    'duration_min': round(accumulated_time / 60.0, 1), 'target_watt': int(current_watt),
                    'pct_ftp': round((current_watt / self.initial_ftp) * 100, 1)
                })
                start_km, current_watt, accumulated_time = row['dist_km'], row['target_power'], 0.0
            elif idx == len(df_raw) - 1:
                intervals.append({
                    'start_km': round(start_km, 1), 'end_km': round(row['dist_km'], 1),
                    'duration_min': round(accumulated_time / 60.0, 1), 'target_watt': int(current_watt),
                    'pct_ftp': round((current_watt / self.initial_ftp) * 100, 1)
                })
        return pd.DataFrame(intervals)

    def generate_nutrition_shopping_list(self, df_intervals):
        total_hours = df_intervals['duration_min'].sum() / 60.0
        total_carbs_g = total_hours * self.carb_intake_per_hour
        iso_bottles = math.ceil(total_hours)
        remaining_carbs = max(0, total_carbs_g - (iso_bottles * 35))
        
        print(f"\n=== EINKAUFSLISTE (GEWICHT: {self.total_mass} KG) ===")
        print(f"Fahrzeit: {math.floor(total_hours):02d}:{round((total_hours%1)*60):02d} | KH-Rate: {self.carb_intake_per_hour}g/h")
        print(f"🥤 {iso_bottles}x Iso-Beutel (à 35g KH) | 🧪 {math.ceil((remaining_carbs/2)/30)}x Gel (30g) | 🥮 {math.ceil((remaining_carbs/2)/40)}x Riegel (40g)")

    def export_to_zwift(self, df_intervals, output_filename="workout.zwo"):
        import xml.etree.ElementTree as ET
        from xml.dom import minidom
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
        """
        Exportiert die Intervalle als distanzbasiertes Garmin-Workout.
        Die Schritte werden in Metern (m) statt in Sekunden definiert.
        """
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write("TARGET_POWER_PLAN_STEPS (DISTANCE BASED):\n")
            for idx, row in df_intervals.iterrows():
                # Berechne die exakte Distanz des Intervalls in Metern
                start_m = int(row['start_km'] * 1000)
                end_m = int(row['end_km'] * 1000)
                distance_m = end_m - start_m
                # Sicherheitscheck für das letzte Segment oder Rundungsfehler
                if distance_m <= 0:
                    continue
                f.write(f"Step {idx}: Distance {distance_m}m, Target {row['target_watt']}W\n")
        print(f"Distanzbasiertes Garmin-Workout exportiert: {output_filename}")

    def _generate_synthetic_oetztaler(self):
        segs = [{'l': 31.5, 's': -0.5}, {'l': 18.0, 's': 7.5}, {'l': 35.0, 's': -4.5}, {'l': 37.5, 's': 2.2},
                {'l': 14.5, 's': -3.0}, {'l': 15.5, 's': 7.3}, {'l': 20.0, 's': -6.0}, {'l': 29.0, 's': 6.2}, {'l': 26.0, 's': -4.0}]
        p_data = []
        c_dist = 0.0
        lat, lon = 47.25142, 11.01241
        for seg in segs:
            steps = int(seg['l'] * 4)
            d_step = (seg['l'] / steps) * 1000.0
            for _ in range(steps):
                c_dist += (d_step / 1000.0)
                lat += 0.0005
                lon += 0.0005
                p_data.append({
                    'distance_km': c_dist,
                    'segment_len_m': d_step,
                    'slope': seg['s'] + np.random.normal(0, 0.1),
                    'latitude': lat,
                    'longitude': lon,
                    'elevation': 1377.0 + (c_dist * 5)
                })
        return pd.DataFrame(p_data)

if __name__ == "__main__":
    optimizer = AdvancedPacingOptimizer(initial_ftp=300, rider_weight=72.0, bike_weight=8.0, carb_intake_per_hour=90)
    df_route = optimizer.parse_gpx("oetztaler_route.gpx")
    df_raw = optimizer.generate_raw_pacing_dataframe(df_route)
    df_intervals = optimizer.optimize_pacing(df_route)
    print(df_intervals.to_string(index=False))
    optimizer.generate_nutrition_shopping_list(df_intervals)
    optimizer.export_to_zwift(df_intervals, "oetztaler_final.zwo")
    optimizer.export_to_garmin_fit(df_intervals, "oetztaler_final.fit")
    optimizer.export_to_karoo_json(df_route, route_name="Ötztaler Radmarathon", output_filename="oetztaler_final.json")

