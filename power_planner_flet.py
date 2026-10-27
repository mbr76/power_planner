"""
Power-Planner (Flet Edition)
Cross-platform Pacing & Nutrition Strategy App for Desktop (macOS/Windows/Linux) 
and Mobile (iOS/Android/iPadOS).
"""

import asyncio
import sys
import os
import io
import math
import time
import json
import base64
import tempfile
import subprocess
from urllib.parse import urlparse, urlunparse
from PIL import Image

# Ensure writable matplotlib config directory in all sandboxes/platforms
os.environ['MPLCONFIGDIR'] = tempfile.gettempdir()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

import flet as ft
from pacing_optimizer import AdvancedPacingOptimizer
from gpx_exporter import generate_gpx_from_pacing_track
from hammerhead_client import HammerheadClient, BrowserAuthSession
from i18n import (
    t,
    set_language,
    get_language,
    detect_system_language,
    get_guide_sections,
    SUPPORTED_LANGUAGES,
)

try:
    import zxingcpp
except ImportError:
    zxingcpp = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import numpy as np
except ImportError:
    np = None


# App Version & Build Metadata
APP_VERSION = "1.0.0"
BUILD_NUMBER = "46"
BUILD_TIMESTAMP = "2026-10-27 21:31:32"

# Übersetzungs-Presets für Berggänge (kleinste Übersetzung) und Abfahrten (größte Übersetzung)
GEAR_RATIOS_LOW = {
    "33/34": ("33 / 34 (0.97) — SRAM AXS Berg (z.B. 46/33 × 10-34)", 33.0 / 34.0),
    "34/34": ("34 / 34 (1.00) — Shimano Compact Berg (34 × 34)", 34.0 / 34.0),
    "30/34": ("30 / 34 (0.88) — Shimano GRX Subcompact (30 × 34)", 30.0 / 34.0),
    "34/32": ("34 / 32 (1.06) — Shimano Compact Standard (34 × 32)", 34.0 / 32.0),
    "36/30": ("36 / 30 (1.20) — Semi-Compact Berg (36 × 30)", 36.0 / 30.0),
    "39/28": ("39 / 28 (1.39) — Klassisch Standard (39 × 28)", 39.0 / 28.0),
    "38/44": ("38 / 44 (0.86) — 1x Gravel Berg (38 × 10-44)", 38.0 / 44.0),
    "40/44": ("40 / 44 (0.91) — 1x Gravel Berg (40 × 10-44)", 40.0 / 44.0),
}

GEAR_RATIOS_HIGH = {
    "46/10": ("46 / 10 (4.60) — SRAM AXS Allroad (46 × 10)", 46.0 / 10.0),
    "48/10": ("48 / 10 (4.80) — SRAM AXS Road (48 × 10)", 48.0 / 10.0),
    "50/10": ("50 / 10 (5.00) — SRAM AXS Aero (50 × 10)", 50.0 / 10.0),
    "50/11": ("50 / 11 (4.55) — Shimano Compact (50 × 11)", 50.0 / 11.0),
    "52/11": ("52 / 11 (4.73) — Shimano Semi-Compact (52 × 11)", 52.0 / 11.0),
    "54/11": ("54 / 11 (4.91) — Shimano Pro / TT (54 × 11)", 54.0 / 11.0),
    "40/10": ("40 / 10 (4.00) — 1x Gravel Speed (40 × 10)", 40.0 / 10.0),
}



# ==========================================
# HELPER FUNCTIONS & NETWORK LOGIC
# ==========================================

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)


def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)


_map_tile_cache = {}


def fetch_map_background(min_lat, max_lat, min_lon, max_lon, zoom=None, is_dark=False):
    try:
        import urllib.request

        # Dynamic zoom: target between 4 and 16 tiles for optimal sharpness and speed
        if zoom is None:
            for z in range(13, 6, -1):
                x0, y0 = deg2num(max_lat, min_lon, z)
                x1, y1 = deg2num(min_lat, max_lon, z)
                if (abs(x1 - x0) + 1) * (abs(y1 - y0) + 1) <= 16:
                    zoom = z
                    break
            if zoom is None:
                zoom = 8

        x0, y0 = deg2num(max_lat, min_lon, zoom)
        x1, y1 = deg2num(min_lat, max_lon, zoom)

        tile_w, tile_h = 256, 256
        num_x = abs(x1 - x0) + 1
        num_y = abs(y1 - y0) + 1

        if num_x * num_y > 36 and zoom > 6:
            return fetch_map_background(min_lat, max_lat, min_lon, max_lon, zoom - 1, is_dark)

        combined = Image.new("RGB", (num_x * tile_w, num_y * tile_h))

        # Free, high-performance basemap services without API key requirements:
        # Dark: Esri World Dark Gray Base (clean dark canvas designed for GPS/data overlay)
        # Light: Esri World Topo Map (shaded relief, mountains, contour elevations)
        if is_dark:
            base_url = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile"
        else:
            base_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile"

        for i, x in enumerate(range(min(x0, x1), max(x0, x1) + 1)):
            for j, y in enumerate(range(min(y0, y1), max(y0, y1) + 1)):
                cache_key = (base_url, zoom, y, x)
                if cache_key in _map_tile_cache:
                    combined.paste(_map_tile_cache[cache_key], (i * tile_w, j * tile_h))
                    continue

                url = f"{base_url}/{zoom}/{y}/{x}"
                req = urllib.request.Request(url, headers={"User-Agent": "PowerPlanner/2.0 (cycling-app)"})
                try:
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        tile_img = Image.open(io.BytesIO(resp.read())).convert("RGB")
                        _map_tile_cache[cache_key] = tile_img
                        combined.paste(tile_img, (i * tile_w, j * tile_h))
                except Exception:
                    # Fallback to OpenStreetMap standard tile server
                    try:
                        osm_url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
                        osm_req = urllib.request.Request(osm_url, headers={"User-Agent": "PowerPlanner/2.0 (cycling-app)"})
                        with urllib.request.urlopen(osm_req, timeout=3.0) as osm_resp:
                            tile_img = Image.open(io.BytesIO(osm_resp.read())).convert("RGB")
                            _map_tile_cache[cache_key] = tile_img
                            combined.paste(tile_img, (i * tile_w, j * tile_h))
                    except Exception:
                        pass

        nw_lat, nw_lon = num2deg(min(x0, x1), min(y0, y1), zoom)
        se_lat, se_lon = num2deg(max(x0, x1) + 1, max(y0, y1) + 1, zoom)
        extent = [nw_lon, se_lon, se_lat, nw_lat]
        return combined, extent
    except Exception:
        return None, None


KNOWN_PASSES = [
    # Ötztaler & Tirol
    (47.214, 11.020, "Kühtai"),
    (47.006, 11.506, "Brenner"),
    (46.840, 11.319, "Jaufenpass"),
    (46.905, 11.097, "Timmelsjoch"),
    (47.290, 10.651, "Hahntennjoch"),
    (47.129, 10.209, "Arlbergpass"),
    (47.157, 10.163, "Flexenpass"),
    (47.280, 10.128, "Hochtannbergpass"),
    (47.273, 9.907, "Faschinajoch"),
    (46.918, 10.092, "Silvretta Bielerhöhe"),
    (47.243, 12.122, "Gerlospass"),
    (47.083, 12.843, "Großglockner"),
    (47.472, 12.431, "Kitzbüheler Horn"),
    (46.928, 10.938, "Ötztaler Gletscherstraße"),
    # Dolomiten & Italien
    (46.508, 11.767, "Sellajoch"),
    (46.550, 11.809, "Grödnerjoch"),
    (46.488, 11.812, "Pordoijoch"),
    (46.520, 11.874, "Campolongo"),
    (46.483, 12.054, "Passo Giau"),
    (46.519, 12.009, "Falzarego"),
    (46.528, 11.990, "Valparola"),
    (46.529, 10.453, "Stilfser Joch"),
    (46.346, 10.488, "Passo di Gavia"),
    (46.248, 10.300, "Passo del Mortirolo"),
    (46.260, 10.583, "Passo del Tonale"),
    (46.457, 11.868, "Passo Fedaia"),
    (46.617, 12.298, "Drei Zinnen"),
    (46.480, 12.937, "Monte Zoncolan"),
    (45.051, 7.054, "Colle delle Finestre"),
    # Schweiz
    (46.556, 8.568, "Gotthardpass"),
    (46.572, 8.415, "Furkapass"),
    (46.561, 8.337, "Grimselpass"),
    (46.729, 8.448, "Sustenpass"),
    (46.478, 8.385, "Nufenenpass"),
    (46.659, 8.671, "Oberalppass"),
    (46.868, 8.855, "Klausenpass"),
    (46.584, 9.838, "Albulapass"),
    (46.411, 10.024, "Berninapass"),
    (46.750, 9.948, "Flüelapass"),
    (46.473, 9.718, "Julierpass"),
    (46.505, 9.330, "Splügenpass"),
    (46.496, 9.171, "San Bernardino"),
    (46.250, 8.033, "Simplonpass"),
    # Frankreich & Pyrenäen
    (45.064, 6.408, "Col du Galibier"),
    (45.035, 6.428, "Col du Lautaret"),
    (45.092, 6.069, "Alpe d'Huez"),
    (45.435, 6.376, "Col de la Madeleine"),
    (45.227, 6.204, "Col de la Croix de Fer"),
    (45.240, 6.175, "Col du Glandon"),
    (44.820, 6.735, "Col d'Izoard"),
    (44.539, 6.703, "Col de Vars"),
    (44.321, 6.807, "Cime de la Bonette"),
    (45.417, 7.031, "Col de l'Iseran"),
    (45.692, 6.690, "Cormet de Roselend"),
    (44.174, 5.279, "Mont Ventoux"),
    (42.908, 0.145, "Col du Tourmalet"),
    (42.929, 0.334, "Col d'Aspin"),
    (42.802, 0.453, "Col de Peyresourde"),
    (42.955, -0.098, "Hautacam"),
]


def format_to_iso_duration(minutes):
    total_seconds = int(float(minutes) * 60)
    hours = total_seconds // 3600
    minutes_rem = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes_rem:02d}:{seconds:02d}"
    return f"{minutes_rem:02d}:{seconds:02d}"


def normalize_karoo_url(url):
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    parsed = urlparse(url)
    path = parsed.path
    if not path or path == "/":
        path = "/upload"
    elif not path.endswith("/upload"):
        path = path.rstrip("/") + "/upload"
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))


def push_to_karoo_http(url, json_str, target_filename, log_cb=None, max_retries=2, timeout=6):
    import requests
    logs = []

    def emit(msg):
        logs.append(msg)
        if log_cb:
            log_cb(msg)

    normalized_url = normalize_karoo_url(url)
    payload_bytes = json_str.encode("utf-8")
    
    emit(f"[{time.strftime('%H:%M:%S')}] 📥 Eingabe-URL: {url.strip()}")
    emit(f"[{time.strftime('%H:%M:%S')}] 🎯 Ziel-Endpoint: {normalized_url}")
    emit(f"[{time.strftime('%H:%M:%S')}] 📦 Datei: {target_filename} ({len(payload_bytes)/1024:.1f} KB)")
    
    for attempt in range(1, max_retries + 1):
        try:
            emit(f"[{time.strftime('%H:%M:%S')}] 📡 Sende HTTP POST (Versuch {attempt}/{max_retries}, Timeout: {timeout}s)...")
            response = requests.post(
                normalized_url,
                data=payload_bytes,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Filename": target_filename,
                    "Content-Length": str(len(payload_bytes))
                },
                timeout=timeout
            )
            emit(f"[{time.strftime('%H:%M:%S')}] 📥 Status-Code: {response.status_code}")
            if response.text:
                emit(f"[{time.strftime('%H:%M:%S')}] 📥 Server-Antwort: {response.text.strip()[:300]}")
            
            if response.status_code == 200:
                emit(f"[{time.strftime('%H:%M:%S')}] ✅ Übertragung erfolgreich bestätigt!")
                return True, f"HTTP 200 OK — {response.text.strip() or 'Erfolgreich übertragen'}", logs
            else:
                emit(f"[{time.strftime('%H:%M:%S')}] ⚠️ Server meldete Fehlercode {response.status_code}")
                if attempt == max_retries:
                    return False, f"Server meldete HTTP {response.status_code}: {response.text.strip()}", logs
        except requests.exceptions.Timeout:
            emit(f"[{time.strftime('%H:%M:%S')}] ⏱️ Timeout bei Versuch {attempt}: Karoo hat nach {timeout}s nicht geantwortet.")
            if attempt == max_retries:
                return False, "Zeitüberschreitung: Karoo hat nach mehreren Versuchen nicht geantwortet.", logs
        except requests.exceptions.ConnectionError:
            emit(f"[{time.strftime('%H:%M:%S')}] ❌ Verbindungsfehler bei Versuch {attempt}: Karoo nicht erreichbar.")
            if attempt == max_retries:
                return False, "Verbindungsfehler: Karoo unter dieser IP/Port nicht erreichbar.", logs
        except Exception as e:
            emit(f"[{time.strftime('%H:%M:%S')}] 💥 Unerwarteter Fehler: {e}")
            return False, str(e), logs
            
        time.sleep(0.5)
    return False, "Alle Übertragungsversuche fehlgeschlagen.", logs



def push_to_karoo_adb(json_str, target_filename):
    try:
        subprocess.run(["adb", "shell", "mkdir", "-p", "/sdcard/PowerTracks/"], check=True, capture_output=True, text=True)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            tmp.write(json_str)
            tmp_path = tmp.name
            
        dest_path = f"/sdcard/PowerTracks/{target_filename}"
        result = subprocess.run(["adb", "push", tmp_path, dest_path], capture_output=True, text=True, check=True)
        os.remove(tmp_path)
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or str(e)
    except FileNotFoundError:
        return False, "ADB wurde auf dem System nicht gefunden (nicht im PATH)."


def decode_qr_image(file_path_or_bytes):
    if zxingcpp:
        try:
            if isinstance(file_path_or_bytes, (bytes, bytearray)):
                pil_img = Image.open(io.BytesIO(file_path_or_bytes))
            elif isinstance(file_path_or_bytes, str):
                pil_img = Image.open(file_path_or_bytes)
            elif hasattr(file_path_or_bytes, "convert"):
                pil_img = file_path_or_bytes
            else:
                pil_img = None
                res = zxingcpp.read_barcode(file_path_or_bytes)
                if res and res.text:
                    return res.text.strip()

            if pil_img is not None:
                if pil_img.mode not in ("RGB", "RGBA", "L"):
                    pil_img = pil_img.convert("RGB")
                res = zxingcpp.read_barcode(pil_img)
                if res and res.text:
                    return res.text.strip()
        except Exception:
            pass

    if cv2:
        try:
            cv_img = None
            if isinstance(file_path_or_bytes, (bytes, bytearray)) and np is not None:
                arr = np.frombuffer(file_path_or_bytes, np.uint8)
                cv_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            elif isinstance(file_path_or_bytes, str):
                cv_img = cv2.imread(file_path_or_bytes)
            elif hasattr(file_path_or_bytes, "shape"):
                cv_img = file_path_or_bytes
            if cv_img is not None:
                detector = cv2.QRCodeDetector()
                data, _, _ = detector.detectAndDecode(cv_img)
                if data:
                    return data.strip()
        except Exception:
            pass

    return None


def resolve_path(p):
    if not isinstance(p, str):
        return p
    if os.path.isabs(p) and os.path.exists(p):
        return p
    if os.path.exists(p):
        return p
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(script_dir, p)
    if os.path.exists(candidate):
        return candidate
    candidate_base = os.path.join(script_dir, os.path.basename(p))
    if os.path.exists(candidate_base):
        return candidate_base

    if hasattr(sys, '_MEIPASS'):
        bundled = os.path.join(sys._MEIPASS, p)
        if os.path.exists(bundled):
            return bundled
        bundled_base = os.path.join(sys._MEIPASS, os.path.basename(p))
        if os.path.exists(bundled_base):
            return bundled_base
    return p


def get_available_gpx_files():
    files = []
    search_dirs = ["."]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in search_dirs and os.path.exists(script_dir):
        search_dirs.append(script_dir)
    if hasattr(sys, '_MEIPASS') and sys._MEIPASS not in search_dirs:
        search_dirs.append(sys._MEIPASS)
    for base_dir in search_dirs:
        for root, dirs, filenames in os.walk(base_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "pacing-env" and d != "__pycache__" and d != "build"]
            for f in filenames:
                if f.lower().endswith(".gpx"):
                    name = os.path.basename(f)
                    if name not in files:
                        files.append(name)
    return sorted(files)


# ==========================================
# USER PREFERENCES & PERSISTENT STORAGE
# ==========================================

DEFAULT_RIDER_SETTINGS = {
    "initial_ftp": 310,
    "w_prime": 20000,
    "rider_w": 76.0,
}

DEFAULT_BIKE_SETTINGS = {
    "bike_w": 8.0,
    "lowest_gear_key": "33/34",
    "highest_gear_key": "46/10",
    "min_climb_cadence": 75.0,
    "max_pedal_cadence": 105.0,
}

DEFAULT_STRATEGY_SETTINGS = {
    "carbs_per_hour": 90,
    "target_f": 0.82,
    "pacing_mode": "dynamic",
    "gpx_path": "oetztaler_route.gpx",
    "language": "de",
}

DEFAULT_SYNC_SETTINGS = {
    "karoo_ip": "",
    "karoo_token": "",
    "hh_token": "",
    "hh_refresh_token": "",
    "hh_user_id": "",
    "hh_email": "",
    "hh_auto_sync": True,
}

DEFAULT_SETTINGS = {
    **DEFAULT_RIDER_SETTINGS,
    **DEFAULT_BIKE_SETTINGS,
    **DEFAULT_STRATEGY_SETTINGS,
    **DEFAULT_SYNC_SETTINGS,
}


def get_settings_file_path() -> str:
    """Returns the persistent file path for storing user settings across platforms."""
    if "POWER_PLANNER_SETTINGS_FILE" in os.environ and os.environ["POWER_PLANNER_SETTINGS_FILE"]:
        return os.environ["POWER_PLANNER_SETTINGS_FILE"]

    candidates = []
    if "FLET_APP_STORAGE_DATA" in os.environ and os.environ["FLET_APP_STORAGE_DATA"]:
        candidates.append(os.path.join(os.environ["FLET_APP_STORAGE_DATA"], "power_planner_settings.json"))

    if "PYTHON_USER_DATA_DIR" in os.environ and os.environ["PYTHON_USER_DATA_DIR"]:
        candidates.append(os.path.join(os.environ["PYTHON_USER_DATA_DIR"], "power_planner_settings.json"))

    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    if os.path.isdir(docs):
        candidates.append(os.path.join(docs, "power_planner_settings.json"))

    app_support = os.path.join(home, "Library", "Application Support", "PowerPlanner")
    candidates.append(os.path.join(app_support, "settings.json"))

    config_dir = os.path.join(home, ".config", "power_planner")
    candidates.append(os.path.join(config_dir, "settings.json"))

    candidates.append(os.path.join(home, ".power_planner_settings.json"))
    candidates.append(os.path.join(tempfile.gettempdir(), "power_planner_settings.json"))

    for path in candidates:
        try:
            d = os.path.dirname(path)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            with open(path, "a", encoding="utf-8"):
                pass
            return path
        except Exception:
            continue

    return os.path.join(tempfile.gettempdir(), "power_planner_settings.json")


def load_settings() -> dict:
    """Loads saved settings from persistent storage."""
    path = get_settings_file_path()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        print(f"[PowerPlanner] Settings load notice ({path}): {e}")
    return {}


def save_settings(state: dict) -> bool:
    """Saves current sliders, dropdowns and settings into persistent storage, separated into profile groups."""
    path = get_settings_file_path()
    try:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

        rider_data = {
            "initial_ftp": int(state.get("initial_ftp", DEFAULT_RIDER_SETTINGS["initial_ftp"])),
            "w_prime": int(state.get("w_prime", DEFAULT_RIDER_SETTINGS["w_prime"])),
            "rider_w": round(float(state.get("rider_w", DEFAULT_RIDER_SETTINGS["rider_w"])), 1),
        }
        bike_data = {
            "bike_w": round(float(state.get("bike_w", DEFAULT_BIKE_SETTINGS["bike_w"])), 1),
            "lowest_gear_key": str(state.get("lowest_gear_key", DEFAULT_BIKE_SETTINGS["lowest_gear_key"])),
            "highest_gear_key": str(state.get("highest_gear_key", DEFAULT_BIKE_SETTINGS["highest_gear_key"])),
            "min_climb_cadence": round(float(state.get("min_climb_cadence", DEFAULT_BIKE_SETTINGS["min_climb_cadence"])), 1),
            "max_pedal_cadence": round(float(state.get("max_pedal_cadence", DEFAULT_BIKE_SETTINGS["max_pedal_cadence"])), 1),
        }
        strategy_data = {
            "carbs_per_hour": int(state.get("carbs_per_hour", DEFAULT_STRATEGY_SETTINGS["carbs_per_hour"])),
            "target_f": round(float(state.get("target_f", DEFAULT_STRATEGY_SETTINGS["target_f"])), 2),
            "pacing_mode": str(state.get("pacing_mode", DEFAULT_STRATEGY_SETTINGS["pacing_mode"])),
            "gpx_path": str(state.get("gpx_path", DEFAULT_STRATEGY_SETTINGS["gpx_path"])),
            "language": str(state.get("language", DEFAULT_STRATEGY_SETTINGS["language"])),
        }
        sync_data = {
            "karoo_ip": str(state.get("karoo_ip", "")),
            "karoo_token": str(state.get("karoo_token", "")),
            "hh_token": str(state.get("hh_token", "")),
            "hh_refresh_token": str(state.get("hh_refresh_token", "")),
            "hh_user_id": str(state.get("hh_user_id", "")),
            "hh_email": str(state.get("hh_email", "")),
            "hh_auto_sync": bool(state.get("hh_auto_sync", True)),
        }

        # Sowohl strukturierte Profilgruppen (für zukünftige Multi-Profile)
        # als auch flache Keys für 100%ige Abwärtskompatibilität
        data = {
            "rider": rider_data,
            "bike": bike_data,
            "strategy": strategy_data,
            "sync": sync_data,
            **rider_data,
            **bike_data,
            **strategy_data,
            **sync_data,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[PowerPlanner] Settings save notice ({path}): {e}")
        return False


def apply_settings(state: dict, saved: dict):
    """Safely updates state with loaded persistent values (supports grouped and flat formats)."""
    if not isinstance(saved, dict):
        return

    # Extrahiere Gruppen falls vorhanden, sonst flach
    rider_src = saved.get("rider") if isinstance(saved.get("rider"), dict) else saved
    bike_src = saved.get("bike") if isinstance(saved.get("bike"), dict) else saved
    strat_src = saved.get("strategy") if isinstance(saved.get("strategy"), dict) else saved
    sync_src = saved.get("sync") if isinstance(saved.get("sync"), dict) else saved

    if "initial_ftp" in rider_src and isinstance(rider_src["initial_ftp"], (int, float)) and 100 <= rider_src["initial_ftp"] <= 500:
        state["initial_ftp"] = int(rider_src["initial_ftp"])
    if "w_prime" in rider_src and isinstance(rider_src["w_prime"], (int, float)) and 10000 <= rider_src["w_prime"] <= 30000:
        state["w_prime"] = int(rider_src["w_prime"])
    if "rider_w" in rider_src and isinstance(rider_src["rider_w"], (int, float)) and 40.0 <= rider_src["rider_w"] <= 130.0:
        state["rider_w"] = round(float(rider_src["rider_w"]), 1)

    if "bike_w" in bike_src and isinstance(bike_src["bike_w"], (int, float)) and 5.0 <= bike_src["bike_w"] <= 20.0:
        state["bike_w"] = round(float(bike_src["bike_w"]), 1)
    if "lowest_gear_key" in bike_src and bike_src["lowest_gear_key"] in GEAR_RATIOS_LOW:
        state["lowest_gear_key"] = bike_src["lowest_gear_key"]
        state["lowest_gear_ratio"] = GEAR_RATIOS_LOW[bike_src["lowest_gear_key"]][1]
    if "highest_gear_key" in bike_src and bike_src["highest_gear_key"] in GEAR_RATIOS_HIGH:
        state["highest_gear_key"] = bike_src["highest_gear_key"]
        state["highest_gear_ratio"] = GEAR_RATIOS_HIGH[bike_src["highest_gear_key"]][1]
    if "min_climb_cadence" in bike_src and isinstance(bike_src["min_climb_cadence"], (int, float)) and 60.0 <= bike_src["min_climb_cadence"] <= 90.0:
        state["min_climb_cadence"] = round(float(bike_src["min_climb_cadence"]), 1)
    if "max_pedal_cadence" in bike_src and isinstance(bike_src["max_pedal_cadence"], (int, float)) and 90.0 <= bike_src["max_pedal_cadence"] <= 125.0:
        state["max_pedal_cadence"] = round(float(bike_src["max_pedal_cadence"]), 1)

    if "carbs_per_hour" in strat_src and isinstance(strat_src["carbs_per_hour"], (int, float)) and 20 <= strat_src["carbs_per_hour"] <= 120:
        state["carbs_per_hour"] = int(strat_src["carbs_per_hour"])
    if "target_f" in strat_src and isinstance(strat_src["target_f"], (int, float)) and 0.60 <= strat_src["target_f"] <= 1.00:
        state["target_f"] = round(float(strat_src["target_f"]), 2)
    if "pacing_mode" in strat_src and strat_src["pacing_mode"] in ("dynamic", "steady"):
        state["pacing_mode"] = strat_src["pacing_mode"]
    if "language" in strat_src and strat_src["language"] in SUPPORTED_LANGUAGES:
        state["language"] = strat_src["language"]
        set_language(state["language"])
    elif "language" in saved and saved["language"] in SUPPORTED_LANGUAGES:
        state["language"] = saved["language"]
        set_language(state["language"])
    if "gpx_path" in strat_src and isinstance(strat_src["gpx_path"], str) and strat_src["gpx_path"]:
        resolved = resolve_path(strat_src["gpx_path"])
        if resolved and os.path.exists(resolved):
            state["gpx_path"] = strat_src["gpx_path"]
            state["base_filename"] = os.path.splitext(os.path.basename(strat_src["gpx_path"]))[0]

    if "karoo_ip" in sync_src and isinstance(sync_src["karoo_ip"], str):
        state["karoo_ip"] = sync_src["karoo_ip"]
    if "karoo_token" in sync_src and isinstance(sync_src["karoo_token"], str):
        state["karoo_token"] = sync_src["karoo_token"]
    if "hh_token" in sync_src and isinstance(sync_src["hh_token"], str):
        state["hh_token"] = sync_src["hh_token"]
    if "hh_refresh_token" in sync_src and isinstance(sync_src["hh_refresh_token"], str):
        state["hh_refresh_token"] = sync_src["hh_refresh_token"]
    if "hh_user_id" in sync_src and isinstance(sync_src["hh_user_id"], str):
        state["hh_user_id"] = sync_src["hh_user_id"]
    if "hh_email" in sync_src and isinstance(sync_src["hh_email"], str):
        state["hh_email"] = sync_src["hh_email"]
    if "hh_auto_sync" in sync_src and isinstance(sync_src["hh_auto_sync"], bool):
        state["hh_auto_sync"] = sync_src["hh_auto_sync"]


# ==========================================
# MAIN FLET APPLICATION CONTROLLER
# ==========================================

async def main(page: ft.Page):
    page.title = t("app.title")
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    page.scroll = None
    page.window.min_width = 380
    page.window.min_height = 650

    def show_snack(text: str, bgcolor=ft.Colors.GREEN_700, icon=None):
        page.show_dialog(
            ft.SnackBar(
                content=ft.Row([
                    ft.Icon(icon, color=ft.Colors.WHITE, size=18) if icon else ft.Container(width=0),
                    ft.Text(text, color=ft.Colors.WHITE, weight=ft.FontWeight.W_500, expand=True)
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=bgcolor,
                duration=ft.Duration(seconds=4),
                show_close_icon=True
            )
        )

    def show_help_dialog(title: str, text: str):
        dlg = ft.AlertDialog(
            modal=False,
            title=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.AMBER_400, size=22),
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, expand=True),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(text, size=13, color=ft.Colors.GREY_300, selectable=True),
                ], tight=True, spacing=8),
                width=420,
            ),
            actions=[
                ft.TextButton(t("dialog.close"), on_click=lambda _: page.pop_dialog()),
            ],
        )
        page.show_dialog(dlg)

    def open_full_help_dialog(_=None):
        guide_sections = get_guide_sections(state.get("language"))

        dlg = ft.AlertDialog(
            modal=False,
            title=ft.Row([
                ft.Icon(ft.Icons.HELP_OUTLINE, color=ft.Colors.AMBER_400, size=24),
                ft.Text(t("dialog.help_title"), size=17, weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(t("dialog.help_subtitle"), size=12, color=ft.Colors.GREY_400),
                    ft.Divider(height=10, color=ft.Colors.GREY_800),
                    *[
                        ft.Container(
                            content=ft.Column([
                                ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300),
                                ft.Text(body, size=12, color=ft.Colors.GREY_300),
                            ], spacing=4),
                            padding=ft.Padding.only(bottom=8),
                        )
                        for title, body in guide_sections
                    ],
                ], scroll=ft.ScrollMode.AUTO, spacing=10),
                width=480,
                height=420,
            ),
            actions=[
                ft.TextButton(t("dialog.close"), on_click=lambda _: page.pop_dialog()),
            ],
        )
        page.show_dialog(dlg)

    # Application State
    state = dict(DEFAULT_SETTINGS)
    state.update({
        "gpx_content": None,
        "base_filename": os.path.splitext(os.path.basename(DEFAULT_SETTINGS["gpx_path"]))[0],
        "df_route": None,
        "calc": None,
        "logs": [],
        "lowest_gear_ratio": GEAR_RATIOS_LOW[DEFAULT_SETTINGS["lowest_gear_key"]][1],
        "highest_gear_ratio": GEAR_RATIOS_HIGH[DEFAULT_SETTINGS["highest_gear_key"]][1],
        "wheel_circumference_m": 2.12,
    })
    apply_settings(state, load_settings())
    if "language" in state:
        set_language(state["language"])
    page.title = t("app.title")

    def format_chip_route(path):
        base = os.path.splitext(os.path.basename(path))[0]
        words = base.replace("-", " ").replace("_", " ").split()
        title = " ".join(w.capitalize() for w in words)
        return title[:12] + "…" if len(title) > 13 else title

    # ----------------------------------------------------
    # Calculation & Chart Rendering Engine (Ultra-Fast)
    # ----------------------------------------------------
    elevation_progress_bar = ft.ProgressBar(width=340, value=0.0, color=ft.Colors.TEAL_400, bgcolor=ft.Colors.GREY_800)
    elevation_progress_text = ft.Text(t("dialog.elevation_connecting"), size=12, color=ft.Colors.GREY_300)
    elevation_dialog_desc = ft.Text(t("dialog.elevation_desc"), size=13, color=ft.Colors.GREY_400)
    elevation_dialog_title = ft.Text(t("dialog.elevation_title"), size=16, weight=ft.FontWeight.BOLD)
    elevation_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Icon(ft.Icons.TERRAIN, color=ft.Colors.TEAL_400, size=24),
            elevation_dialog_title,
        ], spacing=10),
        content=ft.Container(
            content=ft.Column([
                elevation_dialog_desc,
                ft.Container(height=6),
                elevation_progress_text,
                ft.Container(height=4),
                elevation_progress_bar,
            ], spacing=6, tight=True),
            width=380,
            padding=10
        )
    )

    state["is_elevation_dialog_open"] = False

    def on_elevation_progress(fraction: float, message: str):
        if not state.get("is_elevation_dialog_open", False):
            state["is_elevation_dialog_open"] = True
            page.show_dialog(elevation_dialog)
        elevation_progress_bar.value = max(0.0, min(1.0, fraction))
        elevation_progress_text.value = message
        page.update()

    def close_elevation_dialog():
        if state.get("is_elevation_dialog_open", False):
            page.pop_dialog()
            state["is_elevation_dialog_open"] = False
            page.update()

    def run_calculation():
        try:
            optimizer = AdvancedPacingOptimizer(
                initial_ftp=state["initial_ftp"],
                w_prime_max=state["w_prime"],
                target_factor=state["target_f"],
                carb_intake_per_hour=state["carbs_per_hour"],
                rider_weight=state["rider_w"],
                bike_weight=state["bike_w"],
                lowest_gear_ratio=state.get("lowest_gear_ratio", 33.0 / 34.0),
                highest_gear_ratio=state.get("highest_gear_ratio", 46.0 / 10.0),
                min_climb_cadence=state.get("min_climb_cadence", 75.0),
                max_pedal_cadence=state.get("max_pedal_cadence", 105.0),
                wheel_circumference_m=state.get("wheel_circumference_m", 2.12),
                pacing_mode=state.get("pacing_mode", "dynamic"),
            )
            if state["df_route"] is None:
                source = state.get("gpx_content") or resolve_path(state["gpx_path"])
                try:
                    state["df_route"] = optimizer.parse_gpx(source, progress_callback=on_elevation_progress)
                finally:
                    close_elevation_dialog()
                state["elevation_source"] = getattr(optimizer, "elevation_source", "gpx")
                state["elevation_error"] = getattr(optimizer, "elevation_error", None)
            df_route = state["df_route"]
            df_raw = optimizer.generate_raw_pacing_dataframe(df_route)
            df_intervals = optimizer._segment_intervals(df_raw)
            
            total_sec = df_raw['duration_sec'].sum()
            total_hours = total_sec / 3600.0
            h = math.floor(total_hours)
            m = round((total_hours % 1) * 60)
            sys_weight = state["rider_w"] + state["bike_w"]
            rel_ftp = state["initial_ftp"] / state["rider_w"]
            total_carbs = total_hours * state["carbs_per_hour"]

            # Duration-weighted average target power
            avg_target_power = float((df_raw['target_power'] * df_raw['duration_sec']).sum() / total_sec) if total_sec > 0 else 0.0

            # Normalized Power (NP)
            normalized_power = optimizer.calculate_normalized_power(df_raw) if hasattr(optimizer, "calculate_normalized_power") else avg_target_power

            total_km = float(df_raw['distance_km'].iloc[-1]) if not df_raw.empty else 0.0
            if 'elevation' in df_route.columns and not df_route['elevation'].isna().all():
                pos_ele = float(df_route['elevation'].diff().clip(lower=0).sum())
            else:
                pos_ele = float((df_route['slope'].clip(lower=0) * (df_route['segment_len_m'] / 100.0)).sum())

            pos_ele_str = f"{int(pos_ele):,} Hm".replace(",", ".") if pos_ele >= 1000 else f"{int(pos_ele)} Hm"

            state["calc"] = {
                "optimizer": optimizer,
                "df_raw": df_raw,
                "df_intervals": df_intervals,
                "total_hours": total_hours,
                "duration_str": f"{h:02d}:{m:02d} Std",
                "sys_weight_str": f"{sys_weight:.1f} kg",
                "rel_ftp_str": f"{rel_ftp:.2f} W/kg",
                "total_carbs_str": f"{total_carbs:.1f} g",
                "avg_power_str": f"{round(avg_target_power)} W",
                "np_str": f"{round(normalized_power)} W",
                "total_km": total_km,
                "pos_ele": pos_ele,
                "pos_ele_str": pos_ele_str,
            }
            return True, None
        except Exception as e:
            return False, str(e)

    def get_karoo_json():
        if state.get("karoo_json_str") is None and state.get("calc"):
            optimizer = state["calc"]["optimizer"]
            df_route = state["df_route"]
            state["karoo_json_str"] = optimizer.export_to_karoo_json(df_route, route_name=state["base_filename"])
        return state.get("karoo_json_str", "{}")

    def render_route_map():
        if not state["calc"] or state["df_route"] is None:
            return ""
        df_route = state["df_route"]
        if 'latitude' not in df_route.columns or 'longitude' not in df_route.columns:
            return ""

        min_lat, max_lat = df_route['latitude'].min(), df_route['latitude'].max()
        min_lon, max_lon = df_route['longitude'].min(), df_route['longitude'].max()

        # Always use the light topographic map as requested, even in dark mode
        bg_img, extent = fetch_map_background(min_lat, max_lat, min_lon, max_lon, zoom=None, is_dark=False)

        fig = plt.figure(figsize=(10, 5.2), dpi=110)
        ax = fig.add_axes([0, 0, 1, 1])
        fig.patch.set_facecolor('#FFFFFF')
        ax.set_facecolor('#F8FAFC')

        if bg_img and extent:
            ax.imshow(bg_img, extent=extent, aspect='equal', origin='upper')

        # High-contrast route line (white halo + warm amber line)
        ax.plot(df_route['longitude'], df_route['latitude'], color='#FFFFFF', linewidth=4.5, alpha=0.9, zorder=3)
        ax.plot(df_route['longitude'], df_route['latitude'], color='#D97706', linewidth=2.8, alpha=0.95, zorder=4)

        # Automatic detection and annotation of significant mountain passes
        if 'elevation' in df_route.columns and (df_route['elevation'].max() - df_route['elevation'].min() > 80):
            elev = df_route['elevation'].values
            n_pts = len(elev)
            w = max(5, n_pts // 100)
            smooth = pd.Series(elev).rolling(window=w, center=True).mean().bfill().ffill().values
            min_prom = max(120.0, (elev.max() - elev.min()) * 0.12)
            min_dist = max(10, n_pts // 25)

            candidates = [i for i in range(1, n_pts - 1) if smooth[i] > smooth[i - 1] and smooth[i] >= smooth[i + 1]]
            peak_indices = []
            for idx in sorted(candidates, key=lambda i: smooth[i], reverse=True):
                if any(abs(idx - chosen) < min_dist for chosen in peak_indices):
                    continue
                start = max(0, idx - min_dist)
                end = min(n_pts, idx + min_dist)
                if smooth[idx] - np.min(smooth[start:end]) >= min_prom:
                    peak_indices.append(idx)
            peak_indices.sort()

            span_lon = max_lon - min_lon
            for p_idx in peak_indices:
                plat = df_route.iloc[p_idx]['latitude']
                plon = df_route.iloc[p_idx]['longitude']
                pele = df_route.iloc[p_idx]['elevation']

                pass_name = None
                for k_lat, k_lon, k_name in KNOWN_PASSES:
                    if (plat - k_lat) ** 2 + (plon - k_lon) ** 2 < 0.04 ** 2:
                        pass_name = k_name
                        break

                ele_str = f"{int(round(pele)):,}".replace(',', '.')
                label = f"▲ {pass_name} ({ele_str} m)" if pass_name else f"▲ {ele_str} m"

                # Smart horizontal alignment to avoid clipping near map edges
                if span_lon > 0 and plon > max_lon - span_lon * 0.15:
                    ha, offset = 'right', (-10, 10)
                elif span_lon > 0 and plon < min_lon + span_lon * 0.15:
                    ha, offset = 'left', (10, 10)
                else:
                    ha, offset = 'center', (0, 12)

                ax.scatter(plon, plat, color='#EA580C', s=55, zorder=7, edgecolors='#FFFFFF', linewidths=1.8)
                ax.annotate(
                    label,
                    xy=(plon, plat),
                    xytext=offset,
                    textcoords='offset points',
                    fontsize=8.5,
                    fontweight='bold',
                    color='#9A3412',
                    ha=ha,
                    va='bottom',
                    zorder=8,
                    bbox=dict(boxstyle='round,pad=0.35', facecolor='#FFFFFF', edgecolor='#FB923C', alpha=0.92, linewidth=1.2)
                )

        # Start and Ziel badges
        s_lon, s_lat = df_route['longitude'].iloc[0], df_route['latitude'].iloc[0]
        e_lon, e_lat = df_route['longitude'].iloc[-1], df_route['latitude'].iloc[-1]
        is_loop = ((s_lon - e_lon) ** 2 + (s_lat - e_lat) ** 2) < 0.015 ** 2

        if is_loop:
            ax.scatter(s_lon, s_lat, color='#059669', s=70, zorder=7, edgecolors='#FFFFFF', linewidths=2.0)
            ax.annotate(
                'Start / Ziel',
                xy=(s_lon, s_lat),
                xytext=(14, 0),
                textcoords='offset points',
                fontsize=9,
                fontweight='bold',
                color='#065F46',
                ha='left',
                va='center',
                zorder=8,
                bbox=dict(boxstyle='round,pad=0.35', facecolor='#ECFDF5', edgecolor='#10B981', alpha=0.95, linewidth=1.2)
            )
        else:
            ax.scatter(s_lon, s_lat, color='#059669', s=70, zorder=7, edgecolors='#FFFFFF', linewidths=2.0)
            ax.annotate('Start', xy=(s_lon, s_lat), xytext=(12, 0), textcoords='offset points', fontsize=9, fontweight='bold', color='#065F46', ha='left', va='center', zorder=8, bbox=dict(boxstyle='round,pad=0.3', facecolor='#ECFDF5', edgecolor='#10B981', alpha=0.95, linewidth=1.2))
            ax.scatter(e_lon, e_lat, color='#DC2626', s=70, zorder=7, edgecolors='#FFFFFF', linewidths=2.0)
            ax.annotate('Ziel', xy=(e_lon, e_lat), xytext=(12, 0), textcoords='offset points', fontsize=9, fontweight='bold', color='#991B1B', ha='left', va='center', zorder=8, bbox=dict(boxstyle='round,pad=0.3', facecolor='#FEF2F2', edgecolor='#EF4444', alpha=0.95, linewidth=1.2))

        # View boundaries with comfortable margin
        pad_lon = (max_lon - min_lon) * 0.06 if max_lon > min_lon else 0.02
        pad_lat = (max_lat - min_lat) * 0.08 if max_lat > min_lat else 0.02
        ax.set_xlim(min_lon - pad_lon, max_lon + pad_lon)
        ax.set_ylim(min_lat - pad_lat, max_lat + pad_lat)

        # Discreet attribution
        ax.text(0.012, 0.015, '© Esri Topo · OpenStreetMap', transform=ax.transAxes, color='#4B5563', fontsize=7.5, alpha=0.75, zorder=9, bbox=dict(boxstyle='round,pad=0.25', facecolor='#FFFFFF', edgecolor='none', alpha=0.65))

        # Borderless, clean card presentation without coordinate frames
        ax.set_axis_off()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0, facecolor=fig.get_facecolor())
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    def render_elevation_chart():
        if not state["calc"]:
            return ""
        df_raw = state["calc"]["df_raw"]
        df_route = state["df_route"]
        
        is_dark = page.theme_mode == ft.ThemeMode.DARK
        bg_color = '#18181B' if is_dark else '#FFFFFF'
        plot_bg = '#1E1E24' if is_dark else '#F9FAFB'
        text_color = '#E4E4E7' if is_dark else '#1F2937'
        tick_color = '#A1A1AA' if is_dark else '#6B7280'
        grid_color = '#333338' if is_dark else '#E5E7EB'

        fig, ax1 = plt.subplots(figsize=(10, 3.8), dpi=100)
        fig.patch.set_facecolor(bg_color)
        ax1.set_facecolor(plot_bg)

        # Fast step-fill for target power (40x faster than individual bars)
        ax1.fill_between(df_raw['distance_km'], df_raw['target_power'], step='mid', color='#F59E0B', alpha=0.55, label=t('chart.target_power_watt'), rasterized=True)
        ax1.set_xlabel(t('chart.dist_km'), color=text_color, fontsize=9, fontweight='bold')
        ax1.set_ylabel(t('chart.target_power_watt'), color='#F59E0B', fontsize=9, fontweight='bold')
        ax1.tick_params(colors=tick_color, labelsize=8)
        ax1.set_ylim(0, max(450, int(state["initial_ftp"] * 1.4)))
        ax1.grid(True, linestyle='--', alpha=0.25, color=grid_color)

        # Elevation profile
        ax2 = ax1.twinx()
        if 'elevation' in df_route.columns and not df_route['elevation'].isna().all():
            y_ele = df_route['elevation']
        else:
            y_ele = (df_route['slope'] * (df_route['segment_len_m'] / 100.0)).cumsum() + 1377

        ax2.plot(df_route['distance_km'], y_ele, color='#38BDF8', linewidth=2.0, label=t('chart.elevation_label'))
        ax2.fill_between(df_route['distance_km'], y_ele, alpha=0.15, color='#38BDF8', rasterized=True)
        ax2.set_ylabel(t('chart.elevation_m'), color='#38BDF8', fontsize=9, fontweight='bold')
        ax2.tick_params(colors=tick_color, labelsize=8)

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    def render_energy_chart():
        if not state["calc"]:
            return ""
        df_raw = state["calc"]["df_raw"]

        is_dark = page.theme_mode == ft.ThemeMode.DARK
        bg_color = '#18181B' if is_dark else '#FFFFFF'
        plot_bg = '#1E1E24' if is_dark else '#F9FAFB'
        text_color = '#E4E4E7' if is_dark else '#1F2937'
        tick_color = '#A1A1AA' if is_dark else '#6B7280'
        grid_color = '#333338' if is_dark else '#E5E7EB'

        fig, ax = plt.subplots(figsize=(10, 3.4), dpi=100)
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(plot_bg)

        ax.plot(df_raw['distance_km'], df_raw['w_prime_pct'], color='#EF4444', linewidth=2.0, label=t("chart.w_prime_label"))
        ax.plot(df_raw['distance_km'], df_raw['glycogen_pct'], color='#10B981', linewidth=2.2, linestyle='--', label=t('chart.glycogen_label'))
        if 'effective_ftp_pct' in df_raw.columns:
            ax.plot(df_raw['distance_km'], df_raw['effective_ftp_pct'], color='#A855F7', linewidth=1.8, linestyle='-.', label=t('chart.effective_ftp_label'))
        
        ax.set_xlabel(t('chart.dist_km'), color=text_color, fontsize=9, fontweight='bold')
        ax.set_ylabel(t('chart.storage_pct'), color=text_color, fontsize=9, fontweight='bold')
        ax.set_ylim(0, 105)
        ax.tick_params(colors=tick_color, labelsize=8)
        ax.grid(True, linestyle='--', alpha=0.25, color=grid_color)
        ax.legend(facecolor=plot_bg, edgecolor=grid_color, labelcolor=text_color, loc='lower left', fontsize=8.5)

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    # Initial Calculation
    run_calculation()

    # ----------------------------------------------------
    # UI Component Builders
    # ----------------------------------------------------

    # Pace Traffic Light Label & Coach Pill
    pace_badge_text = ft.Text(size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
    pace_badge_subtext = ft.Text(size=10, color=ft.Colors.GREY_400, text_align=ft.TextAlign.CENTER)
    pace_badge = ft.Container(
        content=ft.Column([
            pace_badge_text,
            pace_badge_subtext,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=12,
        alignment=ft.Alignment(0, 0),
    )

    def update_pace_badge():
        tf = state["target_f"]
        pct = int(tf * 100)
        if tf < 0.71:
            pace_badge_text.value = t("pace.very_defensive_title", pct=pct)
            pace_badge_subtext.value = t("pace.very_defensive_sub")
            pace_badge.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.GREEN)
            pace_badge.border = ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.GREEN))
        elif tf < 0.78:
            pace_badge_text.value = t("pace.solid_endurance_title", pct=pct)
            pace_badge_subtext.value = t("pace.solid_endurance_sub")
            pace_badge.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.GREEN)
            pace_badge.border = ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.GREEN))
        elif tf < 0.84:
            pace_badge_text.value = t("pace.ambitious_title", pct=pct)
            pace_badge_subtext.value = t("pace.ambitious_sub")
            pace_badge.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.AMBER)
            pace_badge.border = ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.AMBER))
        else:
            pace_badge_text.value = t("pace.race_title", pct=pct)
            pace_badge_subtext.value = t("pace.race_sub")
            pace_badge.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.RED)
            pace_badge.border = ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.RED))

    update_pace_badge()

    # GI / Carbohydrate Absorption Feedback Badge
    gi_badge_text = ft.Text(size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
    gi_badge_subtext = ft.Text(size=10, color=ft.Colors.GREY_400, text_align=ft.TextAlign.CENTER)
    gi_badge = ft.Container(
        content=ft.Column([
            gi_badge_text,
            gi_badge_subtext,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=12,
        alignment=ft.Alignment(0, 0),
    )

    def update_gi_badge():
        carbs = int(state.get("carbs_per_hour", 90))
        if carbs <= 80:
            gi_badge_text.value = t("gi.friendly_title", carbs=carbs)
            gi_badge_subtext.value = t("gi.friendly_sub")
            gi_badge.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.GREEN)
            gi_badge.border = ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.GREEN))
        elif carbs <= 95:
            gi_badge_text.value = t("gi.limit_title", carbs=carbs)
            gi_badge_subtext.value = t("gi.limit_sub")
            gi_badge.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.AMBER)
            gi_badge.border = ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.AMBER))
        else:
            gi_badge_text.value = t("gi.risk_title", carbs=carbs)
            gi_badge_subtext.value = t("gi.risk_sub")
            gi_badge.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.RED)
            gi_badge.border = ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.RED))

    update_gi_badge()

    # Gearing & Cadence Feedback Badge
    gearing_badge_climb_speed = ft.Text(size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE_200)
    gearing_badge_descent_speed = ft.Text(size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE_200)
    gearing_badge_climb_lbl = ft.Text(t("gearing.climb_speed"), size=11, color=ft.Colors.GREY_300)
    gearing_badge_descent_lbl = ft.Text(t("gearing.descent_speed"), size=11, color=ft.Colors.GREY_300)
    gearing_badge = ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Icon(ft.Icons.TRENDING_UP, size=15, color=ft.Colors.PURPLE_400),
                gearing_badge_climb_lbl,
                gearing_badge_climb_speed,
            ], spacing=5),
            ft.Row([
                ft.Icon(ft.Icons.TRENDING_DOWN, size=15, color=ft.Colors.DEEP_PURPLE_400),
                gearing_badge_descent_lbl,
                gearing_badge_descent_speed,
            ], spacing=5),
        ], alignment=ft.MainAxisAlignment.SPACE_AROUND, wrap=True),
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PURPLE),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.25, ft.Colors.PURPLE)),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=10,
    )

    def update_gearing_badge():
        circ = state.get("wheel_circumference_m", 2.12)
        low_ratio = state.get("lowest_gear_ratio", 33.0 / 34.0)
        high_ratio = state.get("highest_gear_ratio", 46.0 / 10.0)
        min_cad = state.get("min_climb_cadence", 75.0)
        max_cad = state.get("max_pedal_cadence", 105.0)

        min_speed = min_cad * low_ratio * circ * 60.0 / 1000.0
        max_speed = max_cad * high_ratio * circ * 60.0 / 1000.0

        gearing_badge_climb_speed.value = f"{min_speed:.1f} km/h"
        gearing_badge_descent_speed.value = f"{max_speed:.1f} km/h"
        gearing_badge_climb_lbl.value = t("gearing.climb_speed")
        gearing_badge_descent_lbl.value = t("gearing.descent_speed")

    update_gearing_badge()

    # Dynamic KPI Controls for all 3 Tabs (Dauer, Systemgewicht, Rel. FTP, ø Leistung, Normalisierte Leistung, Gesamtanstieg)
    def create_tab_kpi_controls():
        return {
            "time": ft.Text(state["calc"]["duration_str"] if state["calc"] else "-", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400),
            "weight": ft.Text(state["calc"]["sys_weight_str"] if state["calc"] else "-", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_400),
            "rel_ftp": ft.Text(state["calc"]["rel_ftp_str"] if state["calc"] else "-", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
            "avg_power": ft.Text(state["calc"]["avg_power_str"] if state["calc"] else "-", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.LIGHT_BLUE_400),
            "np": ft.Text(state["calc"]["np_str"] if state["calc"] else "-", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_400),
            "ele": ft.Text(state["calc"]["pos_ele_str"] if state["calc"] else "-", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE_400),
        }

    kpi_controls_t1 = create_tab_kpi_controls()
    kpi_controls_t2 = create_tab_kpi_controls()
    kpi_controls_t3 = create_tab_kpi_controls()
    all_kpi_sets = [kpi_controls_t1, kpi_controls_t2, kpi_controls_t3]

    # Backward-compatible references (for any older code or tests)
    kpi_time = kpi_controls_t2["time"]
    kpi_weight = kpi_controls_t2["weight"]
    kpi_rel_ftp = kpi_controls_t2["rel_ftp"]
    kpi_carbs = ft.Text(state["calc"]["total_carbs_str"] if state["calc"] else "-", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE_400)
    hero_kpi_time = kpi_controls_t1["time"]
    hero_kpi_power = kpi_controls_t1["avg_power"]
    hero_kpi_rel_ftp = kpi_controls_t1["rel_ftp"]
    hero_kpi_carbs = kpi_carbs

    # Route summary badges for Setup Tab Route Card
    route_dist_badge = ft.Text(f"{state['calc']['total_km']:.1f} km" if state["calc"] and "total_km" in state["calc"] else "-", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)
    route_ele_badge = ft.Text(f"{int(state['calc']['pos_ele'])} hm" if state["calc"] and "pos_ele" in state["calc"] else "-", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.LIGHT_BLUE_400)
    route_name_badge = ft.Text(os.path.basename(state['gpx_path']), size=13, weight=ft.FontWeight.BOLD, no_wrap=True)

    # Headline Badges & Profile Summaries
    rider_chip_text = ft.Text(f"{state['initial_ftp']} W", size=11, weight=ft.FontWeight.BOLD)
    rider_chip = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.PERSON, size=14, color=ft.Colors.AMBER_400),
            rider_chip_text,
        ], spacing=4, alignment=ft.MainAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.AMBER),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.28, ft.Colors.AMBER)),
        tooltip=t("appbar.rider_tooltip"),
        on_click=lambda _: open_rider_settings_dialog(),
    )

    bike_chip_text = ft.Text(f"{state['bike_w']:.1f} kg", size=11, weight=ft.FontWeight.BOLD)
    bike_chip = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.DIRECTIONS_BIKE, size=14, color=ft.Colors.CYAN_400),
            bike_chip_text,
        ], spacing=4, alignment=ft.MainAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.CYAN),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.28, ft.Colors.CYAN)),
        tooltip=t("appbar.bike_tooltip"),
        on_click=lambda _: open_bike_settings_dialog(),
    )

    route_status_chip_text = ft.Text(format_chip_route(state['gpx_path']), size=11, weight=ft.FontWeight.W_600)
    route_status_chip = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.LOCATION_ON, size=13, color=ft.Colors.LIGHT_BLUE_400),
            route_status_chip_text,
        ], spacing=3, alignment=ft.MainAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.LIGHT_BLUE),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.28, ft.Colors.LIGHT_BLUE)),
        tooltip=t("appbar.route_tooltip"),
        on_click=lambda _: open_route_picker_dialog(),
    )

    rider_summary_text = ft.Text(f"{state['initial_ftp']} W · {state['rider_w']:.1f} kg", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)
    rel_w = state['initial_ftp'] / state['rider_w'] if state['rider_w'] > 0 else 0
    rider_summary_subtext = ft.Text(f"{t('profile.w_prime_battery')}: {state['w_prime']:,} J · {t('profile.rel')}: {rel_w:.2f} W/kg", size=11, color=ft.Colors.GREY_400)

    bike_summary_text = ft.Text(f"{state['bike_w']:.1f} kg · {state['lowest_gear_key']}–{state['highest_gear_key']}", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_400)
    bike_summary_subtext = ft.Text(f"{t('profile.cadence')}: {int(state['min_climb_cadence'])}–{int(state['max_pedal_cadence'])} rpm", size=11, color=ft.Colors.GREY_400)

    def update_profile_summaries():
        rider_chip_text.value = f"{state['initial_ftp']} W"
        bike_chip_text.value = f"{state['bike_w']:.1f} kg"
        route_status_chip_text.value = format_chip_route(state['gpx_path'])
        route_status_chip.tooltip = t("appbar.route_tooltip")
        rider_summary_text.value = f"{state['initial_ftp']} W · {state['rider_w']:.1f} kg"
        rel_calc = state['initial_ftp'] / state['rider_w'] if state['rider_w'] > 0 else 0
        rider_summary_subtext.value = f"{t('profile.w_prime_battery')}: {state['w_prime']:,} J · {t('profile.rel')}: {rel_calc:.2f} W/kg"
        bike_summary_text.value = f"{state['bike_w']:.1f} kg · {state['lowest_gear_key']}–{state['highest_gear_key']}"
        bike_summary_subtext.value = f"{t('profile.cadence')}: {int(state['min_climb_cadence'])}–{int(state['max_pedal_cadence'])} rpm"

    kpi_section_refs = []

    def make_kpi_card(icon, label, value_control, color, tooltip=None, col_span={"xs": 6, "sm": 4, "md": 2}):
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Container(
                        content=ft.Icon(icon, size=13, color=color),
                        bgcolor=ft.Colors.with_opacity(0.18, color),
                        padding=3,
                        border_radius=6,
                    ),
                    ft.Text(label, size=11, color=ft.Colors.GREY_300, weight=ft.FontWeight.W_500, expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
                ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                value_control
            ], spacing=2, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            height=68,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            border_radius=14,
            bgcolor=ft.Colors.with_opacity(0.10, color) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.05, color),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.22, color) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.12, color)),
            tooltip=tooltip,
            col=col_span,
        )

    def build_kpi_overview_section(ctrls):
        header_title = ft.Text(t("kpi.section_title"), size=15, weight=ft.FontWeight.BOLD, expand=True)
        time_card = make_kpi_card(ft.Icons.TIMER_OUTLINED, t("kpi.time"), ctrls["time"], ft.Colors.AMBER_400, tooltip=t("kpi.time_tooltip"))
        weight_card = make_kpi_card(ft.Icons.FITNESS_CENTER_OUTLINED, t("kpi.weight"), ctrls["weight"], ft.Colors.BLUE_400, tooltip=t("kpi.weight_tooltip"))
        rel_ftp_card = make_kpi_card(ft.Icons.SPEED, t("kpi.rel_ftp"), ctrls["rel_ftp"], ft.Colors.GREEN_400, tooltip=t("kpi.rel_ftp_tooltip"))
        avg_power_card = make_kpi_card(ft.Icons.BOLT, t("kpi.avg_power"), ctrls["avg_power"], ft.Colors.LIGHT_BLUE_400, tooltip=t("kpi.avg_power_tooltip"))
        np_card = make_kpi_card(ft.Icons.SHOW_CHART, t("kpi.np"), ctrls["np"], ft.Colors.ORANGE_400, tooltip=t("kpi.np_tooltip"))
        ele_card = make_kpi_card(ft.Icons.LANDSCAPE, t("kpi.elevation"), ctrls["ele"], ft.Colors.PURPLE_400, tooltip=t("kpi.elevation_tooltip"))

        kpi_section_refs.append({
            "header_title": header_title,
            "time_card": time_card,
            "weight_card": weight_card,
            "rel_ftp_card": rel_ftp_card,
            "avg_power_card": avg_power_card,
            "np_card": np_card,
            "ele_card": ele_card,
        })

        return ft.Column([
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.BAR_CHART, size=16, color=ft.Colors.AMBER_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.AMBER),
                    border_radius=8,
                    padding=6,
                ),
                header_title,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.ResponsiveRow([
                time_card,
                weight_card,
                rel_ftp_card,
                avg_power_card,
                np_card,
                ele_card,
            ], spacing=8, run_spacing=8),
        ], spacing=10)

    # Chart Controls
    img_map = ft.Image(src=render_route_map(), fit=ft.BoxFit.CONTAIN, border_radius=8)
    img_elevation = ft.Image(src=render_elevation_chart(), fit=ft.BoxFit.CONTAIN, border_radius=8)
    img_energy = ft.Image(src=render_energy_chart(), fit=ft.BoxFit.CONTAIN, border_radius=8)

    # Interval DataTable Builder
    intervals_column = ft.Column(scroll=ft.ScrollMode.ADAPTIVE, spacing=8)

    def build_intervals_table():
        if not state["calc"]:
            return ft.Text("Keine Intervalldaten vorhanden.")
        df_inv = state["calc"]["df_intervals"]

        rows = []
        for _, row in df_inv.iterrows():
            pct = float(row['pct_ftp'])
            if pct < 55:
                z_color, z_name = ft.Colors.BLUE_GREY_400, "Z1 Recovery"
            elif pct < 75:
                z_color, z_name = ft.Colors.LIGHT_BLUE_400, "Z2 Endurance"
            elif pct < 90:
                z_color, z_name = ft.Colors.GREEN_400, "Z3 Tempo"
            elif pct < 105:
                z_color, z_name = ft.Colors.AMBER_400, "Z4 Threshold"
            elif pct < 120:
                z_color, z_name = ft.Colors.ORANGE_400, "Z5 VO2Max"
            else:
                z_color, z_name = ft.Colors.RED_400, "Z6 Anaerobic"

            dur_str = format_to_iso_duration(row['duration_min'])
            dist_km = row['end_km'] - row['start_km']
            rows.append(
                ft.Container(
                    content=ft.Row([
                        ft.Container(width=4, height=42, bgcolor=z_color, border_radius=2),
                        ft.Column([
                            ft.Row([
                                ft.Text(f"{row['start_km']:.1f} – {row['end_km']:.1f} km", size=13, weight=ft.FontWeight.BOLD),
                                ft.Text(f"({dist_km:.1f} km)", size=11, color=ft.Colors.GREY_400),
                            ], spacing=4),
                            ft.Text(f"⏱️ {dur_str}", size=11, color=ft.Colors.GREY_400),
                        ], spacing=2, expand=True),
                        ft.Column([
                            ft.Text(f"{int(row['target_watt'])} W", size=15, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT),
                            ft.Container(
                                content=ft.Text(f"{z_name} ({pct:.0f}%)", size=10, weight=ft.FontWeight.BOLD, color=z_color),
                                bgcolor=ft.Colors.with_opacity(0.12, z_color),
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border_radius=6,
                            )
                        ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END)
                    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    border_radius=12,
                    bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.02, ft.Colors.BLACK),
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.06, ft.Colors.WHITE) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.06, ft.Colors.BLACK)),
                )
            )
        return ft.Column(rows, spacing=8)

    intervals_column.controls = [build_intervals_table()]

    def refresh_ui(route_changed=False, force_charts=False):
        state["karoo_json_str"] = None  # Invalidate lazy Karoo JSON on changes
        success, err = run_calculation()
        if success and state["calc"]:
            calc = state["calc"]
            for ctrls in all_kpi_sets:
                ctrls["time"].value = calc["duration_str"]
                ctrls["weight"].value = calc["sys_weight_str"]
                ctrls["rel_ftp"].value = calc["rel_ftp_str"]
                ctrls["avg_power"].value = calc["avg_power_str"]
                ctrls["np"].value = calc["np_str"]
                ctrls["ele"].value = calc["pos_ele_str"]
            
            kpi_carbs.value = calc["total_carbs_str"]

            route_dist_badge.value = f"{calc['total_km']:.1f} km"
            route_ele_badge.value = f"{int(calc['pos_ele'])} hm"
            if state.get("elevation_source") == "open-meteo":
                route_ele_badge.tooltip = f"{int(calc['pos_ele'])} Hm (via Open-Meteo API bezogen)"
            elif state.get("elevation_source") == "open-elevation":
                route_ele_badge.tooltip = f"{int(calc['pos_ele'])} Hm (via Open-Elevation API bezogen)"
            elif state.get("elevation_source") == "cache":
                route_ele_badge.tooltip = f"{int(calc['pos_ele'])} Hm (aus lokalem Höhendaten-Cache)"
            elif state.get("elevation_error"):
                route_ele_badge.tooltip = f"0 Hm (Fehler: {state['elevation_error']})"
            else:
                route_ele_badge.tooltip = f"{int(calc['pos_ele'])} Hm (aus GPX-Datei)"

            route_name_badge.value = os.path.basename(state['gpx_path'])
            
            if route_changed:
                if state.get("elevation_error"):
                    show_snack(f"⚠️ {state['elevation_error']}", bgcolor=ft.Colors.RED_800, icon=ft.Icons.ERROR_OUTLINE)
                elif state.get("elevation_source") == "open-meteo":
                    show_snack(f"⛰️ Höhendaten wurden via Open-Meteo bezogen ({int(calc['pos_ele'])} Hm ermittelt).", bgcolor=ft.Colors.TEAL_700, icon=ft.Icons.TERRAIN)
                elif state.get("elevation_source") == "open-elevation":
                    show_snack(f"⛰️ Höhendaten wurden via Open-Elevation bezogen ({int(calc['pos_ele'])} Hm ermittelt).", bgcolor=ft.Colors.TEAL_700, icon=ft.Icons.TERRAIN)
                elif state.get("elevation_source") == "cache":
                    show_snack(f"⚡ Höhendaten aus lokalem Cache geladen ({int(calc['pos_ele'])} Hm).", bgcolor=ft.Colors.TEAL_800, icon=ft.Icons.SAVED_SEARCH)

            if route_changed or state.get("map_bytes") is None:
                state["map_bytes"] = render_route_map()
                img_map.src = state["map_bytes"]
                
            is_analysis_active = getattr(nav_bar, "selected_index", 0) == 1
            if is_analysis_active or force_charts:
                img_elevation.src = render_elevation_chart()
                img_energy.src = render_energy_chart()
                intervals_column.controls = [build_intervals_table()]
                state["charts_dirty"] = False
            else:
                state["charts_dirty"] = True

            update_pace_badge()
            update_gi_badge()
            update_gearing_badge()
            update_shopping_list()
            update_profile_summaries()
            save_settings(state)
            page.update()
        else:
            show_snack(f"Fehler bei der Berechnung: {err}", bgcolor=ft.Colors.RED_700, icon=ft.Icons.ERROR_OUTLINE)

    # ----------------------------------------------------
    # TAB 1: EINSTELLUNGEN & ROUTE
    # ----------------------------------------------------
    def on_ftp_change(e):
        val = int(float(e.data)) if e.data is not None else int(e.control.value)
        state["initial_ftp"] = val
        ftp_val_text.value = f"{val} W"
        page.update()

    def on_ftp_change_end(e):
        val = int(float(e.data)) if e.data is not None else int(e.control.value)
        state["initial_ftp"] = val
        ftp_val_text.value = f"{val} W"
        refresh_ui()

    def on_wprime_change(e):
        val = int(float(e.data)) if e.data is not None else int(e.control.value)
        state["w_prime"] = val
        wprime_val_text.value = f"{val:,} J"
        page.update()

    def on_wprime_change_end(e):
        val = int(float(e.data)) if e.data is not None else int(e.control.value)
        state["w_prime"] = val
        wprime_val_text.value = f"{val:,} J"
        refresh_ui()

    def on_rider_w_change(e):
        val = round(float(e.data), 1) if e.data is not None else float(e.control.value)
        state["rider_w"] = val
        rider_w_val_text.value = f"{val:.1f} kg"
        page.update()

    def on_rider_w_change_end(e):
        val = round(float(e.data), 1) if e.data is not None else float(e.control.value)
        state["rider_w"] = val
        rider_w_val_text.value = f"{val:.1f} kg"
        refresh_ui()

    def on_bike_w_change(e):
        val = round(float(e.data), 1) if e.data is not None else float(e.control.value)
        state["bike_w"] = val
        bike_w_val_text.value = f"{val:.1f} kg"
        page.update()

    def on_bike_w_change_end(e):
        val = round(float(e.data), 1) if e.data is not None else float(e.control.value)
        state["bike_w"] = val
        bike_w_val_text.value = f"{val:.1f} kg"
        refresh_ui()

    def on_carbs_change(e):
        val = int(float(e.data)) if e.data is not None else int(e.control.value)
        state["carbs_per_hour"] = val
        carbs_val_text.value = f"{val} g/h"
        update_gi_badge()
        page.update()

    def on_carbs_change_end(e):
        val = int(float(e.data)) if e.data is not None else int(e.control.value)
        state["carbs_per_hour"] = val
        carbs_val_text.value = f"{val} g/h"
        refresh_ui()

    def on_target_f_change(e):
        val = round(float(e.data), 2) if e.data is not None else float(e.control.value)
        state["target_f"] = val
        target_f_val_text.value = f"{int(val * 100)} % FTP ({val:.2f})"
        update_pace_badge()
        page.update()

    def on_target_f_change_end(e):
        val = round(float(e.data), 2) if e.data is not None else float(e.control.value)
        state["target_f"] = val
        target_f_val_text.value = f"{int(val * 100)} % FTP ({val:.2f})"
        refresh_ui()

    ftp_val_text = ft.Text(f"{state['initial_ftp']} W", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.AMBER_400)
    wprime_val_text = ft.Text(f"{state['w_prime']:,} J", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.RED_400)
    rider_w_val_text = ft.Text(f"{state['rider_w']:.1f} kg", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.BLUE_400)
    bike_w_val_text = ft.Text(f"{state['bike_w']:.1f} kg", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.CYAN_400)
    carbs_val_text = ft.Text(f"{state['carbs_per_hour']} g/h", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.GREEN_400)
    target_f_val_text = ft.Text(f"{int(state['target_f'] * 100)} % FTP ({state['target_f']:.2f})", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.ORANGE_400)

    # Handlers & Controls for Gearing, Cadence & Pacing Mode
    def on_lowest_gear_change(e):
        key = getattr(e, "data", None) or getattr(e.control, "value", None)
        if key in GEAR_RATIOS_LOW:
            state["lowest_gear_key"] = key
            state["lowest_gear_ratio"] = GEAR_RATIOS_LOW[key][1]
            lowest_gear_dropdown.value = key
            update_gearing_badge()
            refresh_ui()

    def on_highest_gear_change(e):
        key = getattr(e, "data", None) or getattr(e.control, "value", None)
        if key in GEAR_RATIOS_HIGH:
            state["highest_gear_key"] = key
            state["highest_gear_ratio"] = GEAR_RATIOS_HIGH[key][1]
            highest_gear_dropdown.value = key
            update_gearing_badge()
            refresh_ui()

    def on_min_cadence_change(e):
        val = round(float(e.data)) if getattr(e, "data", None) is not None else int(e.control.value)
        state["min_climb_cadence"] = float(val)
        min_cadence_val_text.value = f"{val} rpm"
        update_gearing_badge()
        page.update()

    def on_min_cadence_change_end(e):
        val = round(float(e.data)) if getattr(e, "data", None) is not None else int(e.control.value)
        state["min_climb_cadence"] = float(val)
        min_cadence_val_text.value = f"{val} rpm"
        update_gearing_badge()
        refresh_ui()

    def on_max_cadence_change(e):
        val = round(float(e.data)) if getattr(e, "data", None) is not None else int(e.control.value)
        state["max_pedal_cadence"] = float(val)
        max_cadence_val_text.value = f"{val} rpm"
        update_gearing_badge()
        page.update()

    def on_max_cadence_change_end(e):
        val = round(float(e.data)) if getattr(e, "data", None) is not None else int(e.control.value)
        state["max_pedal_cadence"] = float(val)
        max_cadence_val_text.value = f"{val} rpm"
        update_gearing_badge()
        refresh_ui()

    min_cadence_val_text = ft.Text(f"{int(state['min_climb_cadence'])} rpm", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.PURPLE_300)
    max_cadence_val_text = ft.Text(f"{int(state['max_pedal_cadence'])} rpm", weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.DEEP_PURPLE_300)

    lowest_gear_dropdown = ft.Dropdown(
        label="Kleinste Übersetzung (Berggang)",
        options=[ft.dropdown.Option(key=k, text=v[0]) for k, v in GEAR_RATIOS_LOW.items()],
        value=state["lowest_gear_key"],
        expand=True,
        on_select=on_lowest_gear_change,
    )

    highest_gear_dropdown = ft.Dropdown(
        label="Größte Übersetzung (Abfahrtsgang)",
        options=[ft.dropdown.Option(key=k, text=v[0]) for k, v in GEAR_RATIOS_HIGH.items()],
        value=state["highest_gear_key"],
        expand=True,
        on_select=on_highest_gear_change,
    )

    min_cadence_slider = ft.Slider(
        min=60, max=90, divisions=30, value=state["min_climb_cadence"],
        active_color=ft.Colors.PURPLE_400,
        on_change=on_min_cadence_change,
        on_change_end=on_min_cadence_change_end,
    )

    max_cadence_slider = ft.Slider(
        min=90, max=125, divisions=35, value=state["max_pedal_cadence"],
        active_color=ft.Colors.DEEP_PURPLE_400,
        on_change=on_max_cadence_change,
        on_change_end=on_max_cadence_change_end,
    )

    # FilePicker (Registered as a service in Flet 0.86+)
    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    async def on_pick_gpx_click(_):
        try:
            files = await file_picker.pick_files(
                dialog_title="GPX-Streckendatei auswählen",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["gpx", "GPX"],
                with_data=True,
                cancel_upload_on_window_blur=False,
            )
            if files and len(files) > 0:
                picked_file = files[0]
                fname = picked_file.name or (os.path.basename(picked_file.path) if picked_file.path else "uploaded_route.gpx")
                if not fname.lower().endswith(".gpx"):
                    show_snack("⚠️ Bitte wähle eine gültige .gpx Streckendatei aus.", bgcolor=ft.Colors.AMBER_800, icon=ft.Icons.WARNING_AMBER)
                    return
                state["base_filename"] = os.path.splitext(fname)[0]
                if picked_file.bytes:
                    state["gpx_content"] = picked_file.bytes
                    state["gpx_path"] = fname
                elif picked_file.path:
                    state["gpx_path"] = picked_file.path
                    state["gpx_content"] = None
                
                state["df_route"] = None  # Force re-parse for new GPX
                state["map_bytes"] = None
                gpx_file_text.value = f"✅ Geladen: {fname}"
                show_snack(f"✅ Route geladen: {fname}", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.CHECK_CIRCLE)
                refresh_ui(route_changed=True, force_charts=True)
        except Exception as ex:
            show_snack(f"Dateiauswahl blockiert oder nicht unterstützt: {ex}. Nutze 'GPX-Code einfügen'!", bgcolor=ft.Colors.AMBER_800, icon=ft.Icons.INFO_OUTLINE)

    # GPX Paste Dialog for Safari/iOS Web
    paste_gpx_input = ft.TextField(
        label=t("route.paste_dialog_label"),
        hint_text=t("route.paste_dialog_hint"),
        multiline=True,
        min_lines=6,
        max_lines=12,
        text_size=12
    )

    def close_paste_dialog(_=None):
        page.pop_dialog()

    def on_paste_gpx_apply(_):
        text = (paste_gpx_input.value or "").strip()
        if not text:
            show_snack("Bitte GPX-Inhalt in das Textfeld einfügen.", bgcolor=ft.Colors.AMBER_700, icon=ft.Icons.WARNING_AMBER)
            return
        if "<gpx" not in text and "<?xml" not in text:
            show_snack("Ungültiges GPX-Format (fehlendes <gpx>-Tag).", bgcolor=ft.Colors.RED_700, icon=ft.Icons.ERROR_OUTLINE)
            return
        
        state["base_filename"] = "custom_pasted_route"
        state["gpx_content"] = text
        state["gpx_path"] = "custom_pasted_route.gpx"
        state["df_route"] = None
        state["map_bytes"] = None
        gpx_file_text.value = "✅ Eingefügter GPX-Track geladen"
        page.pop_dialog()
        refresh_ui(route_changed=True, force_charts=True)
        show_snack("✅ GPX-Track erfolgreich importiert!", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.CHECK_CIRCLE)

    paste_dialog_title = ft.Text(t("route.paste_dialog_title"))
    paste_dialog_desc = ft.Text(t("route.paste_dialog_desc"), size=13, color=ft.Colors.GREY_400)
    paste_dialog_cancel_btn = ft.TextButton(t("dialog.cancel"), on_click=close_paste_dialog)
    paste_dialog_apply_btn = ft.FilledButton(t("route.paste_dialog_apply"), icon=ft.Icons.CHECK, on_click=on_paste_gpx_apply)

    paste_dialog = ft.AlertDialog(
        title=paste_dialog_title,
        content=ft.Container(
            content=ft.Column([
                paste_dialog_desc,
                paste_gpx_input
            ], spacing=10, tight=True),
            width=500
        ),
        actions=[
            paste_dialog_cancel_btn,
            paste_dialog_apply_btn,
        ]
    )

    def open_paste_dialog(_):
        paste_gpx_input.value = ""
        page.show_dialog(paste_dialog)

    # Local GPX Selector
    available_gpx = get_available_gpx_files()
    def on_select_local_gpx(e):
        selected = e.control.value
        if selected:
            state["gpx_path"] = selected
            state["gpx_content"] = None
            state["base_filename"] = os.path.splitext(os.path.basename(selected))[0]
            state["df_route"] = None
            state["map_bytes"] = None
            gpx_file_text.value = f"Streckendatei: {os.path.basename(selected)}"
            refresh_ui(route_changed=True, force_charts=True)
            show_snack(t("snack.route_changed", name=os.path.basename(selected)), bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.CHECK_CIRCLE)

    gpx_dropdown = ft.Dropdown(
        label=t("route.from_folder"),
        options=[ft.dropdown.Option(key=f, text=f"📍 {f}") for f in available_gpx],
        value=state["gpx_path"] if state["gpx_path"] in available_gpx else (available_gpx[0] if available_gpx else None),
        expand=True,
        on_select=on_select_local_gpx
    )
    gpx_file_text = ft.Text("Aktive GPS-Strecke", size=11, color=ft.Colors.GREY_400)

    def make_hero_card(icon, label, value_control, color):
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Container(
                        content=ft.Icon(icon, size=13, color=color),
                        bgcolor=ft.Colors.with_opacity(0.18, color),
                        padding=3,
                        border_radius=6,
                    ),
                    ft.Text(label, size=11, color=ft.Colors.GREY_300, weight=ft.FontWeight.W_500, expand=True, no_wrap=False)
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                value_control
            ], spacing=2),
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            border_radius=14,
            bgcolor=ft.Colors.with_opacity(0.10, color) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.05, color),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.22, color) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.12, color)),
            col={"xs": 6, "sm": 3},
        )

    ftp_slider = ft.Slider(min=100, max=500, divisions=80, value=state["initial_ftp"], active_color=ft.Colors.AMBER_400, on_change=on_ftp_change, on_change_end=on_ftp_change_end)
    wprime_slider = ft.Slider(min=10000, max=30000, divisions=20, value=state["w_prime"], active_color=ft.Colors.RED_400, on_change=on_wprime_change, on_change_end=on_wprime_change_end)
    rider_w_slider = ft.Slider(min=40, max=130, divisions=90, value=state["rider_w"], active_color=ft.Colors.BLUE_400, on_change=on_rider_w_change, on_change_end=on_rider_w_change_end)
    bike_w_slider = ft.Slider(min=5, max=20, divisions=30, value=state["bike_w"], active_color=ft.Colors.CYAN_400, on_change=on_bike_w_change, on_change_end=on_bike_w_change_end)
    carbs_slider = ft.Slider(min=20, max=120, divisions=20, value=state["carbs_per_hour"], active_color=ft.Colors.GREEN_400, on_change=on_carbs_change, on_change_end=on_carbs_change_end)
    target_f_slider = ft.Slider(min=0.60, max=1.00, divisions=40, value=state["target_f"], active_color=ft.Colors.ORANGE_400, on_change=on_target_f_change, on_change_end=on_target_f_change_end)

    # Independent Reset Handlers for each profile domain
    def on_reset_rider_settings(_=None):
        for k in DEFAULT_RIDER_SETTINGS:
            state[k] = DEFAULT_RIDER_SETTINGS[k]
        ftp_slider.value = state["initial_ftp"]
        wprime_slider.value = state["w_prime"]
        rider_w_slider.value = state["rider_w"]
        ftp_val_text.value = f"{state['initial_ftp']} W"
        wprime_val_text.value = f"{state['w_prime']:,} J"
        rider_w_val_text.value = f"{state['rider_w']:.1f} kg"
        update_profile_summaries()
        save_settings(state)
        refresh_ui()
        show_snack("Fahrer-Standardwerte wiederhergestellt.", bgcolor=ft.Colors.BLUE_GREY_800, icon=ft.Icons.RESTORE)

    def on_reset_bike_settings(_=None):
        for k in DEFAULT_BIKE_SETTINGS:
            state[k] = DEFAULT_BIKE_SETTINGS[k]
        state["lowest_gear_ratio"] = GEAR_RATIOS_LOW[DEFAULT_BIKE_SETTINGS["lowest_gear_key"]][1]
        state["highest_gear_ratio"] = GEAR_RATIOS_HIGH[DEFAULT_BIKE_SETTINGS["highest_gear_key"]][1]
        bike_w_slider.value = state["bike_w"]
        lowest_gear_dropdown.value = state["lowest_gear_key"]
        highest_gear_dropdown.value = state["highest_gear_key"]
        min_cadence_slider.value = state["min_climb_cadence"]
        max_cadence_slider.value = state["max_pedal_cadence"]
        bike_w_val_text.value = f"{state['bike_w']:.1f} kg"
        min_cadence_val_text.value = f"{int(state['min_climb_cadence'])} rpm"
        max_cadence_val_text.value = f"{int(state['max_pedal_cadence'])} rpm"
        update_gearing_badge()
        update_profile_summaries()
        save_settings(state)
        refresh_ui()
        show_snack("Rad-Standardwerte wiederhergestellt.", bgcolor=ft.Colors.BLUE_GREY_800, icon=ft.Icons.RESTORE)

    def on_reset_strategy_settings(_=None):
        for k in DEFAULT_STRATEGY_SETTINGS:
            if k != "gpx_path":
                state[k] = DEFAULT_STRATEGY_SETTINGS[k]
        carbs_slider.value = state["carbs_per_hour"]
        target_f_slider.value = state["target_f"]
        carbs_val_text.value = f"{state['carbs_per_hour']} g/h"
        target_f_val_text.value = f"{int(state['target_f'] * 100)} % FTP ({state['target_f']:.2f})"
        update_gi_badge()
        update_pace_badge()
        save_settings(state)
        refresh_ui()
        show_snack("Strategie-Standardwerte wiederhergestellt.", bgcolor=ft.Colors.BLUE_GREY_800, icon=ft.Icons.RESTORE)

    on_reset_settings_click = on_reset_strategy_settings

    setup_header_title = ft.Text(t("dashboard.setup_title"), size=15, weight=ft.FontWeight.BOLD, expand=True)
    reset_strategy_btn = ft.IconButton(
        icon=ft.Icons.RESTART_ALT,
        icon_size=18,
        tooltip=t("dashboard.reset_tooltip"),
        icon_color=ft.Colors.GREY_400,
        on_click=on_reset_strategy_settings,
    )
    setup_help_btn = ft.IconButton(
        icon=ft.Icons.HELP_OUTLINE,
        icon_size=18,
        tooltip=t("dashboard.help_tooltip"),
        icon_color=ft.Colors.AMBER_400,
        on_click=open_full_help_dialog,
    )

    hero_dashboard = ft.Container(
        content=ft.Column([
            build_kpi_overview_section(kpi_controls_t1),
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.TUNE, size=16, color=ft.Colors.AMBER_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.AMBER),
                    border_radius=8,
                    padding=6,
                ),
                setup_header_title,
                reset_strategy_btn,
                setup_help_btn,
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=4),
    )

    slider_headers = []

    def make_slider_header(icon, label, val_text_control, color, help_title=None, help_text=None, label_key=None, help_title_key=None, help_text_key=None):
        actual_label = t(label_key) if label_key else label
        lbl_control = ft.Text(actual_label, size=13, weight=ft.FontWeight.W_500, expand=True, no_wrap=False)
        header_row = [
            ft.Icon(icon, size=16, color=color),
            lbl_control,
        ]
        info_btn = None
        if help_text or help_text_key:
            h_title = (t(help_title_key) if help_title_key else help_title) or actual_label
            h_text = t(help_text_key) if help_text_key else help_text
            info_btn = ft.IconButton(
                icon=ft.Icons.INFO_OUTLINE,
                icon_size=15,
                icon_color=ft.Colors.GREY_400,
                tooltip=f"Info: {actual_label}",
                on_click=lambda _, tk=help_title_key, dt=h_title, dx=h_text, dk=help_text_key: show_help_dialog(t(tk) if tk else dt, t(dk) if dk else dx),
            )
            header_row.append(info_btn)

        slider_headers.append({
            "label_control": lbl_control,
            "label_key": label_key,
            "fallback_label": label,
            "info_btn": info_btn,
            "help_title_key": help_title_key,
            "help_text_key": help_text_key,
        })

        return ft.Column([
            ft.Row(header_row, spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([
                ft.Container(
                    content=val_text_control,
                    bgcolor=ft.Colors.with_opacity(0.12, color),
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.25, color)),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                    border_radius=8,
                )
            ]),
        ], spacing=4)

    # Compact Profile Summary Cards for Tab 1
    rider_profile_title = ft.Text(t("profile.rider_title"), size=13, weight=ft.FontWeight.BOLD, expand=True)
    rider_profile_btn = ft.TextButton(
        t("profile.customize"),
        icon=ft.Icons.TUNE,
        icon_color=ft.Colors.AMBER_400,
        on_click=lambda _: open_rider_settings_dialog(),
    )
    card_rider_profile = ft.Card(
        content=ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.PERSON, size=15, color=ft.Colors.AMBER_400),
                        bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.AMBER),
                        padding=4,
                        border_radius=6,
                    ),
                    rider_profile_title,
                    rider_profile_btn,
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                rider_summary_text,
                rider_summary_subtext,
            ], spacing=3),
            padding=12,
            border_radius=14,
        ),
        shape=ft.RoundedRectangleBorder(radius=14),
        col={"xs": 12, "md": 6},
    )

    bike_profile_title = ft.Text(t("profile.bike_title"), size=13, weight=ft.FontWeight.BOLD, expand=True)
    bike_profile_btn = ft.TextButton(
        t("profile.customize"),
        icon=ft.Icons.TUNE,
        icon_color=ft.Colors.CYAN_400,
        on_click=lambda _: open_bike_settings_dialog(),
    )
    card_bike_profile = ft.Card(
        content=ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.DIRECTIONS_BIKE, size=15, color=ft.Colors.CYAN_400),
                        bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.CYAN),
                        padding=4,
                        border_radius=6,
                    ),
                    bike_profile_title,
                    bike_profile_btn,
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bike_summary_text,
                bike_summary_subtext,
            ], spacing=3),
            padding=12,
            border_radius=14,
        ),
        shape=ft.RoundedRectangleBorder(radius=14),
        col={"xs": 12, "md": 6},
    )

    card_profiles_row = ft.ResponsiveRow([
        card_rider_profile,
        card_bike_profile,
    ], spacing=10, run_spacing=10)

    # Modal Dialogs for Rider, Bike & Route Settings
    rider_dialog_title = ft.Text(t("dialog.rider_title"), size=16, weight=ft.FontWeight.BOLD, expand=True)
    rider_dialog_reset_btn = ft.TextButton(t("dialog.reset_rider"), icon=ft.Icons.RESTART_ALT, on_click=on_reset_rider_settings)
    rider_dialog_done_btn = ft.FilledButton(t("dialog.done"), on_click=lambda _: page.pop_dialog())

    rider_dialog = ft.AlertDialog(
        modal=False,
        title=ft.Row([
            ft.Icon(ft.Icons.PERSON, color=ft.Colors.AMBER_400, size=22),
            rider_dialog_title,
        ], spacing=10),
        content=ft.Container(
            content=ft.Column([
                make_slider_header(
                    ft.Icons.BOLT, "Start-FTP", ftp_val_text, ft.Colors.AMBER_400,
                    "Start-FTP (Functional Threshold Power)",
                    "Die maximale Dauerleistung in Watt, die du theoretisch 60 Minuten lang konstant halten kannst. Bildet die 100%-Referenz für alle Trainingszonen und aeroben Berechnungen.",
                    label_key="slider.ftp_label",
                    help_title_key="slider.ftp_help_title",
                    help_text_key="slider.ftp_help_text"
                ),
                ftp_slider,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                make_slider_header(
                    ft.Icons.BATTERY_CHARGING_FULL, "W'-Kapazität (Akku)", wprime_val_text, ft.Colors.RED_400,
                    "W'-Kapazität (Anaerober Akku)",
                    "Dein anaerober Speicher in Joule. Jede Sekunde, in der du über deiner FTP fährst, leert diesen Tank. Fährst du unterhalb der FTP, lädt er sich wieder auf (typisch: 15.000 J für Einsteiger bis 25.000+ J für Sprinter/Profis).",
                    label_key="slider.wprime_label",
                    help_title_key="slider.wprime_help_title",
                    help_text_key="slider.wprime_help_text"
                ),
                wprime_slider,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                make_slider_header(
                    ft.Icons.PERSON, "Fahrergewicht", rider_w_val_text, ft.Colors.BLUE_400,
                    "Fahrergewicht (kg)",
                    "Dein reines Körpergewicht ohne Ausrüstung. Maßgeblich für die Steigungsleistung am Berg und die Berechnung des Leistungsgewichts (W/kg).",
                    label_key="slider.rider_w_label",
                    help_title_key="slider.rider_w_help_title",
                    help_text_key="slider.rider_w_help_text"
                ),
                rider_w_slider,
            ], spacing=6, tight=True, scroll=ft.ScrollMode.AUTO),
            width=440,
        ),
        actions=[
            rider_dialog_reset_btn,
            rider_dialog_done_btn,
        ],
    )

    bike_dialog_title = ft.Text(t("dialog.bike_title"), size=16, weight=ft.FontWeight.BOLD, expand=True)
    bike_dialog_reset_btn = ft.TextButton(t("dialog.reset_bike"), icon=ft.Icons.RESTART_ALT, on_click=on_reset_bike_settings)
    bike_dialog_done_btn = ft.FilledButton(t("dialog.done"), on_click=lambda _: page.pop_dialog())

    bike_dialog = ft.AlertDialog(
        modal=False,
        title=ft.Row([
            ft.Icon(ft.Icons.DIRECTIONS_BIKE, color=ft.Colors.CYAN_400, size=22),
            bike_dialog_title,
        ], spacing=10),
        content=ft.Container(
            content=ft.Column([
                make_slider_header(
                    ft.Icons.DIRECTIONS_BIKE, "Fahrrad & Ausrüstung", bike_w_val_text, ft.Colors.CYAN_400,
                    "Fahrrad & Ausrüstung (kg)",
                    "Das Gesamtgewicht deines Fahrrads inklusive Trinkflaschen, Bekleidung, Helm, Schuhen, Werkzeug und Riegeln.",
                    label_key="slider.bike_w_label",
                    help_title_key="slider.bike_w_help_title",
                    help_text_key="slider.bike_w_help_text"
                ),
                bike_w_slider,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                lowest_gear_dropdown,
                ft.Container(height=4),
                make_slider_header(
                    ft.Icons.ROTATE_RIGHT, "Minimale Kletter-Kadenz", min_cadence_val_text, ft.Colors.PURPLE_300,
                    "Minimale Kletter-Kadenz (rpm)",
                    "Deine angestrebte Mindest-Trittfrequenz an steilen Rampen. Verhindert unphysiologisch schweres Treten.",
                    label_key="slider.min_cadence_label",
                    help_title_key="slider.min_cadence_help_title",
                    help_text_key="slider.min_cadence_help_text"
                ),
                min_cadence_slider,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                highest_gear_dropdown,
                ft.Container(height=4),
                make_slider_header(
                    ft.Icons.FAST_FORWARD, "Maximale Pedalier-Kadenz (Spin-Out)", max_cadence_val_text, ft.Colors.DEEP_PURPLE_300,
                    "Maximale Pedalier-Kadenz (Spin-Out)",
                    "Deine persönliche Grenze für schnelles Treten in Abfahrten. Sobald das Tempo im größten Gang diese Kadenz überschreitet, schaltet das Pacing auf 0 W.",
                    label_key="slider.max_cadence_label",
                    help_title_key="slider.max_cadence_help_title",
                    help_text_key="slider.max_cadence_help_text"
                ),
                max_cadence_slider,
                ft.Divider(height=8, color=ft.Colors.TRANSPARENT),
                gearing_badge,
            ], spacing=6, tight=True, scroll=ft.ScrollMode.AUTO),
            width=460,
        ),
        actions=[
            bike_dialog_reset_btn,
            bike_dialog_done_btn,
        ],
    )

    route_dialog_title = ft.Text(t("dialog.route_title"), size=16, weight=ft.FontWeight.BOLD, expand=True)
    route_dialog_select_prompt = ft.Text(t("route.dialog_select_prompt"), size=12, color=ft.Colors.GREY_400)
    route_dialog_folder_prompt = ft.Text(t("route.dialog_folder_prompt"), size=12, color=ft.Colors.GREY_400)
    route_dialog_pick_btn = ft.FilledButton(
        t("route.select_file"),
        icon=ft.Icons.UPLOAD_FILE,
        on_click=lambda e: (page.pop_dialog(), on_pick_gpx_click(e)),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )
    route_dialog_paste_btn = ft.OutlinedButton(
        t("route.paste_code"),
        icon=ft.Icons.PASTE,
        on_click=lambda e: (page.pop_dialog(), open_paste_dialog(e)),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )
    route_dialog_close_btn = ft.TextButton(t("dialog.close"), on_click=lambda _: page.pop_dialog())

    route_dialog = ft.AlertDialog(
        modal=False,
        title=ft.Row([
            ft.Icon(ft.Icons.MAP_OUTLINED, color=ft.Colors.LIGHT_BLUE_400, size=22),
            route_dialog_title,
        ], spacing=10),
        content=ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.LOCATION_ON, size=16, color=ft.Colors.LIGHT_BLUE_400),
                            route_name_badge,
                        ], spacing=6),
                        ft.Row([
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.STRAIGHTEN, size=13, color=ft.Colors.AMBER_400),
                                    route_dist_badge,
                                ], spacing=4),
                                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.AMBER),
                                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                border_radius=8,
                            ),
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.LANDSCAPE, size=13, color=ft.Colors.LIGHT_BLUE_400),
                                    route_ele_badge,
                                ], spacing=4),
                                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.LIGHT_BLUE),
                                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                border_radius=8,
                            ),
                        ], spacing=8),
                    ], spacing=6),
                    padding=10,
                    border_radius=10,
                    bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.04, ft.Colors.BLACK),
                ),
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                route_dialog_select_prompt,
                ft.Row([
                    route_dialog_pick_btn,
                    route_dialog_paste_btn,
                ], spacing=8, wrap=True),
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT) if available_gpx else ft.Container(),
                ft.Column([
                    route_dialog_folder_prompt,
                    gpx_dropdown,
                ], spacing=4) if available_gpx else ft.Container(),
            ], spacing=8, tight=True, scroll=ft.ScrollMode.AUTO),
            width=440,
        ),
        actions=[
            route_dialog_close_btn,
        ],
    )

    def open_rider_settings_dialog(_=None):
        page.show_dialog(rider_dialog)

    def open_bike_settings_dialog(_=None):
        page.show_dialog(bike_dialog)

    def open_route_picker_dialog(_=None):
        page.show_dialog(route_dialog)

    # Backward-compatible references for tests
    card1 = rider_dialog
    card_gearing = bike_dialog

    section2_title = ft.Text(t("section.nutrition_title"), size=15, weight=ft.FontWeight.BOLD, expand=True)
    section2_info_btn = ft.IconButton(
        icon=ft.Icons.INFO_OUTLINE,
        icon_size=16,
        icon_color=ft.Colors.GREY_400,
        tooltip=f"Info: {t('section.nutrition_title')}",
        on_click=lambda _: show_help_dialog(
            t("section.nutrition_help_title"),
            t("section.nutrition_help_text")
        ),
    )
    section2_header = ft.Row([
        ft.Container(
            content=ft.Icon(ft.Icons.ECO, size=16, color=ft.Colors.GREEN_400),
            bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.GREEN),
            border_radius=8,
            padding=6,
        ),
        section2_title,
        section2_info_btn,
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    card2 = ft.Card(
        content=ft.Container(
            content=ft.Column([
                make_slider_header(
                    ft.Icons.RESTAURANT, "Kohlenhydrate (g/h)", carbs_val_text, ft.Colors.GREEN_400,
                    "Kohlenhydrate pro Stunde (g/h)",
                    "Die geplante Zufuhr an Kohlenhydraten pro Stunde. Schützt den körpereigenen Glykogenspeicher und verzögert den Hungerast. Für Marathons werden 80-100 g/h empfohlen; Werte über 90 g/h erfordern Dual-Source Fructose/Maltodextrin und Magen-Darm-Training.",
                    label_key="slider.carbs_label",
                    help_title_key="slider.carbs_help_title",
                    help_text_key="slider.carbs_help_text"
                ),
                carbs_slider,
                gi_badge,

                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                make_slider_header(
                    ft.Icons.SPEED, "Intensitätsfaktor (Target Factor)", target_f_val_text, ft.Colors.ORANGE_400,
                    "Intensitätsfaktor (Target Factor)",
                    "Der prozentuale Anteil deiner FTP, den du im flachen und leicht ansteigenden Gelände als Basis anstrebst (z. B. 0.82 = 82% FTP). Höhere Werte verringern die Fahrzeit, leeren aber die Energiespeicher deutlich rascher.",
                    label_key="slider.target_f_label",
                    help_title_key="slider.target_f_help_title",
                    help_text_key="slider.target_f_help_text"
                ),
                target_f_slider,
                pace_badge,
            ]),
            padding=16,
            border_radius=16,
        ),
        shape=ft.RoundedRectangleBorder(radius=16),
    )

    section3_title = ft.Text(t("section.route_title"), size=15, weight=ft.FontWeight.BOLD, expand=True)
    section3_info_btn = ft.IconButton(
        icon=ft.Icons.INFO_OUTLINE,
        icon_size=16,
        icon_color=ft.Colors.GREY_400,
        tooltip=f"Info: {t('section.route_title')}",
        on_click=lambda _: show_help_dialog(
            t("section.route_help_title"),
            t("section.route_help_text")
        ),
    )
    section3_header = ft.Row([
        ft.Container(
            content=ft.Icon(ft.Icons.ROUTE, size=16, color=ft.Colors.LIGHT_BLUE_400),
            bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.LIGHT_BLUE),
            border_radius=8,
            padding=6,
        ),
        section3_title,
        section3_info_btn,
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    route_change_btn = ft.FilledTonalButton(
        t("route.change_button"),
        icon=ft.Icons.FOLDER_OPEN,
        on_click=lambda _: open_route_picker_dialog(),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )
    route_card_pick_btn = ft.FilledButton(
        t("route.select_file"),
        icon=ft.Icons.UPLOAD_FILE,
        on_click=on_pick_gpx_click,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )
    route_card_paste_btn = ft.OutlinedButton(
        t("route.paste_code"),
        icon=ft.Icons.PASTE,
        on_click=open_paste_dialog,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )

    card3 = ft.Card(
        content=ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.MAP_OUTLINED, size=20, color=ft.Colors.LIGHT_BLUE_400),
                    ft.Column([
                        route_name_badge,
                        gpx_file_text,
                    ], spacing=2, expand=True),
                    route_change_btn,
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.STRAIGHTEN, size=13, color=ft.Colors.AMBER_400),
                            route_dist_badge,
                        ], spacing=4),
                        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.AMBER),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                        border_radius=8,
                    ),
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.LANDSCAPE, size=13, color=ft.Colors.LIGHT_BLUE_400),
                            route_ele_badge,
                        ], spacing=4),
                        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.LIGHT_BLUE),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                        border_radius=8,
                    ),
                ], spacing=8),
                ft.Divider(height=6, color=ft.Colors.TRANSPARENT),
                ft.Row([
                    route_card_pick_btn,
                    route_card_paste_btn,
                ], wrap=True, spacing=8),
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT) if available_gpx else ft.Container(),
                ft.Row([gpx_dropdown]) if available_gpx else ft.Container(),
            ], spacing=10),
            padding=16,
            border_radius=16,
        ),
        shape=ft.RoundedRectangleBorder(radius=16),
    )

    tab_setup_view = ft.Container(
        content=ft.Column([
            hero_dashboard,
            card_profiles_row,
            section2_header,
            card2,
            section3_header,
            card3,
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True),
        padding=16,
        expand=True
    )

    tab_setup_view.test_controls = {
        "ftp_slider": ftp_slider,
        "wprime_slider": wprime_slider,
        "rider_w_slider": rider_w_slider,
        "bike_w_slider": bike_w_slider,
        "carbs_slider": carbs_slider,
        "target_f_slider": target_f_slider,
        "lowest_gear_dropdown": lowest_gear_dropdown,
        "highest_gear_dropdown": highest_gear_dropdown,
        "min_cadence_slider": min_cadence_slider,
        "max_cadence_slider": max_cadence_slider,
        "rider_dialog": rider_dialog,
        "bike_dialog": bike_dialog,
        "route_dialog": route_dialog,
        "rider_chip": rider_chip,
        "bike_chip": bike_chip,
        "route_status_chip": route_status_chip,
    }

    # ----------------------------------------------------
    # TAB 2: ANALYSE & CHARTS & SPORTNAHRUNG
    # ----------------------------------------------------
    shopping_iso_text = ft.Text("-", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300)
    shopping_gels_text = ft.Text("-", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300)
    shopping_bars_text = ft.Text("-", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300)

    def update_shopping_list():
        if not state["calc"] or "total_hours" not in state["calc"]:
            return
        total_hours = max(0.5, float(state["calc"]["total_hours"]))
        carbs_h = float(state.get("carbs_per_hour", 90))
        iso_bottles = math.ceil(total_hours)
        remaining_carbs = max(0.0, (total_hours * carbs_h) - (iso_bottles * 35.0))
        standard_gels = math.ceil((remaining_carbs / 2.0) / 30.0)
        hydro_bars = math.ceil((remaining_carbs / 2.0) / 40.0)

        shopping_iso_text.value = t("shopping.iso", count=iso_bottles)
        shopping_gels_text.value = t("shopping.gels", count=standard_gels)
        shopping_bars_text.value = t("shopping.bars", count=hydro_bars)

    update_shopping_list()

    shopping_desc_text = ft.Text(t("tab2.shopping_subtitle"), size=12, color=ft.Colors.GREY_400)
    shopping_card = ft.Card(
        content=ft.Container(
            content=ft.Column([
                shopping_desc_text,
                ft.ResponsiveRow([
                    ft.Container(
                        content=shopping_iso_text,
                        bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.CYAN),
                        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                        border_radius=10,
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.20, ft.Colors.CYAN)),
                        col={"xs": 12, "sm": 4},
                    ),
                    ft.Container(
                        content=shopping_gels_text,
                        bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.GREEN),
                        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                        border_radius=10,
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.20, ft.Colors.GREEN)),
                        col={"xs": 12, "sm": 4},
                    ),
                    ft.Container(
                        content=shopping_bars_text,
                        bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.AMBER),
                        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                        border_radius=10,
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.20, ft.Colors.AMBER)),
                        col={"xs": 12, "sm": 4},
                    ),
                ], spacing=8, run_spacing=8),
            ], spacing=8),
            padding=16,
            border_radius=16,
        ),
        shape=ft.RoundedRectangleBorder(radius=16),
    )

    map_section_title = ft.Text(t("tab2.map_preview"), size=15, weight=ft.FontWeight.BOLD, expand=True)
    elevation_section_title = ft.Text(t("tab2.elevation_power"), size=15, weight=ft.FontWeight.BOLD, expand=True)
    energy_section_title = ft.Text(t("tab2.energy_tanks"), size=15, weight=ft.FontWeight.BOLD, expand=True)
    intervals_section_title = ft.Text(t("tab2.intervals_zones"), size=15, weight=ft.FontWeight.BOLD, expand=True)
    shopping_section_title = ft.Text(t("tab2.shopping_title"), size=15, weight=ft.FontWeight.BOLD, expand=True)
    shopping_info_btn = ft.IconButton(
        icon=ft.Icons.INFO_OUTLINE,
        icon_size=16,
        icon_color=ft.Colors.GREY_400,
        tooltip=f"Info: {t('tab2.shopping_title')}",
        on_click=lambda _: show_help_dialog(
            t("tab2.shopping_title"),
            (
                "Berechnet deinen exakten Verpflegungsbedarf auf Basis der prognostizierten Fahrzeit und deiner eingestellten Kohlenhydrate pro Stunde:\n\n"
                "• Iso-Getränkepulver: 1 Flasche pro Rennstunde (ca. 35g KH).\n"
                "• Feste / halbfeste Nahrung: Der restliche Kohlenhydratbedarf wird zu 50% über schnelle Gels (30g KH) und zu 50% über Riegel/Hydro-Gels (40g KH) aufgeteilt."
            ) if get_language() == "de" else (
                "Calculates your exact race fueling demand based on predicted duration and configured hourly carbohydrate intake:\n\n"
                "• Electrolyte drink mix: 1 bottle per race hour (~35g carbs).\n"
                "• Solid / semi-solid fuel: Remaining carbs split 50% into fast energy gels (30g) and 50% into energy bars/hydro-gels (40g)."
            )
        ),
    )

    tab_analysis_view = ft.Container(
        content=ft.Column([
            build_kpi_overview_section(kpi_controls_t2),

            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.MAP, size=16, color=ft.Colors.LIGHT_BLUE_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.LIGHT_BLUE),
                    border_radius=8,
                    padding=6,
                ),
                map_section_title,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Card(content=ft.Container(content=img_map, padding=10), shape=ft.RoundedRectangleBorder(radius=16)),

            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.SHOW_CHART, size=16, color=ft.Colors.AMBER_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.AMBER),
                    border_radius=8,
                    padding=6,
                ),
                elevation_section_title,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Card(content=ft.Container(content=img_elevation, padding=10), shape=ft.RoundedRectangleBorder(radius=16)),

            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.BATTERY_CHARGING_FULL, size=16, color=ft.Colors.RED_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.RED),
                    border_radius=8,
                    padding=6,
                ),
                energy_section_title,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Card(content=ft.Container(content=img_energy, padding=10), shape=ft.RoundedRectangleBorder(radius=16)),

            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.FORMAT_LIST_BULLETED, size=16, color=ft.Colors.PURPLE_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PURPLE),
                    border_radius=8,
                    padding=6,
                ),
                intervals_section_title,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Card(content=ft.Container(content=intervals_column, padding=12), shape=ft.RoundedRectangleBorder(radius=16)),

            # Sportnahrungs-Einkaufsliste
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.SHOPPING_BAG, size=16, color=ft.Colors.GREEN_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.GREEN),
                    border_radius=8,
                    padding=6,
                ),
                shopping_section_title,
                shopping_info_btn,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            shopping_card,
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True),
        padding=16,
        expand=True
    )

    # ----------------------------------------------------
    # TAB 3: KAROO-SYNC & EXPORTE
    # ----------------------------------------------------
    log_box = ft.TextField(
        multiline=True,
        read_only=True,
        min_lines=6,
        max_lines=10,
        text_size=12,
        value="[System bereit für Übertragungen]",
    )

    def log_message(msg):
        state["logs"].append(msg)
        log_box.value = "\n".join(state["logs"][-20:])
        page.update()

    # ----------------------------------------------------
    # HAMMERHEAD CLOUD SYNC & BROWSER LOGIN
    # ----------------------------------------------------
    hh_client = HammerheadClient(
        token=state.get("hh_token") or None,
        user_id=state.get("hh_user_id") or None,
        refresh_token=state.get("hh_refresh_token") or None,
    )
    if hh_client.user_id and not state.get("hh_user_id"):
        state["hh_user_id"] = hh_client.user_id

    auth_session_holder = {"session": None}

    hh_status_text = ft.Text("", size=12, weight=ft.FontWeight.W_600)
    hh_status_icon = ft.Icon(ft.Icons.CLOUD_OFF, size=16, color=ft.Colors.GREY_400)
    hh_logout_btn = ft.OutlinedButton(
        "Abmelden",
        icon=ft.Icons.LOGOUT,
        visible=False,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )

    def refresh_hh_auth_ui():
        if hh_client.is_authenticated:
            ident = state.get("hh_email") or f"User-ID: {hh_client.user_id}"
            hh_status_text.value = f"Verbunden mit Hammerhead Cloud ({ident})"
            hh_status_text.color = ft.Colors.GREEN_300
            hh_status_icon.name = ft.Icons.CLOUD_DONE
            hh_status_icon.color = ft.Colors.GREEN_400
            hh_logout_btn.visible = True
        else:
            hh_status_text.value = "Nicht bei Hammerhead Cloud angemeldet"
            hh_status_text.color = ft.Colors.GREY_400
            hh_status_icon.name = ft.Icons.CLOUD_OFF
            hh_status_icon.color = ft.Colors.GREY_400
            hh_logout_btn.visible = False

    refresh_hh_auth_ui()

    def on_hh_auto_sync_change(e):
        state["hh_auto_sync"] = bool(e.control.value)
        save_settings(state)

    hh_auto_sync_switch = ft.Switch(
        label="Route (.gpx) nach erfolgreichem Karoo-Transfer automatisch an Hammerhead senden",
        value=bool(state.get("hh_auto_sync", True)),
        active_color=ft.Colors.AMBER_400,
        on_change=on_hh_auto_sync_change,
    )

    async def on_hh_browser_login_click(_):
        import webbrowser

        old_sess = auth_session_holder.get("session")
        if old_sess:
            old_sess.stop()

        loop = asyncio.get_running_loop()

        def on_auth_completed(token: str, user_id: str, identifier: str, refresh_token: str = None):
            def apply_on_main_thread():
                hh_client.set_token(token, user_id, refresh_token=refresh_token)
                state["hh_token"] = token
                state["hh_refresh_token"] = refresh_token or ""
                state["hh_user_id"] = user_id
                state["hh_email"] = identifier
                save_settings(state)
                refresh_hh_auth_ui()
                log_message(f"[{time.strftime('%H:%M:%S')}] ✅ Hammerhead Browser-Login erfolgreich ({identifier}, User-ID: {user_id}).")
                show_snack(f"☁️ Mit Hammerhead Cloud verbunden ({identifier})!", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.CLOUD_DONE)
                page.update()

            loop.call_soon_threadsafe(apply_on_main_thread)

        sess = BrowserAuthSession(
            on_success=on_auth_completed,
            clear_session=bool(state.get("hh_clear_webview_session", False)),
        )
        state["hh_clear_webview_session"] = False
        auth_session_holder["session"] = sess
        login_url = sess.start()

        log_message(f"[{time.strftime('%H:%M:%S')}] 🌐 Öffne offizielles Hammerhead / SRAM Anmeldefenster (https://dashboard.hammerhead.io)...")
        launched_native = await asyncio.to_thread(sess.launch_native_hammerhead_browser)
        if not launched_native:
            opened = False
            try:
                await page.launch_url(login_url)
                opened = True
            except Exception:
                pass
            if not opened:
                try:
                    webbrowser.open(login_url)
                except Exception:
                    pass
        show_snack("🌐 Hammerhead / SRAM Anmeldefenster geöffnet.", bgcolor=ft.Colors.BLUE_700, icon=ft.Icons.OPEN_IN_BROWSER)

    def on_hh_logout_click(_):
        old_sess = auth_session_holder.get("session")
        if old_sess:
            old_sess.stop()
            auth_session_holder["session"] = None
        hh_client.clear_auth()
        state["hh_token"] = ""
        state["hh_refresh_token"] = ""
        state["hh_user_id"] = ""
        state["hh_email"] = ""
        state["hh_clear_webview_session"] = True
        save_settings(state)
        refresh_hh_auth_ui()
        log_message(f"[{time.strftime('%H:%M:%S')}] 🔒 Hammerhead Cloud-Verbindung getrennt.")
        show_snack("Von Hammerhead Cloud abgemeldet.", bgcolor=ft.Colors.BLUE_GREY_800, icon=ft.Icons.LOGOUT)
        page.update()

    hh_logout_btn.on_click = on_hh_logout_click

    async def do_push_gpx_to_hammerhead(json_str: str = None) -> bool:
        if not state["calc"]:
            show_snack("Keine Berechnungsdaten vorhanden.", bgcolor=ft.Colors.AMBER_700, icon=ft.Icons.WARNING_AMBER)
            return False
        if not hh_client.is_authenticated:
            log_message(f"[{time.strftime('%H:%M:%S')}] ⚠️ Hammerhead GPX-Upload nicht möglich: Bitte zuerst über das Browserfenster anmelden.")
            show_snack("Bitte zuerst bei Hammerhead im Browser anmelden.", bgcolor=ft.Colors.AMBER_700, icon=ft.Icons.LOGIN)
            return False

        try:
            raw_json = json_str or get_karoo_json()
            data = json.loads(raw_json)
            meta = data.get("meta") or {}
            track = data.get("track") or []
            route_name = meta.get("route_name") or state["base_filename"]
            gpx_str = generate_gpx_from_pacing_track(meta, track)

            log_message(f"[{time.strftime('%H:%M:%S')}] ☁️ Sende Routendatei '{route_name}.gpx' an Hammerhead Cloud...")
            await asyncio.to_thread(hh_client.upload_gpx, gpx_str, route_name)
            if hh_client.token and hh_client.token != state.get("hh_token"):
                state["hh_token"] = hh_client.token
                state["hh_refresh_token"] = hh_client.refresh_token or ""
                save_settings(state)
            log_message(f"[{time.strftime('%H:%M:%S')}] ✅ Hammerhead Cloud: Route '{route_name}.gpx' erfolgreich übertragen!")
            show_snack(f"☁️ Route '{route_name}.gpx' an Hammerhead übertragen!", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.CLOUD_DONE)
            return True
        except Exception as e:
            log_message(f"[{time.strftime('%H:%M:%S')}] ❌ Hammerhead Cloud Upload-Fehler: {e}")
            show_snack(f"❌ Hammerhead GPX-Upload fehlgeschlagen: {e}", bgcolor=ft.Colors.RED_700, icon=ft.Icons.CLOUD_OFF)
            return False

    async def on_hh_manual_upload_click(_):
        await do_push_gpx_to_hammerhead()

    async def do_push_to_karoo(url):
        if not state["calc"]:
            show_snack("Keine Berechnungsdaten vorhanden.", bgcolor=ft.Colors.AMBER_700, icon=ft.Icons.WARNING_AMBER)
            return
        filename = f"{state['base_filename']}_power_track.json"
        json_str = get_karoo_json()
        
        log_message(f"🚀 Starte Karoo-Upload an: {url}")
        loop = asyncio.get_running_loop()

        def safe_log(msg):
            loop.call_soon_threadsafe(log_message, msg)

        success, msg, logs = await asyncio.to_thread(push_to_karoo_http, url, json_str, filename, safe_log)
            
        if success:
            show_snack(f"🎉 Erfolgreich auf Karoo übertragen ({filename})!", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.CHECK_CIRCLE)
            if state.get("hh_auto_sync", True):
                if hh_client.is_authenticated:
                    log_message(f"[{time.strftime('%H:%M:%S')}] 🔄 Karoo-Transfer abgeschlossen — übermittle GPX-Route an Hammerhead...")
                    await do_push_gpx_to_hammerhead(json_str)
                else:
                    log_message(f"[{time.strftime('%H:%M:%S')}] ℹ️ Hinweis: Automatischer Hammerhead-Routenupload ist aktiv, aber noch kein Konto angemeldet.")
        else:
            show_snack(f"❌ Übertragung fehlgeschlagen: {msg}", bgcolor=ft.Colors.RED_700, icon=ft.Icons.ERROR_OUTLINE)

    # Transfer Inputs with continuous live state sync for Safari / Mobile
    def on_karoo_ip_change(e):
        state["karoo_ip"] = e.control.value.strip()
        save_settings(state)

    def on_karoo_token_change(e):
        state["karoo_token"] = e.control.value.strip().upper()
        save_settings(state)

    def on_karoo_url_change(e):
        state["karoo_url"] = e.control.value.strip()

    karoo_ip_input = ft.TextField(
        label="Karoo IP-Adresse", 
        hint_text="192.168.1.45", 
        prefix_icon=ft.Icons.ROUTER, 
        value=state.get("karoo_ip", ""),
        on_change=on_karoo_ip_change
    )
    karoo_token_input = ft.TextField(
        label="6-stelliger Code", 
        hint_text="PRDUTX", 
        prefix_icon=ft.Icons.PIN, 
        max_length=10, 
        value=state.get("karoo_token", ""),
        on_change=on_karoo_token_change
    )
    url_input = ft.TextField(
        label="Vollständige Karoo-URL", 
        hint_text="http://192.168.1.45:8080/upload?token=PRDUTX", 
        prefix_icon=ft.Icons.LINK, 
        expand=True,
        value=state.get("karoo_url", ""),
        on_change=on_karoo_url_change
    )

    async def on_send_code_click(_):
        ip = (karoo_ip_input.value or state.get("karoo_ip") or "").strip()
        token = (karoo_token_input.value or state.get("karoo_token") or "").strip().upper()
        if ip and token:
            state["karoo_ip"] = ip
            state["karoo_token"] = token
            save_settings(state)
            clean_ip = ip.replace("http://", "").replace("https://", "").split(":")[0].rstrip("/")
            full_url = f"http://{clean_ip}:8080/upload?token={token}"
            await do_push_to_karoo(full_url)
        else:
            show_snack("Bitte IP und 6-stelligen Code eingeben.", bgcolor=ft.Colors.AMBER_700, icon=ft.Icons.WARNING_AMBER)
            log_message("⚠️ Bitte IP und 6-stelligen Code eingeben.")

    async def on_send_url_click(_):
        url = (url_input.value or state.get("karoo_url") or "").strip()
        if url:
            await do_push_to_karoo(url)
        else:
            show_snack("Bitte eine Karoo-URL eingeben.", bgcolor=ft.Colors.AMBER_700, icon=ft.Icons.WARNING_AMBER)
            log_message("⚠️ Bitte eine Karoo-URL eingeben.")

    async def on_adb_push_click(_):
        if not state["calc"]:
            return
        filename = f"{state['base_filename']}_power_track.json"
        json_str = get_karoo_json()
        log_message("🔌 Starte lokalen ADB Push via USB...")
        success, msg = push_to_karoo_adb(json_str, filename)
        if success:
            log_message(f"✅ ADB Erfolg: {msg}")
            show_snack(f"✅ Per ADB nach /sdcard/PowerTracks/{filename} übertragen!", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.USB)
            if state.get("hh_auto_sync", True) and hh_client.is_authenticated:
                log_message(f"[{time.strftime('%H:%M:%S')}] 🔄 ADB-Transfer abgeschlossen — übermittle GPX-Route an Hammerhead...")
                await do_push_gpx_to_hammerhead(json_str)
        else:
            log_message(f"❌ ADB Fehler: {msg}")
            show_snack(f"❌ ADB Fehler: {msg}", bgcolor=ft.Colors.RED_700, icon=ft.Icons.ERROR_OUTLINE)

    async def save_file_locally(content_str_or_bytes, default_name):
        try:
            raw_bytes = content_str_or_bytes.encode("utf-8") if isinstance(content_str_or_bytes, str) else content_str_or_bytes
            if getattr(page, "web", False):
                await file_picker.save_file(
                    dialog_title="Datei speichern",
                    file_name=default_name,
                    src_bytes=raw_bytes
                )
            else:
                with open(default_name, "wb" if isinstance(content_str_or_bytes, (bytes, bytearray)) else "w", encoding=None if isinstance(content_str_or_bytes, (bytes, bytearray)) else "utf-8") as f:
                    f.write(content_str_or_bytes)
                show_snack(f"💾 Datei lokal gespeichert: {default_name}", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.SAVE)
        except Exception as e:
            show_snack(f"Fehler beim Speichern: {e}", bgcolor=ft.Colors.RED_700, icon=ft.Icons.ERROR_OUTLINE)

    async def on_export_json_click(_):
        if state["calc"]:
            await save_file_locally(get_karoo_json(), f"{state['base_filename']}_power_track.json")

    async def on_export_zwift_click(_):
        if state["calc"]:
            fname = f"{state['base_filename']}_workout.zwo"
            state["calc"]["optimizer"].export_to_zwift(state["calc"]["df_intervals"], fname)
            if getattr(page, "web", False) and os.path.exists(fname):
                with open(fname, "rb") as f:
                    await save_file_locally(f.read(), fname)
            else:
                show_snack(f"💾 Zwift-Workout gespeichert: {fname}", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.DIRECTIONS_BIKE)

    async def on_export_garmin_click(_):
        if state["calc"]:
            fname = f"{state['base_filename']}_workout.fit"
            state["calc"]["optimizer"].export_to_garmin_fit(state["calc"]["df_intervals"], fname)
            if getattr(page, "web", False) and os.path.exists(fname):
                with open(fname, "rb") as f:
                    await save_file_locally(f.read(), fname)
            else:
                show_snack(f"💾 Garmin-Workout gespeichert: {fname}", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.WATCH)

    # ----------------------------------------------------
    # QR CAMERA SCANNER & IMAGE PICKER
    # ----------------------------------------------------
    cam_scanner_state = {"running": False, "cap": None}

    camera_image = ft.Image(
        src=b"",
        fit=ft.BoxFit.CONTAIN,
        width=440,
        height=330,
        border_radius=8,
    )

    scanner_status = ft.Text(
        "📷 Initialisiere Kamera...",
        size=13,
        color=ft.Colors.BLUE_200,
        text_align=ft.TextAlign.CENTER,
    )

    scanner_progress = ft.ProgressBar(width=440, color=ft.Colors.BLUE_400, visible=True)

    def close_qr_camera_scanner(_=None):
        cam_scanner_state["running"] = False
        cap = cam_scanner_state.get("cap")
        if cap:
            try:
                cap.release()
            except Exception:
                pass
        cam_scanner_state["cap"] = None
        page.pop_dialog()

    async def on_fallback_pick_image(_=None):
        close_qr_camera_scanner()
        await on_pick_qr_image_file()

    async def on_retry_camera_click(_=None):
        scanner_status.value = "📷 Kamera wird neu gestartet..."
        scanner_status.color = ft.Colors.BLUE_200
        scanner_progress.visible = True
        camera_error_box.visible = False
        camera_image.visible = True
        page.update()
        if hasattr(page, "run_task"):
            page.run_task(camera_scanner_loop)
        else:
            asyncio.create_task(camera_scanner_loop())

    camera_error_box = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.VIDEOCAM_OFF_OUTLINED, color=ft.Colors.AMBER_400, size=48),
            ft.Text(
                "Kamera nicht verfügbar oder Zugriff blockiert",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=ft.Colors.AMBER_300,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                "Unter macOS: Bitte erlaube den Kamerazugriff in:\n„Systemeinstellungen > Datenschutz & Sicherheit > Kamera“.\n\nAlternativ kannst du ein QR-Code Foto laden.",
                size=12,
                color=ft.Colors.GREY_300,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Row([
                ft.FilledButton("🔄 Erneut versuchen", icon=ft.Icons.REFRESH, on_click=on_retry_camera_click),
                ft.OutlinedButton("📁 Bilddatei wählen", icon=ft.Icons.IMAGE, on_click=on_fallback_pick_image),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
        visible=False,
        padding=16,
        alignment=ft.Alignment(0, 0),
    )

    camera_viewport = ft.Container(
        content=ft.Stack([
            camera_image,
            camera_error_box,
        ], alignment=ft.Alignment(0, 0)),
        width=440,
        height=330,
        bgcolor=ft.Colors.BLACK,
        border_radius=10,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        alignment=ft.Alignment(0, 0),
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )

    qr_camera_dialog = ft.AlertDialog(
        title=ft.Row([
            ft.Icon(ft.Icons.QR_CODE_SCANNER, color=ft.Colors.BLUE_400, size=24),
            ft.Text("Karoo QR-Code scannen", size=18, weight=ft.FontWeight.BOLD),
        ], spacing=10),
        content=ft.Container(
            content=ft.Column([
                scanner_status,
                scanner_progress,
                camera_viewport,
            ], spacing=10, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=460,
        ),
        actions=[
            ft.TextButton("Abbrechen", icon=ft.Icons.CLOSE, on_click=close_qr_camera_scanner),
            ft.OutlinedButton("📁 Bilddatei wählen", icon=ft.Icons.IMAGE, on_click=on_fallback_pick_image),
        ],
        on_dismiss=close_qr_camera_scanner,
    )

    async def camera_scanner_loop():
        loop = asyncio.get_running_loop()
        cap = None
        try:
            if cv2:
                cap = await loop.run_in_executor(None, cv2.VideoCapture, 0)
        except Exception:
            cap = None

        if cap is None or not cap.isOpened():
            scanner_status.value = "⚠️ Kamera konnte nicht geöffnet werden oder Zugriff blockiert."
            scanner_status.color = ft.Colors.AMBER_400
            scanner_progress.visible = False
            camera_image.visible = False
            camera_error_box.visible = True
            page.update()
            if cap:
                try:
                    await loop.run_in_executor(None, cap.release)
                except Exception:
                    pass
            return

        cam_scanner_state["cap"] = cap
        scanner_status.value = "🎯 Richte die Kamera auf den QR-Code auf dem Karoo-Display..."
        scanner_status.color = ft.Colors.GREY_300
        scanner_progress.visible = False
        camera_image.visible = True
        camera_error_box.visible = False
        page.update()

        detected_url = None

        try:
            while cam_scanner_state["running"]:
                ret, frame = await loop.run_in_executor(None, cap.read)
                if not ret or frame is None:
                    await asyncio.sleep(0.04)
                    continue

                barcode_text = None
                barcode_points = None
                if zxingcpp:
                    try:
                        barcode = zxingcpp.read_barcode(frame)
                        if barcode and barcode.text:
                            barcode_text = barcode.text.strip()
                            if hasattr(barcode, "position") and barcode.position and np is not None:
                                barcode_points = np.array([
                                    [barcode.position.top_left.x, barcode.position.top_left.y],
                                    [barcode.position.top_right.x, barcode.position.top_right.y],
                                    [barcode.position.bottom_right.x, barcode.position.bottom_right.y],
                                    [barcode.position.bottom_left.x, barcode.position.bottom_left.y],
                                ], np.int32).reshape((-1, 1, 2))
                    except Exception:
                        pass

                if not barcode_text and cv2:
                    try:
                        detector = cv2.QRCodeDetector()
                        data, points, _ = detector.detectAndDecode(frame)
                        if data:
                            barcode_text = data.strip()
                            if points is not None and len(points) > 0 and np is not None:
                                barcode_points = points.astype(np.int32).reshape((-1, 1, 2))
                    except Exception:
                        pass

                if barcode_text:
                    txt = barcode_text
                    if "http" in txt or "token=" in txt or (len(txt) == 6 and txt.isalnum()):
                        detected_url = txt
                        try:
                            if barcode_points is not None and cv2:
                                cv2.polylines(frame, [barcode_points], True, (0, 255, 0), 4)
                        except Exception:
                            pass

                        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        camera_image.src = buf.tobytes()
                        scanner_status.value = "✅ QR-Code erkannt! Übertrage an Karoo..."
                        scanner_status.color = ft.Colors.GREEN_400
                        page.update()
                        break

                _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 55])
                camera_image.src = buf.tobytes()
                camera_image.update()
                await asyncio.sleep(0.04)
        except Exception as ex:
            log_message(f"Kamera-Scan Fehler: {ex}")
        finally:
            if cap:
                try:
                    await loop.run_in_executor(None, cap.release)
                except Exception:
                    pass
            cam_scanner_state["cap"] = None

        if detected_url and cam_scanner_state["running"]:
            cam_scanner_state["running"] = False
            await asyncio.sleep(0.35)
            page.pop_dialog()
            page.update()

            log_message(f"🎯 Karoo QR-Code erkannt: {detected_url}")
            url_input.value = detected_url
            state["karoo_url"] = detected_url

            if "token=" in detected_url and "://" in detected_url:
                try:
                    karoo_ip_input.value = detected_url.split("://")[1].split(":")[0]
                    karoo_token_input.value = detected_url.split("token=")[1].split("&")[0]
                except Exception:
                    pass
            elif len(detected_url) == 6 and detected_url.isalnum():
                karoo_token_input.value = detected_url

            show_snack(f"🎯 QR-Code erkannt: {detected_url}", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.QR_CODE)
            page.update()
            await do_push_to_karoo(detected_url)

    async def open_qr_camera_scanner(_=None):
        if not cv2:
            show_snack("Kamera-Bibliothek (OpenCV) nicht verfügbar. Nutze Bildauswahl.", bgcolor=ft.Colors.AMBER_800, icon=ft.Icons.INFO_OUTLINE)
            await on_pick_qr_image_file()
            return

        cam_scanner_state["running"] = True
        scanner_status.value = "📷 Initialisiere Kamera..."
        scanner_status.color = ft.Colors.BLUE_200
        scanner_progress.visible = True
        camera_image.visible = True
        camera_error_box.visible = False

        page.show_dialog(qr_camera_dialog)
        page.update()

        if hasattr(page, "run_task"):
            page.run_task(camera_scanner_loop)
        else:
            asyncio.create_task(camera_scanner_loop())

    async def on_pick_qr_image_file(_=None):
        try:
            files = await file_picker.pick_files(
                dialog_title="QR-Code Foto oder Bild auswählen",
                file_type=ft.FilePickerFileType.IMAGE,
                with_data=True,
                cancel_upload_on_window_blur=False,
            )
            if files and len(files) > 0:
                qr_file = files[0]
                fname = qr_file.name or (os.path.basename(qr_file.path) if qr_file.path else "qr_code.png")
                log_message(f"📷 QR-Code Bild geladen: {fname}")
                data_src = qr_file.bytes if qr_file.bytes else qr_file.path
                decoded = decode_qr_image(data_src)
                if decoded:
                    log_message(f"🎯 QR-Code erfolgreich erkannt: {decoded}")
                    url_input.value = decoded
                    state["karoo_url"] = decoded
                    if "token=" in decoded and "://" in decoded:
                        try:
                            karoo_ip_input.value = decoded.split("://")[1].split(":")[0]
                            karoo_token_input.value = decoded.split("token=")[1].split("&")[0]
                        except Exception:
                            pass
                    elif len(decoded) == 6 and decoded.isalnum():
                        karoo_token_input.value = decoded
                    show_snack(f"🎯 QR-Code erkannt: {decoded}", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.QR_CODE)
                    page.update()
                    await do_push_to_karoo(decoded)
                else:
                    log_message("⚠️ Kein QR-Code im Bild erkannt.")
                    show_snack("Kein QR-Code erkannt. Bitte Bild prüfen oder Code manuell eingeben.", bgcolor=ft.Colors.AMBER_700, icon=ft.Icons.WARNING_AMBER)
        except Exception as ex:
            show_snack(f"Fehler beim QR-Bild-Dialog: {ex}", bgcolor=ft.Colors.RED_700, icon=ft.Icons.ERROR_OUTLINE)

    sync_scan_title = ft.Text(t("sync.quick_scan"), size=14, weight=ft.FontWeight.BOLD)
    sync_scan_desc = ft.Text(t("sync.quick_scan_desc"), size=12, color=ft.Colors.GREY_400)
    sync_scan_camera_btn = ft.FilledButton(
        t("sync.scan_camera_btn"),
        icon=ft.Icons.CAMERA_ALT,
        on_click=open_qr_camera_scanner,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )
    sync_pick_image_btn = ft.OutlinedButton(
        t("sync.pick_image_btn"),
        icon=ft.Icons.IMAGE,
        on_click=on_pick_qr_image_file,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )
    manual_entry_title = ft.Text(t("sync.manual_entry"), size=14, weight=ft.FontWeight.BOLD)
    send_code_btn = ft.FilledTonalButton(t("sync.send_code_btn"), icon=ft.Icons.SEND, on_click=on_send_code_click, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))
    send_url_btn = ft.OutlinedButton(t("sync.send_url_btn"), icon=ft.Icons.WIFI_TETHERING, on_click=on_send_url_click, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))
    cloud_sync_title = ft.Text(t("sync.cloud_sync"), size=14, weight=ft.FontWeight.BOLD, expand=True)
    hh_browser_login_btn = ft.FilledTonalButton(
        t("sync.browser_login_btn"),
        icon=ft.Icons.OPEN_IN_BROWSER,
        on_click=on_hh_browser_login_click,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )
    hh_manual_upload_btn = ft.OutlinedButton(
        t("sync.manual_upload_btn"),
        icon=ft.Icons.CLOUD_UPLOAD_OUTLINED,
        on_click=on_hh_manual_upload_click,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
    )
    exports_section_title = ft.Text(t("sync.exports_title"), size=15, weight=ft.FontWeight.BOLD)
    protocol_section_title = ft.Text(t("sync.protocol_title"), size=15, weight=ft.FontWeight.BOLD)
    adb_push_btn = ft.OutlinedButton(t("sync.adb_push_btn"), icon=ft.Icons.USB, on_click=on_adb_push_click)

    tab_sync_view = ft.Container(
        content=ft.Column([
            build_kpi_overview_section(kpi_controls_t3),
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.SEND_TO_MOBILE, size=16, color=ft.Colors.AMBER_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.AMBER),
                    border_radius=8,
                    padding=6,
                ),
                ft.Text("Hammerhead Karoo Live-Sync", size=15, weight=ft.FontWeight.BOLD),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),

            # Hero Card: QR-Code Live Scanner (Fastest mobile method)
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.QR_CODE_SCANNER, size=20, color=ft.Colors.AMBER_400),
                            sync_scan_title,
                        ], spacing=8),
                        sync_scan_desc,
                        ft.Row([
                            sync_scan_camera_btn,
                            sync_pick_image_btn,
                        ], spacing=10, wrap=True),
                    ], spacing=12),
                    padding=16,
                    border_radius=16,
                ),
                shape=ft.RoundedRectangleBorder(radius=16),
            ),

            # Secondary Card: Manual IP & Token Entry
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.KEYBOARD, size=18, color=ft.Colors.BLUE_400),
                            manual_entry_title,
                        ], spacing=8),
                        ft.ResponsiveRow([
                            ft.Column([karoo_ip_input], col={"xs": 12, "sm": 7}),
                            ft.Column([karoo_token_input], col={"xs": 12, "sm": 5}),
                        ], spacing=8, run_spacing=8),
                        send_code_btn,
                        ft.Divider(height=6, color=ft.Colors.TRANSPARENT),
                        ft.Row([url_input]),
                        send_url_btn,
                    ], spacing=10),
                    padding=16,
                    border_radius=16,
                ),
                shape=ft.RoundedRectangleBorder(radius=16),
            ),

            # Hammerhead Cloud Route-Sync Card
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.CLOUD_UPLOAD, size=18, color=ft.Colors.AMBER_400),
                            cloud_sync_title,
                        ], spacing=8),
                        ft.Container(
                            content=ft.Row([
                                hh_status_icon,
                                hh_status_text,
                            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                            border_radius=10,
                            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
                        ),
                        hh_auto_sync_switch,
                        ft.Row([
                            hh_browser_login_btn,
                            hh_logout_btn,
                            hh_manual_upload_btn,
                        ], spacing=8, wrap=True),
                    ], spacing=10),
                    padding=16,
                    border_radius=16,
                ),
                shape=ft.RoundedRectangleBorder(radius=16),
            ),

            # Section: Export Files
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.SAVE_ALT, size=16, color=ft.Colors.GREEN_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.GREEN),
                    border_radius=8,
                    padding=6,
                ),
                exports_section_title,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.ResponsiveRow([
                ft.FilledTonalButton("💾 Karoo JSON", icon=ft.Icons.DOWNLOAD, col={"xs": 12, "sm": 4}, on_click=on_export_json_click),
                ft.FilledTonalButton("🚴 Zwift (.zwo)", icon=ft.Icons.DIRECTIONS_BIKE, col={"xs": 12, "sm": 4}, on_click=on_export_zwift_click),
                ft.FilledTonalButton("⌚ Garmin (.fit)", icon=ft.Icons.WATCH, col={"xs": 12, "sm": 4}, on_click=on_export_garmin_click),
            ], spacing=8, run_spacing=8),

            # Section: Protocol & Live-Log
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.RECEIPT_LONG, size=16, color=ft.Colors.PURPLE_400),
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PURPLE),
                    border_radius=8,
                    padding=6,
                ),
                protocol_section_title,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Card(
                content=ft.Container(content=log_box, padding=12, border_radius=16),
                shape=ft.RoundedRectangleBorder(radius=16),
            ),

            ft.Container(
                content=adb_push_btn,
                margin=ft.Margin.only(top=4, bottom=4)
            ),

            ft.Container(
                content=ft.Column([
                    ft.Text(f"Build {BUILD_NUMBER} · v{APP_VERSION}", size=11, color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER),
                    ft.Text(f"{BUILD_TIMESTAMP}", size=10, color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
                alignment=ft.Alignment(0, 0),
                margin=ft.Margin.only(top=6, bottom=24),
            )
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True),
        padding=16,
        expand=True
    )

    # ----------------------------------------------------
    # APP NAVIGATION & TOP BAR
    # ----------------------------------------------------
    current_view_container = ft.Container(content=tab_setup_view, expand=True)

    def on_nav_change(e):
        idx = e.control.selected_index
        if idx == 0:
            current_view_container.content = tab_setup_view
        elif idx == 1:
            if state.get("charts_dirty", False):
                img_elevation.src = render_elevation_chart()
                img_energy.src = render_energy_chart()
                intervals_column.controls = [build_intervals_table()]
                state["charts_dirty"] = False
            current_view_container.content = tab_analysis_view
        elif idx == 2:
            current_view_container.content = tab_sync_view
        page.update()

    # Settings Menu (Theme Mode & Language Switching)
    settings_menu = ft.PopupMenuButton(
        icon=ft.Icons.SETTINGS_OUTLINED,
        tooltip=t("appbar.settings_tooltip"),
        items=[],
    )

    def update_settings_menu_items():
        curr_lang = state.get("language", "de")
        is_dark = page.theme_mode == ft.ThemeMode.DARK
        theme_label = t("settings.theme_light") if is_dark else t("settings.theme_dark")
        theme_icon = ft.Icons.LIGHT_MODE if is_dark else ft.Icons.DARK_MODE

        settings_menu.tooltip = t("appbar.settings_tooltip")
        settings_menu.items = [
            ft.PopupMenuItem(
                icon=theme_icon,
                content=theme_label,
                on_click=toggle_theme,
            ),
            ft.PopupMenuItem(
                content=ft.Divider(height=1),
                disabled=True,
            ),
            ft.PopupMenuItem(
                content=t("settings.language_de"),
                checked=(curr_lang == "de"),
                on_click=lambda _: on_change_language("de"),
            ),
            ft.PopupMenuItem(
                content=t("settings.language_en"),
                checked=(curr_lang == "en"),
                on_click=lambda _: on_change_language("en"),
            ),
        ]

    def toggle_theme(_=None):
        page.theme_mode = ft.ThemeMode.LIGHT if page.theme_mode == ft.ThemeMode.DARK else ft.ThemeMode.DARK
        app_bar.bgcolor = ft.Colors.with_opacity(0.04, ft.Colors.WHITE) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.02, ft.Colors.BLACK)
        update_settings_menu_items()
        refresh_ui(route_changed=True)

    def apply_ui_translations():
        page.title = t("app.title")
        app_bar.title.value = t("app.name")
        rider_chip.tooltip = t("appbar.rider_tooltip")
        bike_chip.tooltip = t("appbar.bike_tooltip")
        route_status_chip.tooltip = t("appbar.route_tooltip")
        help_btn.tooltip = t("appbar.help_tooltip")
        
        # Navigation
        nav_bar.destinations[0].label = t("nav.setup")
        nav_bar.destinations[1].label = t("nav.analysis")
        nav_bar.destinations[2].label = t("nav.sync")

        # KPIs
        for ref in kpi_section_refs:
            ref["header_title"].value = t("kpi.section_title")
            ref["time_card"].content.controls[0].controls[1].value = t("kpi.time")
            ref["time_card"].tooltip = t("kpi.time_tooltip")
            ref["weight_card"].content.controls[0].controls[1].value = t("kpi.weight")
            ref["weight_card"].tooltip = t("kpi.weight_tooltip")
            ref["rel_ftp_card"].content.controls[0].controls[1].value = t("kpi.rel_ftp")
            ref["rel_ftp_card"].tooltip = t("kpi.rel_ftp_tooltip")
            ref["avg_power_card"].content.controls[0].controls[1].value = t("kpi.avg_power")
            ref["avg_power_card"].tooltip = t("kpi.avg_power_tooltip")
            ref["np_card"].content.controls[0].controls[1].value = t("kpi.np")
            ref["np_card"].tooltip = t("kpi.np_tooltip")
            ref["ele_card"].content.controls[0].controls[1].value = t("kpi.elevation")
            ref["ele_card"].tooltip = t("kpi.elevation_tooltip")

        # Tab 1 Dashboard & Profiles
        setup_header_title.value = t("dashboard.setup_title")
        reset_strategy_btn.tooltip = t("dashboard.reset_tooltip")
        setup_help_btn.tooltip = t("dashboard.help_tooltip")
        rider_profile_title.value = t("profile.rider_title")
        rider_profile_btn.content = t("profile.customize")
        bike_profile_title.value = t("profile.bike_title")
        bike_profile_btn.content = t("profile.customize")

        # Slider headers
        for sh in slider_headers:
            actual = t(sh["label_key"]) if sh["label_key"] else sh["fallback_label"]
            sh["label_control"].value = actual
            if sh["info_btn"]:
                sh["info_btn"].tooltip = f"Info: {actual}"

        # Dialogs
        rider_dialog_title.value = t("dialog.rider_title")
        rider_dialog_reset_btn.content = t("dialog.reset_rider")
        rider_dialog_done_btn.content = t("dialog.done")

        bike_dialog_title.value = t("dialog.bike_title")
        bike_dialog_reset_btn.content = t("dialog.reset_bike")
        bike_dialog_done_btn.content = t("dialog.done")
        lowest_gear_dropdown.label = t("slider.lowest_gear_label")
        highest_gear_dropdown.label = t("slider.highest_gear_label")

        route_dialog_title.value = t("dialog.route_title")
        route_dialog_close_btn.content = t("dialog.close")
        route_dialog_select_prompt.value = t("route.dialog_select_prompt")
        if available_gpx:
            route_dialog_folder_prompt.value = t("route.dialog_folder_prompt")
            gpx_dropdown.label = t("route.from_folder")
        route_dialog_pick_btn.content = t("route.select_file")
        route_dialog_paste_btn.content = t("route.paste_code")

        paste_dialog_title.value = t("route.paste_dialog_title")
        paste_dialog_desc.value = t("route.paste_dialog_desc")
        paste_dialog_cancel_btn.content = t("dialog.cancel")
        paste_dialog_apply_btn.content = t("route.paste_dialog_apply")
        paste_gpx_input.label = t("route.paste_dialog_label")
        paste_gpx_input.hint_text = t("route.paste_dialog_hint")

        elevation_dialog_title.value = t("dialog.elevation_title")
        elevation_dialog_desc.value = t("dialog.elevation_desc")

        # Tab 1 Card 2 & Card 3
        section2_title.value = t("section.nutrition_title")
        section2_info_btn.tooltip = f"Info: {t('section.nutrition_title')}"
        section3_title.value = t("section.route_title")
        section3_info_btn.tooltip = f"Info: {t('section.route_title')}"
        route_change_btn.content = t("route.change_button")
        route_card_pick_btn.content = t("route.select_file")
        route_card_paste_btn.content = t("route.paste_code")

        # Tab 2
        map_section_title.value = t("tab2.map_preview")
        elevation_section_title.value = t("tab2.elevation_power")
        energy_section_title.value = t("tab2.energy_tanks")
        intervals_section_title.value = t("tab2.intervals_zones")
        shopping_section_title.value = t("tab2.shopping_title")
        shopping_desc_text.value = t("tab2.shopping_subtitle")
        shopping_info_btn.tooltip = f"Info: {t('tab2.shopping_title')}"

        # Tab 3
        sync_scan_title.value = t("sync.quick_scan")
        sync_scan_desc.value = t("sync.quick_scan_desc")
        sync_scan_camera_btn.content = t("sync.scan_camera_btn")
        sync_pick_image_btn.content = t("sync.pick_image_btn")
        manual_entry_title.value = t("sync.manual_entry")
        send_code_btn.content = t("sync.send_code_btn")
        send_url_btn.content = t("sync.send_url_btn")
        cloud_sync_title.value = t("sync.cloud_sync")
        hh_browser_login_btn.content = t("sync.browser_login_btn")
        hh_logout_btn.content = t("sync.logout_btn")
        hh_manual_upload_btn.content = t("sync.manual_upload_btn")
        hh_auto_sync_switch.label = t("sync.auto_upload_switch")
        exports_section_title.value = t("sync.exports_title")
        protocol_section_title.value = t("sync.protocol_title")
        adb_push_btn.content = t("sync.adb_push_btn")

        update_pace_badge()
        update_gi_badge()
        update_gearing_badge()
        update_shopping_list()
        update_profile_summaries()
        update_settings_menu_items()

    def on_change_language(new_lang: str):
        if state.get("language") == new_lang:
            return
        state["language"] = new_lang
        set_language(new_lang)
        save_settings(state)
        apply_ui_translations()
        refresh_ui(force_charts=True)
        page.update()

    update_settings_menu_items()
    tab_setup_view.test_controls["settings_menu"] = settings_menu

    initial_tab = int(os.environ.get("POWER_PLANNER_TAB", "0"))
    if initial_tab == 1:
        img_elevation.src = render_elevation_chart()
        img_energy.src = render_energy_chart()
        intervals_column.controls = [build_intervals_table()]
        state["charts_dirty"] = False
        current_view_container.content = tab_analysis_view
    elif initial_tab == 2:
        current_view_container.content = tab_sync_view
    else:
        current_view_container.content = tab_setup_view

    nav_bar = ft.NavigationBar(
        selected_index=initial_tab,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.TUNE_OUTLINED, selected_icon=ft.Icons.TUNE, label=t("nav.setup")),
            ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART_OUTLINED, selected_icon=ft.Icons.BAR_CHART, label=t("nav.analysis")),
            ft.NavigationBarDestination(icon=ft.Icons.SEND_TO_MOBILE_OUTLINED, selected_icon=ft.Icons.SEND_TO_MOBILE, label=t("nav.sync")),
        ],
        on_change=on_nav_change
    )

    help_btn = ft.IconButton(
        icon=ft.Icons.HELP_OUTLINE,
        tooltip=t("appbar.help_tooltip"),
        on_click=open_full_help_dialog,
    )

    app_bar = ft.AppBar(
        leading=ft.Icon(ft.Icons.DIRECTIONS_BIKE, color=ft.Colors.AMBER_400, size=24),
        leading_width=32,
        title=ft.Text(t("app.name"), size=16, weight=ft.FontWeight.BOLD, no_wrap=True),
        actions=[
            rider_chip,
            bike_chip,
            route_status_chip,
            help_btn,
            settings_menu,
            ft.Container(width=4),
        ],
        bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.02, ft.Colors.BLACK),
    )

    page.appbar = app_bar
    page.navigation_bar = nav_bar
    page.add(current_view_container)


if __name__ == "__main__":
    import sys
    import socket
    is_web = "--web" in sys.argv
    port = int(os.environ.get("PORT", 9500)) if is_web else 0
    if is_web:
        host = "0.0.0.0"
        hostname = socket.gethostname()
        print(f"🚀 Starte Power-Planner Web/Mobile Server auf http://0.0.0.0:{port} (Hostname: {hostname})")
        ft.run(main, host=host, port=port, view=ft.AppView.WEB_BROWSER)
    else:
        ft.run(main)
