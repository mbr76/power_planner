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

import flet as ft
from pacing_optimizer import AdvancedPacingOptimizer

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


def fetch_map_background(min_lat, max_lat, min_lon, max_lon, zoom=10, is_dark=True):
    try:
        import urllib.request
        x0, y0 = deg2num(max_lat, min_lon, zoom)
        x1, y1 = deg2num(min_lat, max_lon, zoom)

        tile_w, tile_h = 256, 256
        num_x = abs(x1 - x0) + 1
        num_y = abs(y1 - y0) + 1

        if num_x * num_y > 36 and zoom > 6:
            return fetch_map_background(min_lat, max_lat, min_lon, max_lon, zoom - 1, is_dark)

        combined = Image.new("RGB", (num_x * tile_w, num_y * tile_h))
        style = "dark_all" if is_dark else "rastertiles/voyager"

        for i, x in enumerate(range(min(x0, x1), max(x0, x1) + 1)):
            for j, y in enumerate(range(min(y0, y1), max(y0, y1) + 1)):
                url = f"https://a.basemaps.cartocdn.com/{style}/{zoom}/{x}/{y}.png"
                req = urllib.request.Request(url, headers={"User-Agent": "PowerPlanner/2.0"})
                try:
                    with urllib.request.urlopen(req, timeout=2.5) as resp:
                        tile_img = Image.open(io.BytesIO(resp.read()))
                        combined.paste(tile_img, (i * tile_w, j * tile_h))
                except Exception:
                    pass

        nw_lat, nw_lon = num2deg(min(x0, x1), min(y0, y1), zoom)
        se_lat, se_lon = num2deg(max(x0, x1) + 1, max(y0, y1) + 1, zoom)
        extent = [nw_lon, se_lon, se_lat, nw_lat]
        return combined, extent
    except Exception:
        return None, None


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
    if os.path.exists(p):
        return p
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
    if hasattr(sys, '_MEIPASS'):
        search_dirs.append(sys._MEIPASS)
    for base_dir in search_dirs:
        for root, dirs, filenames in os.walk(base_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "pacing-env" and d != "__pycache__"]
            for f in filenames:
                if f.lower().endswith(".gpx"):
                    name = os.path.basename(f)
                    if name not in files:
                        files.append(name)
    return sorted(files)


# ==========================================
# MAIN FLET APPLICATION CONTROLLER
# ==========================================

async def main(page: ft.Page):
    page.title = "🚴‍♂️ Power-Planner — Pacing & Nutrition Strategy"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.scroll = ft.ScrollMode.ADAPTIVE
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

    # Application State
    state = {
        "initial_ftp": 310,
        "w_prime": 20000,
        "rider_w": 76.0,
        "bike_w": 8.0,
        "carbs_per_hour": 90,
        "target_f": 0.82,
        "gpx_path": "oetztaler_route.gpx",
        "gpx_content": None,
        "base_filename": "oetztaler_route",
        "df_route": None,
        "calc": None,
        "karoo_ip": "",
        "karoo_token": "",
        "logs": []
    }

    # ----------------------------------------------------
    # Calculation & Chart Rendering Engine (Ultra-Fast)
    # ----------------------------------------------------
    def run_calculation():
        try:
            optimizer = AdvancedPacingOptimizer(
                initial_ftp=state["initial_ftp"],
                w_prime_max=state["w_prime"],
                target_factor=state["target_f"],
                carb_intake_per_hour=state["carbs_per_hour"],
                rider_weight=state["rider_w"],
                bike_weight=state["bike_w"]
            )
            if state["df_route"] is None:
                source = state.get("gpx_content") or resolve_path(state["gpx_path"])
                state["df_route"] = optimizer.parse_gpx(source)
            df_route = state["df_route"]
            df_raw = optimizer.generate_raw_pacing_dataframe(df_route)
            df_intervals = optimizer._segment_intervals(df_raw)
            
            total_hours = df_raw['duration_sec'].sum() / 3600.0
            h = math.floor(total_hours)
            m = round((total_hours % 1) * 60)
            sys_weight = state["rider_w"] + state["bike_w"]
            rel_ftp = state["initial_ftp"] / state["rider_w"]
            total_carbs = total_hours * state["carbs_per_hour"]

            state["calc"] = {
                "optimizer": optimizer,
                "df_raw": df_raw,
                "df_intervals": df_intervals,
                "total_hours": total_hours,
                "duration_str": f"{h:02d}:{m:02d} Std",
                "sys_weight_str": f"{sys_weight:.1f} kg",
                "rel_ftp_str": f"{rel_ftp:.2f} W/kg",
                "total_carbs_str": f"{total_carbs:.1f} g",
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

        is_dark = page.theme_mode == ft.ThemeMode.DARK
        bg_color = '#18181B' if is_dark else '#FFFFFF'
        plot_bg = '#1E1E24' if is_dark else '#F9FAFB'
        text_color = '#E4E4E7' if is_dark else '#1F2937'
        tick_color = '#A1A1AA' if is_dark else '#6B7280'
        grid_color = '#333338' if is_dark else '#E5E7EB'

        min_lat, max_lat = df_route['latitude'].min(), df_route['latitude'].max()
        min_lon, max_lon = df_route['longitude'].min(), df_route['longitude'].max()

        bg_img, extent = fetch_map_background(min_lat, max_lat, min_lon, max_lon, zoom=10, is_dark=is_dark)

        fig, ax = plt.subplots(figsize=(10, 4.8), dpi=100)
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(plot_bg)

        if bg_img and extent:
            ax.imshow(bg_img, extent=extent, aspect='equal', origin='upper')
            # Route line with contrast border
            ax.plot(df_route['longitude'], df_route['latitude'], color='#000000' if is_dark else '#FFFFFF', linewidth=4.0, alpha=0.6)
            ax.plot(df_route['longitude'], df_route['latitude'], color='#F59E0B', linewidth=2.8, label='Streckenverlauf')
        else:
            scatter = ax.scatter(df_route['longitude'], df_route['latitude'], c=df_route['elevation'], cmap='turbo', s=3.5, alpha=0.9, rasterized=True)
            ax.plot(df_route['longitude'], df_route['latitude'], color='#FFFFFF' if is_dark else '#000000', linewidth=0.5, alpha=0.3)
            cbar = fig.colorbar(scatter, ax=ax, pad=0.02)
            cbar.set_label('Höhe über NN (m)', color=text_color, fontsize=9, fontweight='bold')
            cbar.ax.yaxis.set_tick_params(color=tick_color)
            plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color=tick_color)

        # Start and End markers
        ax.scatter(df_route['longitude'].iloc[0], df_route['latitude'].iloc[0], color='#10B981', s=90, zorder=6, edgecolors='#FFFFFF', linewidths=1.5, label='Start')
        ax.scatter(df_route['longitude'].iloc[-1], df_route['latitude'].iloc[-1], color='#EF4444', s=90, marker='s', zorder=6, edgecolors='#FFFFFF', linewidths=1.5, label='Ziel')

        ax.set_xlim(min_lon - 0.04, max_lon + 0.04)
        ax.set_ylim(min_lat - 0.03, max_lat + 0.03)

        ax.set_xlabel('Längengrad (°E)', color=text_color, fontsize=9, fontweight='bold')
        ax.set_ylabel('Breitengrad (°N)', color=text_color, fontsize=9, fontweight='bold')
        ax.tick_params(colors=tick_color, labelsize=8)
        ax.grid(True, linestyle='--', alpha=0.25, color=grid_color)
        ax.legend(facecolor=plot_bg, edgecolor=grid_color, labelcolor=text_color, loc='upper right', fontsize=9)

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
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
        ax1.fill_between(df_raw['distance_km'], df_raw['target_power'], step='mid', color='#F59E0B', alpha=0.55, label='Ziel-Leistung (Watt)', rasterized=True)
        ax1.set_xlabel('Distanz (km)', color=text_color, fontsize=9, fontweight='bold')
        ax1.set_ylabel('Ziel-Leistung (Watt)', color='#F59E0B', fontsize=9, fontweight='bold')
        ax1.tick_params(colors=tick_color, labelsize=8)
        ax1.set_ylim(0, max(450, int(state["initial_ftp"] * 1.4)))
        ax1.grid(True, linestyle='--', alpha=0.25, color=grid_color)

        # Elevation profile
        ax2 = ax1.twinx()
        if 'elevation' in df_route.columns and not df_route['elevation'].isna().all():
            y_ele = df_route['elevation']
        else:
            y_ele = (df_route['slope'] * (df_route['segment_len_m'] / 100.0)).cumsum() + 1377

        ax2.plot(df_route['distance_km'], y_ele, color='#38BDF8', linewidth=2.0, label='Höhe (m)')
        ax2.fill_between(df_route['distance_km'], y_ele, alpha=0.15, color='#38BDF8', rasterized=True)
        ax2.set_ylabel('Höhe über NN (m)', color='#38BDF8', fontsize=9, fontweight='bold')
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

        ax.plot(df_raw['distance_km'], df_raw['w_prime_pct'], color='#EF4444', linewidth=2.0, label="W'-Akku (Anaerob) %")
        ax.plot(df_raw['distance_km'], df_raw['glycogen_pct'], color='#10B981', linewidth=2.2, linestyle='--', label='Glykogentank (Metabolisch) %')
        
        ax.set_xlabel('Distanz (km)', color=text_color, fontsize=9, fontweight='bold')
        ax.set_ylabel('Speicher-Füllstand (%)', color=text_color, fontsize=9, fontweight='bold')
        ax.set_ylim(0, 105)
        ax.tick_params(colors=tick_color, labelsize=8)
        ax.grid(True, linestyle='--', alpha=0.25, color=grid_color)
        ax.legend(facecolor=plot_bg, edgecolor=grid_color, labelcolor=text_color, loc='lower left', fontsize=9)

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

    # Pace Traffic Light Label
    pace_badge_text = ft.Text(size=12, weight=ft.FontWeight.BOLD)
    pace_badge = ft.Container(
        content=pace_badge_text,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        border_radius=8,
    )

    def update_pace_badge():
        tf = state["target_f"]
        if tf < 0.71:
            pace_badge_text.value = "🟢 Sehr defensiv (Genussfahrt / Regenerativ)"
            pace_badge.bgcolor = ft.Colors.with_opacity(0.2, ft.Colors.GREEN)
        elif tf < 0.78:
            pace_badge_text.value = "🟢 Solide Ausdauer Pace (Marathon-Standard)"
            pace_badge.bgcolor = ft.Colors.with_opacity(0.2, ft.Colors.GREEN)
        elif tf < 0.84:
            pace_badge_text.value = "🟡 Ambitioniert / Sportlich (Hohe Ermüdung)"
            pace_badge.bgcolor = ft.Colors.with_opacity(0.2, ft.Colors.AMBER)
        else:
            pace_badge_text.value = "🔴 Renn-Pace / Elite (Sehr hart, Ausbelastung)"
            pace_badge.bgcolor = ft.Colors.with_opacity(0.2, ft.Colors.RED)

    update_pace_badge()

    # Dynamic KPI Cards
    kpi_time = ft.Text(state["calc"]["duration_str"] if state["calc"] else "-", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)
    kpi_weight = ft.Text(state["calc"]["sys_weight_str"] if state["calc"] else "-", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_400)
    kpi_rel_ftp = ft.Text(state["calc"]["rel_ftp_str"] if state["calc"] else "-", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)
    kpi_carbs = ft.Text(state["calc"]["total_carbs_str"] if state["calc"] else "-", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE_400)

    def make_kpi_card(icon, label, value_control, col_span=6):
        return ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon(icon, size=18, color=ft.Colors.GREY_400), ft.Text(label, size=12, color=ft.Colors.GREY_400)]),
                value_control
            ], spacing=4),
            padding=14,
            border_radius=12,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.04, ft.Colors.BLACK),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.1, ft.Colors.BLACK)),
            col={"xs": 12, "sm": col_span, "md": 3},
        )

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
                z_color, z_bg, z_name = ft.Colors.GREY_400, ft.Colors.with_opacity(0.15, ft.Colors.GREY), "Z1 Recovery"
            elif pct < 75:
                z_color, z_bg, z_name = ft.Colors.GREEN_400, ft.Colors.with_opacity(0.15, ft.Colors.GREEN), "Z2 Endurance"
            elif pct < 90:
                z_color, z_bg, z_name = ft.Colors.AMBER_400, ft.Colors.with_opacity(0.15, ft.Colors.AMBER), "Z3 Tempo"
            elif pct < 105:
                z_color, z_bg, z_name = ft.Colors.ORANGE_400, ft.Colors.with_opacity(0.15, ft.Colors.ORANGE), "Z4 Threshold"
            elif pct < 120:
                z_color, z_bg, z_name = ft.Colors.RED_400, ft.Colors.with_opacity(0.15, ft.Colors.RED), "Z5 VO2Max"
            else:
                z_color, z_bg, z_name = ft.Colors.PURPLE_400, ft.Colors.with_opacity(0.15, ft.Colors.PURPLE), "Z6 Anaerobic"

            dur_str = format_to_iso_duration(row['duration_min'])
            rows.append(
                ft.Container(
                    content=ft.ResponsiveRow([
                        ft.Text(f"{row['start_km']:.2f} - {row['end_km']:.2f} km", col={"xs": 4, "sm": 3}, size=13, weight=ft.FontWeight.W_500),
                        ft.Text(f"⏱️ {dur_str}", col={"xs": 3, "sm": 2}, size=13),
                        ft.Text(f"⚡ {int(row['target_watt'])} W", col={"xs": 2, "sm": 2}, size=13, weight=ft.FontWeight.BOLD),
                        ft.Container(
                            content=ft.Text(f"{z_name} ({pct:.0f}%)", size=11, weight=ft.FontWeight.BOLD, color=z_color),
                            bgcolor=z_bg,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                            border_radius=6,
                            col={"xs": 3, "sm": 5}
                        )
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    border_radius=8,
                    bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE) if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.with_opacity(0.02, ft.Colors.BLACK),
                )
            )
        return ft.Column(rows, spacing=6)

    intervals_column.controls = [build_intervals_table()]

    def refresh_ui(route_changed=False, force_charts=False):
        state["karoo_json_str"] = None  # Invalidate lazy Karoo JSON on changes
        success, err = run_calculation()
        if success and state["calc"]:
            kpi_time.value = state["calc"]["duration_str"]
            kpi_weight.value = state["calc"]["sys_weight_str"]
            kpi_rel_ftp.value = state["calc"]["rel_ftp_str"]
            kpi_carbs.value = state["calc"]["total_carbs_str"]
            
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
            route_status_chip.label = ft.Text(f"📍 {os.path.basename(state['gpx_path'])}")
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
        label="GPX-XML Inhalt",
        hint_text="Hier den Inhalt einer GPX-Datei einfügen (<gpx ...> ... </gpx>)",
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

    paste_dialog = ft.AlertDialog(
        title=ft.Text("📋 GPX-XML Code einfügen"),
        content=ft.Container(
            content=ft.Column([
                ft.Text("Füge den XML-Code deiner GPX-Datei hier ein (ideal für Safari & Mobile):", size=13, color=ft.Colors.GREY_400),
                paste_gpx_input
            ], spacing=10, tight=True),
            width=500
        ),
        actions=[
            ft.TextButton("Abbrechen", on_click=close_paste_dialog),
            ft.FilledButton("GPX importieren", icon=ft.Icons.CHECK, on_click=on_paste_gpx_apply)
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
            gpx_file_text.value = f"Aktuelle Route: {os.path.basename(selected)}"
            refresh_ui(route_changed=True, force_charts=True)
            show_snack(f"✅ Route gewechselt: {os.path.basename(selected)}", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.CHECK_CIRCLE)

    gpx_dropdown = ft.Dropdown(
        label="Vorhandene Strecke aus Projektordner",
        options=[ft.dropdown.Option(key=f, text=f"📍 {f}") for f in available_gpx],
        value=state["gpx_path"] if state["gpx_path"] in available_gpx else (available_gpx[0] if available_gpx else None),
        expand=True,
        on_select=on_select_local_gpx
    )
    gpx_file_text = ft.Text(f"Aktuelle Route: {os.path.basename(state['gpx_path'])}", size=13, color=ft.Colors.GREY_300)

    tab_setup_view = ft.Container(
        content=ft.Column([
            ft.Text("🔧 Fahrereinstellungen & Pacing-Parameter", size=16, weight=ft.FontWeight.BOLD),
            
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([ft.Text("Start-FTP (Functional Threshold Power)", size=13, weight=ft.FontWeight.W_500), ftp_val_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Slider(min=100, max=500, divisions=80, value=state["initial_ftp"], on_change=on_ftp_change, on_change_end=on_ftp_change_end),

                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                        ft.Row([ft.Text("W'-Kapazität (Anaerober Akku)", size=13, weight=ft.FontWeight.W_500), wprime_val_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Slider(min=10000, max=30000, divisions=20, value=state["w_prime"], on_change=on_wprime_change, on_change_end=on_wprime_change_end),

                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                        ft.ResponsiveRow([
                            ft.Column([
                                ft.Row([ft.Text("Fahrergewicht", size=13), rider_w_val_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Slider(min=40, max=130, divisions=90, value=state["rider_w"], on_change=on_rider_w_change, on_change_end=on_rider_w_change_end),
                            ], col={"xs": 12, "md": 6}),
                            ft.Column([
                                ft.Row([ft.Text("Fahrrad- & Ausrüstungsgewicht", size=13), bike_w_val_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Slider(min=5, max=20, divisions=30, value=state["bike_w"], on_change=on_bike_w_change, on_change_end=on_bike_w_change_end),
                            ], col={"xs": 12, "md": 6}),
                        ]),
                    ]),
                    padding=16,
                )
            ),

            ft.Text("🍏 Ernährungsstrategie & Intensität", size=16, weight=ft.FontWeight.BOLD),
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([ft.Text("Kohlenhydrate pro Stunde (g/h)", size=13, weight=ft.FontWeight.W_500), carbs_val_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Slider(min=20, max=120, divisions=20, value=state["carbs_per_hour"], on_change=on_carbs_change, on_change_end=on_carbs_change_end),

                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                        ft.Row([ft.Text("Intensitätsfaktor (Target Factor)", size=13, weight=ft.FontWeight.W_500), target_f_val_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Slider(min=0.60, max=1.00, divisions=40, value=state["target_f"], on_change=on_target_f_change, on_change_end=on_target_f_change_end),
                        pace_badge,
                    ]),
                    padding=16,
                )
            ),

            ft.Text("🛣️ Streckenprofil (GPX-Import)", size=16, weight=ft.FontWeight.BOLD),
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.ResponsiveRow([
                            ft.Column([
                                ft.Text("Eigene GPX-Strecke (.gpx) laden oder einfügen", size=14, weight=ft.FontWeight.BOLD),
                                gpx_file_text
                            ], col={"xs": 12, "md": 6}),
                            ft.Row([
                                ft.FilledButton(
                                    "📁 GPX auswählen (.gpx)",
                                    icon=ft.Icons.UPLOAD_FILE,
                                    on_click=on_pick_gpx_click
                                ),
                                ft.OutlinedButton(
                                    "📋 GPX einfügen",
                                    icon=ft.Icons.PASTE,
                                    on_click=open_paste_dialog
                                )
                            ], col={"xs": 12, "md": 6}, alignment=ft.MainAxisAlignment.END),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Divider(height=10, color=ft.Colors.TRANSPARENT) if available_gpx else ft.Container(),
                        ft.Row([gpx_dropdown]) if available_gpx else ft.Container(),
                    ]),
                    padding=16,
                )
            ),
        ], spacing=16),
        padding=10
    )

    # ----------------------------------------------------
    # TAB 2: ANALYSE & CHARTS
    # ----------------------------------------------------
    tab_analysis_view = ft.Container(
        content=ft.Column([
            ft.Text("📊 Übersicht & Key Performance Indicators", size=16, weight=ft.FontWeight.BOLD),
            ft.ResponsiveRow([
                make_kpi_card(ft.Icons.TIMER_OUTLINED, "Prognostizierte Fahrzeit", kpi_time),
                make_kpi_card(ft.Icons.FITNESS_CENTER_OUTLINED, "Systemgewicht Gesamt", kpi_weight),
                make_kpi_card(ft.Icons.BOLT_OUTLINED, "Relative FTP (W/kg)", kpi_rel_ftp),
                make_kpi_card(ft.Icons.RESTAURANT_OUTLINED, "Gesamtbedarf KH", kpi_carbs),
            ]),

            ft.Text("🗺️ Strecken-Vorschau (Geografischer Verlauf)", size=16, weight=ft.FontWeight.BOLD),
            ft.Card(content=ft.Container(content=img_map, padding=10)),

            ft.Text("📈 Höhenprofil & Segment-Leistung", size=16, weight=ft.FontWeight.BOLD),
            ft.Card(content=ft.Container(content=img_elevation, padding=10)),

            ft.Text("🔋 Energiespeicher & Ermüdungsverlauf (W' vs. Glykogen)", size=16, weight=ft.FontWeight.BOLD),
            ft.Card(content=ft.Container(content=img_energy, padding=10)),

            ft.Text("📋 Berechnete Intervall-Blöcke (Zonen-Farbcodierung)", size=16, weight=ft.FontWeight.BOLD),
            ft.Card(content=ft.Container(content=intervals_column, padding=12)),
        ], spacing=16),
        padding=10
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
        else:
            show_snack(f"❌ Übertragung fehlgeschlagen: {msg}", bgcolor=ft.Colors.RED_700, icon=ft.Icons.ERROR_OUTLINE)

    # Transfer Inputs with continuous live state sync for Safari / Mobile
    def on_karoo_ip_change(e):
        state["karoo_ip"] = e.control.value.strip()

    def on_karoo_token_change(e):
        state["karoo_token"] = e.control.value.strip().upper()

    def on_karoo_url_change(e):
        state["karoo_url"] = e.control.value.strip()

    karoo_ip_input = ft.TextField(
        label="Karoo IP-Adresse", 
        hint_text="192.168.1.45", 
        prefix_icon=ft.Icons.ROUTER, 
        expand=True,
        value=state.get("karoo_ip", ""),
        on_change=on_karoo_ip_change
    )
    karoo_token_input = ft.TextField(
        label="6-stelliger Code", 
        hint_text="PRDUTX", 
        prefix_icon=ft.Icons.PIN, 
        max_length=10, 
        width=150,
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

    def on_adb_push_click(_):
        if not state["calc"]:
            return
        filename = f"{state['base_filename']}_power_track.json"
        json_str = get_karoo_json()
        log_message("🔌 Starte lokalen ADB Push via USB...")
        success, msg = push_to_karoo_adb(json_str, filename)
        if success:
            log_message(f"✅ ADB Erfolg: {msg}")
            show_snack(f"✅ Per ADB nach /sdcard/PowerTracks/{filename} übertragen!", bgcolor=ft.Colors.GREEN_700, icon=ft.Icons.USB)
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

    tab_sync_view = ft.Container(
        content=ft.Column([
            ft.Text("📱 Hammerhead Karoo Drahtlos-Übertragung (WLAN)", size=16, weight=ft.FontWeight.BOLD),
            
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Text("Methode 1: 6-Stelliger Code (Vom Karoo-Display)", size=14, weight=ft.FontWeight.BOLD),
                        ft.Row([karoo_ip_input, karoo_token_input]),
                        ft.FilledButton("🚀 Track mit Code an Karoo senden", icon=ft.Icons.SEND, on_click=on_send_code_click),
                    ], spacing=12),
                    padding=16
                )
            ),

            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Text("Methode 2: Live QR-Code Scanner (Kamera)", size=14, weight=ft.FontWeight.BOLD),
                        ft.Text("Scanne den QR-Code auf deinem Karoo-Display direkt live mit deiner Webcam/Kamera:", size=12, color=ft.Colors.GREY_400),
                        ft.Row([
                            ft.FilledButton(
                                "📷 QR-Code mit Kamera scannen",
                                icon=ft.Icons.CAMERA_ALT,
                                on_click=open_qr_camera_scanner
                            ),
                            ft.OutlinedButton(
                                "📁 Bilddatei wählen",
                                icon=ft.Icons.IMAGE,
                                on_click=on_pick_qr_image_file
                            ),
                        ], spacing=12),
                    ], spacing=12),
                    padding=16
                )
            ),

            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Text("Methode 3: Direkte Karoo-WLAN-URL", size=14, weight=ft.FontWeight.BOLD),
                        ft.Row([url_input]),
                        ft.FilledButton("📡 Senden an URL", icon=ft.Icons.WIFI_TETHERING, on_click=on_send_url_click),
                    ], spacing=12),
                    padding=16
                )
            ),

            ft.Text("📋 Übertragungs-Protokoll & Live-Log", size=16, weight=ft.FontWeight.BOLD),
            log_box,

            ft.Divider(height=15),
            ft.Text("💾 Lokale Workout- & Dateiexporte", size=16, weight=ft.FontWeight.BOLD),
            ft.ResponsiveRow([
                ft.FilledTonalButton("💾 Karoo JSON speichern", icon=ft.Icons.DOWNLOAD, col={"xs": 12, "sm": 4}, on_click=on_export_json_click),
                ft.FilledTonalButton("🚴 Zwift (.zwo) speichern", icon=ft.Icons.DIRECTIONS_BIKE, col={"xs": 12, "sm": 4}, on_click=on_export_zwift_click),
                ft.FilledTonalButton("⌚ Garmin (.fit) speichern", icon=ft.Icons.WATCH, col={"xs": 12, "sm": 4}, on_click=on_export_garmin_click),
            ]),

            ft.Container(
                content=ft.OutlinedButton("🔌 Entwickler: Lokaler ADB Push (USB-Kabel)", icon=ft.Icons.USB, on_click=on_adb_push_click),
                margin=ft.Margin.only(top=10)
            )
        ], spacing=16),
        padding=10
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

    def toggle_theme(_):
        page.theme_mode = ft.ThemeMode.LIGHT if page.theme_mode == ft.ThemeMode.DARK else ft.ThemeMode.DARK
        theme_btn.icon = ft.Icons.DARK_MODE if page.theme_mode == ft.ThemeMode.LIGHT else ft.Icons.LIGHT_MODE
        refresh_ui(route_changed=True)

    theme_btn = ft.IconButton(
        icon=ft.Icons.LIGHT_MODE,
        tooltip="Farbschema wechseln",
        on_click=toggle_theme
    )

    route_status_chip = ft.Chip(
        label=ft.Text(f"📍 {os.path.basename(state['gpx_path'])}", size=12),
        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.AMBER)
    )

    nav_bar = ft.NavigationBar(
        selected_index=0,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.TUNE_OUTLINED, selected_icon=ft.Icons.TUNE, label="Setup & Route"),
            ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART_OUTLINED, selected_icon=ft.Icons.BAR_CHART, label="Analyse & Charts"),
            ft.NavigationBarDestination(icon=ft.Icons.SEND_TO_MOBILE_OUTLINED, selected_icon=ft.Icons.SEND_TO_MOBILE, label="Karoo-Sync"),
        ],
        on_change=on_nav_change
    )

    app_bar = ft.AppBar(
        leading=ft.Icon(ft.Icons.DIRECTIONS_BIKE, color=ft.Colors.AMBER_400, size=28),
        leading_width=40,
        title=ft.Column([
            ft.Text("Power-Planner", size=18, weight=ft.FontWeight.BOLD),
            ft.Text("Pacing & Nutrition Strategy", size=11, color=ft.Colors.GREY_400),
        ], spacing=1),
        actions=[
            route_status_chip,
            theme_btn,
            ft.Container(width=8)
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
