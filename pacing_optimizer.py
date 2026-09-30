import os
import io
import math
import json
import time
import hashlib
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timezone
import numpy as np
import pandas as pd

try:
    import gpxpy
except ImportError:
    gpxpy = None

class ElevationFetchError(Exception):
    """Fehler beim Abrufen von Höhendaten über eine externe API."""
    pass


def _get_elevation_cache_dir():
    cache_dir = os.path.expanduser("~/.cache/pacing_optimizer/elevation")
    try:
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir
    except Exception:
        fallback = os.path.join(tempfile.gettempdir(), "pacing_elevation_cache")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _compute_route_hash(df):
    hasher = hashlib.sha256()
    summary = f"{len(df)}:{df['distance_km'].iloc[-1]:.3f}:"
    hasher.update(summary.encode('utf-8'))
    for lat, lon in zip(df['latitude'], df['longitude']):
        hasher.update(f"{lat:.5f},{lon:.5f};".encode('ascii'))
    return hasher.hexdigest()[:24]


def _apply_elevation_and_slope(df):
    if len(df) >= 5:
        smoothed_ele = df['elevation'].rolling(window=5, min_periods=1, center=True).mean()
    else:
        smoothed_ele = df['elevation']

    ele_diff = smoothed_ele.diff().fillna(0.0)
    seg_len = df['segment_len_m'].replace(0.0, 1.0)
    df['slope'] = (ele_diff / seg_len) * 100.0
    if len(df) >= 15:
        df['slope'] = df['slope'].rolling(window=15, min_periods=1, center=True).mean()


class AdvancedPacingOptimizer:
    def __init__(self, initial_ftp=300, w_prime_max=20000, target_factor=0.82, 
                 min_duration_sec=300, carb_intake_per_hour=90,
                 rider_weight=75.0, bike_weight=8.5, cda=0.35, crr=0.005,
                 initial_glycogen_kcal=2000.0, max_descent_kmh=56.0):
        self.initial_ftp = initial_ftp
        self.w_prime_max = w_prime_max
        self.target_factor = target_factor
        self.min_duration_sec = min_duration_sec
        self.carb_intake_per_hour = carb_intake_per_hour
        self.rider_weight = rider_weight
        self.bike_weight = bike_weight
        self.total_mass = rider_weight + bike_weight
        self.cda = cda
        self.crr = crr
        self.rho = 1.2
        self.loss_dt = 0.03
        self.initial_glycogen_kcal = initial_glycogen_kcal
        self.max_descent_kmh = max_descent_kmh
        self.elevation_source = "gpx"
        self.elevation_error = None

    def _solve_velocity(self, target_watt, slope_pct):
        s = slope_pct / 100.0
        g = 9.81
        # Effektive Leistung am Hinterrad (Kettenverlust einbezogen)
        p_wheel = max(target_watt * (1.0 - self.loss_dt), 0.0)
        # Konstante Kräfte (Hangabtrieb + Rollwiderstand)
        f_constant = (self.total_mass * g * s) + (self.total_mass * g * self.crr)
        # Bisektion-Suchbereich: Zwischen 1.50 m/s (5.4 km/h) und maximaler technischer Abfahrtsgeschwindigkeit
        v_max_mps = self.max_descent_kmh / 3.6
        low, high = 1.50, v_max_mps
        for _ in range(16):
            mid = (low + high) / 2.0
            # Physikalische Leistungsgleichung: P = F_luft * v + F_konstant * v
            p_calc = (0.5 * self.cda * self.rho * (mid**3)) + (f_constant * mid)
            if p_calc > p_wheel:
                high = mid  # Zu schnell für die getretene Leistung
            else:
                low = mid   # Mehr Leistung vorhanden, schneller fahren
                
        return (low + high) / 2.0

    def enrich_elevation_from_api(self, df, progress_callback=None, timeout_per_request=8.0, total_timeout=40.0):
        """
        Ruft Höhendaten für die Koordinaten im DataFrame über Open-Meteo oder Open-Elevation ab.
        - Prüft zuerst den lokalen Festplatten-Cache.
        - Bis 450 Punkte: Open-Meteo in kleinen 90er-Batches mit Pacing (schnell, unter 600/min).
        - Ab 450 Punkte oder bei HTTP 429/403: Automatischer Fallback auf Open-Elevation per POST.
        - Meldet Zwischenstände über progress_callback(fraction, message).
        
        Bei Fehlern oder Timeouts wird ElevationFetchError ausgelöst.
        """
        if df.empty or 'latitude' not in df.columns or 'longitude' not in df.columns:
            return df

        # 1. Prüfen, ob für diese Route bereits ein lokaler Disk-Cache existiert
        cache_key = _compute_route_hash(df)
        cache_file = os.path.join(_get_elevation_cache_dir(), f"{cache_key}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                cached_elevations = cached_data.get("elevations")
                if cached_elevations and len(cached_elevations) == len(df):
                    df['elevation'] = np.array(cached_elevations, dtype=float)
                    _apply_elevation_and_slope(df)
                    self.elevation_source = "cache"
                    self.elevation_error = None
                    return df
            except Exception:
                pass  # Bei beschädigtem Cache frisch anfragen

        total_dist_m = float(df['distance_km'].iloc[-1] * 1000.0) if not df.empty else 0.0
        
        # 2. Raster-Berechnung:
        # Strecken bis 100 km: ca. 400-450 Stützpunkte (passt perfekt ins Open-Meteo 600er-Minutenkontingent)
        # Strecken über 100 km: 75-100m Raster (max. 1500 Punkte, ideal für Open-Elevation POST)
        if total_dist_m <= 100000.0:
            min_spacing_m = max(50.0, total_dist_m / 450.0)
        else:
            min_spacing_m = max(75.0, total_dist_m / 1500.0)

        selected_indices = [0]
        last_dist_m = 0.0
        for idx in range(1, len(df)):
            dist_m = df['distance_km'].iloc[idx] * 1000.0
            if dist_m - last_dist_m >= min_spacing_m:
                selected_indices.append(idx)
                last_dist_m = dist_m

        if selected_indices[-1] != len(df) - 1:
            selected_indices.append(len(df) - 1)

        sample_df = df.iloc[selected_indices]
        coords_lat = sample_df['latitude'].tolist()
        coords_lon = sample_df['longitude'].tolist()
        n_sample = len(sample_df)

        def _fetch_open_meteo(lats, lons):
            chunk_size = 90  # 90 Punkte pro URL
            chunks = [
                (lats[i:i + chunk_size], lons[i:i + chunk_size])
                for i in range(0, len(lats), chunk_size)
            ]
            elevs = []
            for i, (ch_lats, ch_lons) in enumerate(chunks):
                if progress_callback:
                    pct = (i / len(chunks)) * 0.95
                    progress_callback(pct, f"Abruf via Open-Meteo ({int(pct * 100)} %)...")
                if i > 0:
                    time.sleep(0.06)

                lat_str = ",".join(f"{lat:.5f}" for lat in ch_lats)
                lon_str = ",".join(f"{lon:.5f}" for lon in ch_lons)
                url = f"https://api.open-meteo.com/v1/elevation?latitude={lat_str}&longitude={lon_str}"
                req = urllib.request.Request(url, headers={"User-Agent": "PacingOptimizer/1.0"})
                
                with urllib.request.urlopen(req, timeout=timeout_per_request) as resp:
                    status_code = getattr(resp, "status", getattr(resp, "code", 200))
                    if status_code != 200:
                        raise ElevationFetchError(f"Open-Meteo meldete Status {status_code}")
                    payload = json.loads(resp.read().decode("utf-8"))
                    if "elevation" not in payload:
                        raise ElevationFetchError("Kein 'elevation'-Feld in Open-Meteo Antwort")
                    elevs.extend(payload["elevation"])
            return elevs

        def _fetch_open_elevation(lats, lons):
            chunk_size = 500  # 500 Punkte pro POST
            chunks = [
                (lats[i:i + chunk_size], lons[i:i + chunk_size])
                for i in range(0, len(lats), chunk_size)
            ]
            elevs = []
            for i, (ch_lats, ch_lons) in enumerate(chunks):
                if progress_callback:
                    pct = (i / len(chunks)) * 0.95
                    progress_callback(pct, f"Abruf via Open-Elevation POST ({int(pct * 100)} %)...")
                if i > 0:
                    time.sleep(0.1)

                url = "https://api.open-elevation.com/api/v1/lookup"
                locations = [{"latitude": round(lat, 5), "longitude": round(lon, 5)} for lat, lon in zip(ch_lats, ch_lons)]
                payload_bytes = json.dumps({"locations": locations}).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": "PacingOptimizer/1.0"
                    }
                )
                with urllib.request.urlopen(req, timeout=timeout_per_request + 4.0) as resp:
                    status_code = getattr(resp, "status", getattr(resp, "code", 200))
                    if status_code != 200:
                        raise ElevationFetchError(f"Open-Elevation meldete Status {status_code}")
                    payload = json.loads(resp.read().decode("utf-8"))
                    results = payload.get("results", [])
                    if not results:
                        raise ElevationFetchError("Keine Ergebnisse von Open-Elevation")
                    elevs.extend([float(r.get("elevation") or 0.0) for r in results])
            return elevs

        fetched_elevations = None
        used_provider = "open-meteo"

        # 3. Provider-Strategie:
        # Wenn <= 450 Punkte: Open-Meteo zuerst. Bei 429/403 -> Fallback auf Open-Elevation.
        # Wenn > 450 Punkte: Open-Elevation zuerst. Bei Fehler -> Fallback auf Open-Meteo mit 450 Pkt.
        if n_sample <= 450:
            try:
                fetched_elevations = _fetch_open_meteo(coords_lat, coords_lon)
                used_provider = "open-meteo"
            except Exception as e_meteo:
                if progress_callback:
                    progress_callback(0.2, "Open-Meteo Rate-Limit erreicht. Schwenke auf Open-Elevation um...")
                try:
                    fetched_elevations = _fetch_open_elevation(coords_lat, coords_lon)
                    used_provider = "open-elevation"
                except Exception as e_elev:
                    err_msg = f"Höhendaten konnten weder über Open-Meteo ({e_meteo}) noch Open-Elevation ({e_elev}) bezogen werden."
                    self.elevation_source = "none"
                    self.elevation_error = err_msg
                    raise ElevationFetchError(err_msg)
        else:
            try:
                fetched_elevations = _fetch_open_elevation(coords_lat, coords_lon)
                used_provider = "open-elevation"
            except Exception as e_elev:
                if progress_callback:
                    progress_callback(0.2, "Open-Elevation nicht verfügbar. Schwenke auf Open-Meteo (450 Pkt) um...")
                try:
                    # Fallback auf 450 Punkte für Open-Meteo
                    step = math.ceil(n_sample / 450)
                    sub_indices = list(range(0, n_sample, step))
                    if sub_indices[-1] != n_sample - 1:
                        sub_indices.append(n_sample - 1)
                    sub_lats = [coords_lat[idx] for idx in sub_indices]
                    sub_lons = [coords_lon[idx] for idx in sub_indices]
                    sub_elevs = _fetch_open_meteo(sub_lats, sub_lons)
                    
                    # Auf n_sample rückinterpolieren
                    sub_dists = [sample_df['distance_km'].iloc[idx] for idx in sub_indices]
                    fetched_elevations = list(np.interp(sample_df['distance_km'].values, sub_dists, sub_elevs))
                    used_provider = "open-meteo"
                except Exception as e_meteo:
                    err_msg = f"Höhendaten konnten weder über Open-Elevation ({e_elev}) noch Open-Meteo ({e_meteo}) bezogen werden."
                    self.elevation_source = "none"
                    self.elevation_error = err_msg
                    raise ElevationFetchError(err_msg)

        if not fetched_elevations or len(fetched_elevations) != len(sample_df):
            err_msg = "Die Höhendaten konnten nicht bezogen werden: Unvollständige API-Antwort."
            self.elevation_source = "none"
            self.elevation_error = err_msg
            raise ElevationFetchError(err_msg)

        if progress_callback:
            progress_callback(0.98, "Interpoliere Höhendaten und berechne Steigungsprofil...")

        # 4. Auf alle Punkte des Original-DataFrames interpolieren
        sample_dists = sample_df['distance_km'].values
        all_dists = df['distance_km'].values
        final_elevations = np.interp(all_dists, sample_dists, fetched_elevations)

        df['elevation'] = np.round(final_elevations, 1)
        _apply_elevation_and_slope(df)

        # 5. Im lokalen Disk-Cache sichern
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "provider": used_provider,
                    "points": len(df),
                    "distance_km": float(df['distance_km'].iloc[-1]),
                    "elevations": df['elevation'].round(1).tolist()
                }, f)
        except Exception:
            pass

        if progress_callback:
            progress_callback(1.0, "Fertig!")

        self.elevation_source = used_provider
        self.elevation_error = None
        return df

    def parse_gpx(self, gpx_source, auto_fetch_elevation=True, elevation_timeout=40.0, progress_callback=None):
        if gpxpy is None:
            return self._generate_synthetic_oetztaler()

        try:
            if isinstance(gpx_source, (bytes, bytearray)):
                gpx = gpxpy.parse(io.BytesIO(gpx_source))
            elif isinstance(gpx_source, str) and ("<gpx" in gpx_source or "<?xml" in gpx_source):
                gpx = gpxpy.parse(io.StringIO(gpx_source))
            elif isinstance(gpx_source, str):
                resolved = gpx_source
                if not os.path.exists(resolved):
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    cand = os.path.join(script_dir, gpx_source)
                    if os.path.exists(cand):
                        resolved = cand
                    else:
                        cand_base = os.path.join(script_dir, os.path.basename(gpx_source))
                        if os.path.exists(cand_base):
                            resolved = cand_base
                if os.path.exists(resolved):
                    with open(resolved, 'r', encoding='utf-8') as f:
                        gpx = gpxpy.parse(f)
                else:
                    return self._generate_synthetic_oetztaler()
        except Exception:
            return self._generate_synthetic_oetztaler()
            
        points_data = []
        cumulative_dist = 0.0
        prev_point = None
        
        segments_to_process = []
        for track in gpx.tracks:
            segments_to_process.extend(track.segments)
        if not segments_to_process and hasattr(gpx, 'routes'):
            for route in gpx.routes:
                segments_to_process.append(route)

        for segment in segments_to_process:
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

        # Automatische Erkennung und Ergänzung fehlender Höhendaten
        has_valid_elevation = False
        if not df.empty and 'elevation' in df.columns:
            non_zero = (df['elevation'] != 0.0) & df['elevation'].notna()
            # Valide, wenn Werte ungleich 0 existieren und Varianz vorhanden ist (nicht flach auf 0.0)
            if non_zero.any() and (df['elevation'].max() - df['elevation'].min() > 0.001):
                has_valid_elevation = True

        if not df.empty and not has_valid_elevation:
            if auto_fetch_elevation:
                try:
                    self.enrich_elevation_from_api(df, progress_callback=progress_callback, total_timeout=elevation_timeout)
                except ElevationFetchError:
                    # df bleibt mit 0 Hm erhalten, Fehlerstatus ist in self.elevation_error hinterlegt
                    pass
            else:
                self.elevation_source = "none"
                self.elevation_error = "Die GPX-Datei enthält keine Höhendaten."
        elif not df.empty and has_valid_elevation:
            self.elevation_source = "gpx"
            self.elevation_error = None

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
        g = 9.81
        
        for idx, row in df_route.iterrows():
            slope = row['slope']
            dist_m = row['segment_len_m']
            s = slope / 100.0
            
            tank_emptiness_pct = 1.0 - (internal_glycogen_kcal / self.initial_glycogen_kcal) if self.initial_glycogen_kcal > 0 else 1.0
            # Realistische physiologische Ermüdung bei fortschreitender Glykogenentleerung (max. 10% Abfall)
            current_ftp = self.initial_ftp * (1.0 - (0.10 * (tank_emptiness_pct ** 2)))
            
            # 1. Neigungsabhängiges Pacing:
            if slope < -5.0:
                # Steile Abfahrten: Rollen lassen / aktive Erholung
                base_factor = 0.0
            elif slope < -1.5:
                # Leichte Gefälle: Sanftes Mittreten
                ratio = (slope - (-5.0)) / 3.5
                base_factor = ratio * (self.target_factor * 0.45)
            elif slope <= 1.5:
                # Flachstücke & leichtes Rollen: Orientierung an gewähltem Target Factor
                base_factor = self.target_factor * (1.0 + 0.02 * slope)
            else:
                # Anstiege: Progressive Leistungssteigerung (moderat bei falschen Flachstücken, spürbar an echten Bergen)
                climb_slope = slope - 1.5
                slope_boost = 0.035 * climb_slope + 0.0025 * (climb_slope ** 1.5)
                base_factor = self.target_factor * (1.0 + slope_boost)
            
            target_watt = base_factor * current_ftp
            
            # 2. Biomechanischer & physikalischer Mindest-Kletterleistungs-Floor auf steilen Rampen
            # Verhindert Umfallen / Abwürgen bei steilen Rampen (z.B. > 8-18%) selbst bei "lockerem" Setup
            if slope >= 3.0:
                v_min = 1.95  # ca. 7.0 km/h (entspricht ca. 50-55 U/min im kleinsten Rettungsgang 34/32)
                sin_theta = s / math.sqrt(1.0 + s**2)
                f_gravity = self.total_mass * g * sin_theta
                f_roll = self.total_mass * g * self.crr
                p_min_crank = ((f_gravity + f_roll) * v_min) / (1.0 - self.loss_dt)
                target_watt = max(target_watt, p_min_crank)
            
            # 3. W'-Begrenzung (anaerober Akku)
            w_prime_pct = w_prime_current / self.w_prime_max if self.w_prime_max > 0 else 1.0
            if w_prime_pct > 0.30:
                max_allowed_watt = current_ftp * 1.45
            elif w_prime_pct > 0.15:
                max_allowed_watt = current_ftp * 1.20
            else:
                max_allowed_watt = current_ftp * 1.05
            
            target_watt = min(target_watt, max(max_allowed_watt, current_ftp * 0.85))
            if slope <= -5.0:
                target_watt = 0
            else:
                target_watt = int(round(target_watt / 5.0) * 5)
            
            v_mps = self._solve_velocity(target_watt, slope)
            dt = dist_m / v_mps
            cumulative_time_sec += dt
            
            # 4. Stoffwechsel-Crossover (Kohlenhydrate vs. Fettverbrennung)
            p_ratio = target_watt / current_ftp if current_ftp > 0 else 1.0
            f_cho = min(1.0, max(0.15, p_ratio ** 2.2))
            
            intake_kcal = (self.carb_intake_per_hour / 3600.0) * dt * 4.1
            burned_kcal = (target_watt * dt) / 1000.0
            glycogen_burned_kcal = burned_kcal * f_cho
            total_burned_kcal += burned_kcal
            
            internal_glycogen_kcal = max(0.0, min(self.initial_glycogen_kcal, internal_glycogen_kcal - (glycogen_burned_kcal - intake_kcal)))
            
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
        if df_raw.empty:
            return pd.DataFrame(columns=['start_km', 'end_km', 'duration_min', 'target_watt', 'pct_ftp'])
            
        n = len(df_raw)
        if n == 1:
            row = df_raw.iloc[0]
            target_watt = int(row['target_power'])
            return pd.DataFrame([{
                'start_km': round(row['dist_km'], 1),
                'end_km': round(row['dist_km'], 1),
                'duration_min': round(row['duration_sec'] / 60.0, 1),
                'target_watt': target_watt,
                'pct_ftp': round((target_watt / self.initial_ftp) * 100.0, 1)
            }])

        # 1. Topologische Anstiegsblöcke identifizieren (inkl. kurzer Rampen >= 10m Gain)
        climb_blocks = []
        in_c = False
        start_c = 0
        for i in range(n):
            slp = df_raw['slope'].iloc[i]
            if not in_c and slp >= 2.5:
                in_c = True
                start_c = i
            elif in_c and slp < 1.0:
                in_c = False
                gain = df_raw['ele'].iloc[i] - df_raw['ele'].iloc[start_c]
                dist = (df_raw['dist_km'].iloc[i] - df_raw['dist_km'].iloc[start_c]) * 1000.0
                avg_s = df_raw['slope'].iloc[start_c:i].mean()
                # Signifikante Kletterrampe:
                # - mind. 10m Höhengewinn (selbst bei nur 150-200m Länge)
                # - oder mind. 8m Höhengewinn bei steilem Gefälle (>= 4%)
                # - oder mind. 180m Länge bei >= 4%
                if (gain >= 10.0) or (gain >= 8.0 and avg_s >= 4.0) or (dist >= 180.0 and avg_s >= 4.0):
                    climb_blocks.append((start_c, i, 'CLIMB'))
        if in_c:
            gain = df_raw['ele'].iloc[-1] - df_raw['ele'].iloc[start_c]
            if gain >= 8.0:
                climb_blocks.append((start_c, n - 1, 'CLIMB'))

        # 2. Topologische Abfahrtsblöcke identifizieren
        descent_blocks = []
        in_d = False
        start_d = 0
        for i in range(n):
            slp = df_raw['slope'].iloc[i]
            if not in_d and slp <= -2.5:
                in_d = True
                start_d = i
            elif in_d and slp > -1.0:
                in_d = False
                drop = df_raw['ele'].iloc[start_d] - df_raw['ele'].iloc[i]
                dur = df_raw['duration_sec'].iloc[start_d:i].sum()
                if drop >= 15.0 or (drop >= 8.0 and dur >= 45.0):
                    descent_blocks.append((start_d, i, 'DESCENT'))
        if in_d:
            drop = df_raw['ele'].iloc[start_d] - df_raw['ele'].iloc[-1]
            if drop >= 10.0:
                descent_blocks.append((start_d, n - 1, 'DESCENT'))

        # Grenzen an allen Übergängen setzen
        boundary_indices = set([0, n - 1])
        for s_idx, e_idx, _ in climb_blocks:
            boundary_indices.add(s_idx)
            boundary_indices.add(e_idx)
        for s_idx, e_idx, _ in descent_blocks:
            boundary_indices.add(s_idx)
            boundary_indices.add(e_idx)
            
        sorted_boundaries = sorted(boundary_indices)
        
        # Rohe Segmente zwischen allen Grenzen bilden
        raw_segments = []
        for idx_b in range(len(sorted_boundaries) - 1):
            i_start = sorted_boundaries[idx_b]
            i_end = sorted_boundaries[idx_b + 1]
            chunk = df_raw.iloc[i_start:i_end]
            if chunk.empty:
                continue
            
            dur_s = chunk['duration_sec'].sum()
            gain = df_raw['ele'].iloc[i_end] - df_raw['ele'].iloc[i_start]
            avg_w = (chunk['target_power'] * chunk['duration_sec']).sum() / dur_s if dur_s > 0 else chunk['target_power'].mean()
            dist_m = (df_raw['dist_km'].iloc[i_end] - df_raw['dist_km'].iloc[i_start]) * 1000.0
            avg_s = (gain / max(1.0, dist_m)) * 100.0
            
            raw_segments.append({
                'start_idx': i_start,
                'end_idx': i_end,
                'start_km': df_raw['dist_km'].iloc[i_start],
                'end_km': df_raw['dist_km'].iloc[i_end],
                'dur_s': dur_s,
                'avg_w': avg_w,
                'gain_m': gain,
                'avg_slope': avg_s,
                'dist_m': dist_m
            })

        # 3. Pass 1: Nicht-Kicker flach/wellig zusammenfassen
        merged1 = []
        cur = None
        for seg in raw_segments:
            is_k = (seg['gain_m'] >= 9.0 and seg['avg_slope'] >= 3.0) or (seg['dist_m'] >= 150.0 and seg['gain_m'] >= 10.0)
            is_d = (seg['gain_m'] <= -12.0 and seg['avg_slope'] <= -2.5)
            
            if cur is None:
                cur = seg
                continue
                
            cur_is_k = (cur['gain_m'] >= 9.0 and cur['avg_slope'] >= 3.0) or (cur['dist_m'] >= 150.0 and cur['gain_m'] >= 10.0)
            cur_is_d = (cur['gain_m'] <= -12.0 and cur['avg_slope'] <= -2.5)
            
            # Kicker werden NIEMALS in Flachstücke oder Abfahrten absorbiert
            if cur_is_k or is_k:
                merged1.append(cur)
                cur = seg
            elif cur_is_d != is_d:
                merged1.append(cur)
                cur = seg
            elif cur['dur_s'] < self.min_duration_sec or abs(cur['avg_w'] - seg['avg_w']) < (self.initial_ftp * 0.06):
                total_dur = cur['dur_s'] + seg['dur_s']
                cur_avg_w = (cur['avg_w'] * cur['dur_s'] + seg['avg_w'] * seg['dur_s']) / total_dur if total_dur > 0 else cur['avg_w']
                cur = {
                    'start_idx': cur['start_idx'],
                    'end_idx': seg['end_idx'],
                    'start_km': cur['start_km'],
                    'end_km': seg['end_km'],
                    'dur_s': total_dur,
                    'avg_w': cur_avg_w,
                    'gain_m': cur['gain_m'] + seg['gain_m'],
                    'avg_slope': ((cur['gain_m'] + seg['gain_m']) / max(1.0, cur['dist_m'] + seg['dist_m'])) * 100.0,
                    'dist_m': cur['dist_m'] + seg['dist_m']
                }
            else:
                merged1.append(cur)
                cur = seg
        if cur is not None:
            merged1.append(cur)
            
        # 4. Pass 2: Winzige Übergangsschnipsel (< 50s oder < 250m), die keine Kicker sind, glätten
        final_merged = []
        for it in merged1:
            is_k = (it['gain_m'] >= 9.0 and it['avg_slope'] >= 3.0) or (it['dist_m'] >= 150.0 and it['gain_m'] >= 10.0)
            if not final_merged:
                final_merged.append(it)
                continue
            prev = final_merged[-1]
            prev_is_k = (prev['gain_m'] >= 9.0 and prev['avg_slope'] >= 3.5) or (prev['dist_m'] >= 150.0 and prev['gain_m'] >= 10.0)
            
            if not is_k and (it['dur_s'] < 50.0 or it['dist_m'] < 250.0):
                tot_dur = prev['dur_s'] + it['dur_s']
                avg_w = (prev['avg_w'] * prev['dur_s'] + it['avg_w'] * it['dur_s']) / tot_dur if tot_dur > 0 else prev['avg_w']
                prev['end_idx'] = it['end_idx']
                prev['end_km'] = it['end_km']
                prev['dur_s'] = tot_dur
                prev['avg_w'] = avg_w
                prev['gain_m'] += it['gain_m']
                prev['dist_m'] += it['dist_m']
                prev['avg_slope'] = (prev['gain_m'] / max(1.0, prev['dist_m'])) * 100.0
            elif not prev_is_k and not is_k and abs(prev['avg_w'] - it['avg_w']) < (self.initial_ftp * 0.05):
                tot_dur = prev['dur_s'] + it['dur_s']
                avg_w = (prev['avg_w'] * prev['dur_s'] + it['avg_w'] * it['dur_s']) / tot_dur if tot_dur > 0 else prev['avg_w']
                prev['end_idx'] = it['end_idx']
                prev['end_km'] = it['end_km']
                prev['dur_s'] = tot_dur
                prev['avg_w'] = avg_w
                prev['gain_m'] += it['gain_m']
                prev['dist_m'] += it['dist_m']
                prev['avg_slope'] = (prev['gain_m'] / max(1.0, prev['dist_m'])) * 100.0
            else:
                final_merged.append(it)

        # Sichere durchgängige Kilometer-Kette
        final_merged[0]['start_km'] = df_raw['dist_km'].iloc[0]
        out = []
        for it in final_merged:
            target_watt = int(round(it['avg_w'] / 5.0) * 5)
            out.append({
                'start_km': round(it['start_km'], 1),
                'end_km': round(it['end_km'], 1),
                'duration_min': round(it['dur_s'] / 60.0, 1),
                'target_watt': target_watt,
                'pct_ftp': round((target_watt / self.initial_ftp) * 100.0, 1)
            })
        return pd.DataFrame(out)

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

