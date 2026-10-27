"""
i18n.py — Lightweight, cross-platform translation engine for Power-Planner.
Supports German (de) and English (en) with zero external dependencies.
"""
from typing import Dict, Any, List, Tuple
import locale

SUPPORTED_LANGUAGES = {
    "de": "Deutsch 🇩🇪",
    "en": "English 🇬🇧",
}

DEFAULT_LANGUAGE = "de"
_current_language = DEFAULT_LANGUAGE


def detect_system_language() -> str:
    """Attempts to detect system language (de/en), falling back to de."""
    try:
        loc = locale.getdefaultlocale()[0]
        if loc and loc.lower().startswith("en"):
            return "en"
    except Exception:
        pass
    return "de"


def set_language(lang: str):
    """Sets the active translation language."""
    global _current_language
    if lang in SUPPORTED_LANGUAGES:
        _current_language = lang
    else:
        _current_language = DEFAULT_LANGUAGE


def get_language() -> str:
    """Returns the currently active language code."""
    return _current_language


TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "de": {
        # App & Header
        "app.title": "🚴‍♂️ Power-Planner — Pacing & Nutrition Strategy",
        "app.name": "Power-Planner",
        "app.subtitle": "Pacing & Strategy",
        "appbar.rider_tooltip": "Fahrereinstellungen: FTP, W' & Gewicht",
        "appbar.bike_tooltip": "Radspezifische Einstellungen: Gewicht, Schaltung & Trittfrequenz",
        "appbar.route_tooltip": "Streckenauswahl & GPX-Import öffnen",
        "appbar.help_tooltip": "Hilfe & Anleitung",
        "appbar.settings_tooltip": "Einstellungen (Sprache & Farbschema)",
        
        # Settings Menu
        "settings.theme_light": "Helles Farbschema",
        "settings.theme_dark": "Dunkles Farbschema",
        "settings.language_de": "🇩🇪 Deutsch",
        "settings.language_en": "🇬🇧 English",

        # Navigation Bar
        "nav.setup": "Setup & Route",
        "nav.analysis": "Analyse & Charts",
        "nav.sync": "Karoo-Sync",

        # KPIs
        "kpi.section_title": "Übersicht & Leistungs-KPIs",
        "kpi.time": "Dauer",
        "kpi.time_tooltip": "Prognostizierte Gesamtfahrzeit",
        "kpi.weight": "Systemgewicht",
        "kpi.weight_tooltip": "Gesamtgewicht: Fahrer + Fahrrad + Ausrüstung",
        "kpi.rel_ftp": "Rel. FTP",
        "kpi.rel_ftp_tooltip": "Relative Schwellenleistung (W/kg)",
        "kpi.avg_power": "Ø Leistung",
        "kpi.avg_power_tooltip": "Durchschnittliche Zielleistung (Watt)",
        "kpi.np": "NP (Coggan)",
        "kpi.np_tooltip": "Coggan Normalized Power (30s gleitendes 4.-Potenz-Mittel)",
        "kpi.elevation": "Gesamtanstieg",
        "kpi.elevation_tooltip": "Kumulierte positive Höhenmeter",

        # Tab 1 Dashboard & Profiles
        "dashboard.setup_title": "Pacing- & Strategie-Setup",
        "dashboard.reset_tooltip": "Strategie-Standardwerte wiederherstellen",
        "dashboard.help_tooltip": "Anleitung & Hilfe öffnen",
        "profile.rider_title": "Fahrerprofil",
        "profile.bike_title": "Fahrrad & Schaltung",
        "profile.customize": "Anpassen ↗",
        "profile.w_prime_battery": "W'-Akku",
        "profile.rel": "Rel",
        "profile.cadence": "Trittfrequenz",

        # Dialogs
        "dialog.close": "Schließen",
        "dialog.done": "Fertig",
        "dialog.cancel": "Abbrechen",
        "dialog.reset_rider": "Fahrer-Standardwerte",
        "dialog.reset_bike": "Rad-Standardwerte",
        "dialog.rider_title": "Fahrereinstellungen",
        "dialog.bike_title": "Fahrrad- & Schaltungseinstellungen",
        "dialog.route_title": "Streckenauswahl & GPX-Import",
        "dialog.help_title": "Power-Planner Anleitung & Hilfe",
        "dialog.help_subtitle": "Vollständige Funktions- & Modell-Übersicht:",
        "dialog.elevation_title": "Höhendaten werden ermittelt",
        "dialog.elevation_desc": "Die Strecke enthält keine Höhendaten. Die Geländehöhen werden automatisch abgerufen:",
        "dialog.elevation_connecting": "Verbindung zur Höhen-API...",

        # Sliders & Headers
        "slider.ftp_label": "Start-FTP",
        "slider.ftp_help_title": "Start-FTP (Functional Threshold Power)",
        "slider.ftp_help_text": "Die maximale Dauerleistung in Watt, die du theoretisch 60 Minuten lang konstant halten kannst. Bildet die 100%-Referenz für alle Trainingszonen und aeroben Berechnungen.",
        "slider.wprime_label": "W'-Kapazität (Akku)",
        "slider.wprime_help_title": "W'-Kapazität (Anaerober Akku)",
        "slider.wprime_help_text": "Dein anaerober Speicher in Joule. Jede Sekunde, in der du über deiner FTP fährst, leert diesen Tank. Fährst du unterhalb der FTP, lädt er sich wieder auf (typisch: 15.000 J für Einsteiger bis 25.000+ J für Sprinter/Profis).",
        "slider.rider_w_label": "Fahrergewicht",
        "slider.rider_w_help_title": "Fahrergewicht (kg)",
        "slider.rider_w_help_text": "Dein reines Körpergewicht ohne Ausrüstung. Maßgeblich für die Steigungsleistung am Berg und die Berechnung des Leistungsgewichts (W/kg).",
        "slider.bike_w_label": "Fahrrad & Ausrüstung",
        "slider.bike_w_help_title": "Fahrrad & Ausrüstung (kg)",
        "slider.bike_w_help_text": "Das Gesamtgewicht deines Fahrrads inklusive Trinkflaschen, Bekleidung, Helm, Schuhen, Werkzeug und Riegeln.",
        "slider.lowest_gear_label": "Kleinste Übersetzung (Berggang)",
        "slider.highest_gear_label": "Größte Übersetzung (Abfahrtsgang)",
        "slider.min_cadence_label": "Minimale Kletter-Kadenz",
        "slider.min_cadence_help_title": "Minimale Kletter-Kadenz (rpm)",
        "slider.min_cadence_help_text": "Deine angestrebte Mindest-Trittfrequenz an steilen Rampen. Verhindert unphysiologisch schweres Treten.",
        "slider.max_cadence_label": "Maximale Pedalier-Kadenz (Spin-Out)",
        "slider.max_cadence_help_title": "Maximale Pedalier-Kadenz (Spin-Out)",
        "slider.max_cadence_help_text": "Deine persönliche Grenze für schnelles Treten in Abfahrten. Sobald das Tempo im größten Gang diese Kadenz überschreitet, schaltet das Pacing auf 0 W.",
        "gearing.climb_speed": "Min. Bergtempo:",
        "gearing.descent_speed": "Spin-Out Abfahrt:",

        # Nutrition & Intensity Section
        "section.nutrition_title": "Ernährungsstrategie & Intensität",
        "section.nutrition_help_title": "Ernährungsstrategie & Intensität",
        "section.nutrition_help_text": "Steuert deine Zielleistung und die stündliche Energieaufnahme. Der Glykogentank fasst ca. 2.000 kcal. Durch rechtzeitige Kohlenhydratzufuhr hältst du deine Leistungsfähigkeit bis zum letzten Berg stabil.",
        "slider.carbs_label": "Kohlenhydrate (g/h)",
        "slider.carbs_help_title": "Kohlenhydrate pro Stunde (g/h)",
        "slider.carbs_help_text": "Die geplante Zufuhr an Kohlenhydraten pro Stunde. Schützt den körpereigenen Glykogenspeicher und verzögert den Hungerast. Für Marathons werden 80-100 g/h empfohlen; Werte über 90 g/h erfordern Dual-Source Fructose/Maltodextrin und Magen-Darm-Training.",
        "slider.target_f_label": "Intensitätsfaktor (Target Factor)",
        "slider.target_f_help_title": "Intensitätsfaktor (Target Factor)",
        "slider.target_f_help_text": "Der prozentuale Anteil deiner FTP, den du im flachen und leicht ansteigenden Gelände als Basis anstrebst (z. B. 0.82 = 82% FTP). Höhere Werte verringern die Fahrzeit, leeren aber die Energiespeicher deutlich rascher.",

        # Badges
        "gi.friendly_title": "🟢 Magen-freundlich ({carbs} g/h)",
        "gi.friendly_sub": "Hohe Verträglichkeit auch nach >5h und im Hochgebirge (>2.000m)",
        "gi.limit_title": "🟡 Sportliches Limit ({carbs} g/h, 2:1 Glukose:Fruktose)",
        "gi.limit_sub": "Ab 4h Fahrzeit & Hitze sinkt Darmaufnahme auf ~70–80 g/h – Wasser & Salz/Brühe einplanen!",
        "gi.risk_title": "🔴 Hohes GI-Distress-Risiko ({carbs} g/h)",
        "gi.risk_sub": "Warnung: Übersteigt Darm-Absorption bei langen Pässen! Gefahr von Übelkeit/Magenstau – Suppe/Na+ ab 3,5h Pflicht",
        "pace.very_defensive_title": "🟢 Sehr defensiv ({pct}% FTP)",
        "pace.very_defensive_sub": "Genussfahrt & Regeneration / Minimale Glykogen-Ermüdung",
        "pace.solid_endurance_title": "🟢 Solide Ausdauer Pace ({pct}% FTP)",
        "pace.solid_endurance_sub": "Marathon-Standard / Stabiler W'-Speicher über viele Stunden",
        "pace.ambitious_title": "🟡 Ambitioniert / Sportlich ({pct}% FTP)",
        "pace.ambitious_sub": "Hohe metabolische Beanspruchung / Disziplinierte Verpflegung nötig",
        "pace.race_title": "🔴 Renn-Pace / Elite ({pct}% FTP)",
        "pace.race_sub": "Sehr hart / Hohe W'-Erschöpfung & Ausbelastung an Anstiegen",

        # Route Section
        "section.route_title": "Streckenprofil & GPX-Import",
        "section.route_help_title": "Streckenprofil & GPX-Import",
        "section.route_help_text": "Du kannst Streckendateien (.gpx) über den Dateibrowser wählen, aus dem Projektordner laden oder den XML-Code direkt einfügen. Fehlen Höhenmeter, werden diese automatisch über die SRTM Geländehöhen-API ergänzt.",
        "route.change_button": "Strecke wechseln",
        "route.select_file": "📁 GPX auswählen (.gpx)",
        "route.paste_code": "📋 GPX einfügen",
        "route.active_file": "Streckendatei:",
        "route.from_folder": "Vorhandene Strecke aus Projektordner",
        "route.dialog_select_prompt": "GPX-Datei auswählen oder einfügen:",
        "route.dialog_folder_prompt": "Aus vorhandenen Strecken wählen:",
        "route.paste_dialog_title": "📋 GPX-XML Code einfügen",
        "route.paste_dialog_desc": "Füge den XML-Code deiner GPX-Datei hier ein (ideal für Safari & Mobile):",
        "route.paste_dialog_apply": "GPX importieren",
        "route.paste_dialog_label": "GPX-XML Inhalt",
        "route.paste_dialog_hint": "Hier den Inhalt einer GPX-Datei einfügen (<gpx ...> ... </gpx>)",

        # Tab 2 (Analysis & Nutrition)
        "tab2.map_preview": "Strecken-Vorschau (Karte)",
        "tab2.elevation_power": "Höhenprofil & Ziel-Leistung",
        "tab2.energy_tanks": "Energiespeicher (W' & Glykogen)",
        "tab2.intervals_zones": "Pacing-Intervalle & Zonen",
        "tab2.shopping_title": "Sportnahrungs-Einkaufsliste",
        "tab2.shopping_subtitle": "Empfohlene Verpflegungsausrüstung für das gesamte Rennen:",
        "shopping.iso": "🥤 {count}x Iso-Portionsbeutel (à 35g KH)",
        "shopping.gels": "🧪 {count}x Standard-Gels (à 30g KH)",
        "shopping.bars": "🥮 {count}x Sportriegel / Hydro-Gels (à 40g KH)",

        # Charts
        "chart.dist_km": "Distanz (km)",
        "chart.target_power_watt": "Ziel-Leistung (Watt)",
        "chart.elevation_m": "Höhe über NN (m)",
        "chart.elevation_label": "Höhe (m)",
        "chart.storage_pct": "Speicher-Füllstand (%)",
        "chart.w_prime_label": "W'-Akku (Anaerob) %",
        "chart.glycogen_label": "Glykogentank (Metabolisch) %",
        "chart.effective_ftp_label": "Effektive FTP (Höhe & Ermüdung) %",

        # Tab 3 (Karoo-Sync)
        "sync.quick_scan": "Schneller Live-Scan (Kamera)",
        "sync.quick_scan_desc": "Scanne den QR-Code auf deinem Karoo-Display direkt mit der Kamera für eine blitzschnelle Verbindung:",
        "sync.scan_camera_btn": "QR-Code mit Kamera scannen",
        "sync.pick_image_btn": "QR-Bild wählen",
        "sync.manual_entry": "Manuelle Eingabe (Code / WLAN-IP)",
        "sync.send_code_btn": "Track mit Code an Karoo senden",
        "sync.send_url_btn": "Senden an URL",
        "sync.cloud_sync": "Hammerhead Cloud Routen-Sync (.gpx)",
        "sync.browser_login_btn": "🌐 Im Browser anmelden",
        "sync.logout_btn": "Abmelden",
        "sync.manual_upload_btn": "☁️ Route jetzt senden",
        "sync.auto_upload_switch": "Nach Karoo-Transfer automatisch in Cloud hochladen",
        "sync.exports_title": "Lokale Workout- & Dateiexporte",
        "sync.protocol_title": "Übertragungs-Protokoll & Status",
        "sync.adb_push_btn": "🔌 Entwickler: Lokaler ADB Push (USB-Kabel)",

        # Snacks & Notifications
        "snack.route_changed": "✅ Route gewechselt: {name}",
        "snack.route_loaded": "✅ Route geladen: {name}",
        "snack.strategy_reset": "Strategie-Standardwerte wiederhergestellt.",
        "snack.rider_reset": "Fahrer-Standardwerte wiederhergestellt.",
        "snack.bike_reset": "Rad-Standardwerte wiederhergestellt.",
        "snack.calc_error": "Fehler bei der Berechnung: {err}",
    },
    "en": {
        # App & Header
        "app.title": "🚴‍♂️ Power-Planner — Pacing & Nutrition Strategy",
        "app.name": "Power-Planner",
        "app.subtitle": "Pacing & Strategy",
        "appbar.rider_tooltip": "Rider settings: FTP, W' & Weight",
        "appbar.bike_tooltip": "Bike settings: Weight, Gearing & Cadence",
        "appbar.route_tooltip": "Open route selection & GPX import",
        "appbar.help_tooltip": "Help & Instructions",
        "appbar.settings_tooltip": "Settings (Language & Theme)",

        # Settings Menu
        "settings.theme_light": "Light Theme",
        "settings.theme_dark": "Dark Theme",
        "settings.language_de": "🇩🇪 Deutsch",
        "settings.language_en": "🇬🇧 English",

        # Navigation Bar
        "nav.setup": "Setup & Route",
        "nav.analysis": "Analysis & Charts",
        "nav.sync": "Karoo-Sync",

        # KPIs
        "kpi.section_title": "Overview & Performance KPIs",
        "kpi.time": "Duration",
        "kpi.time_tooltip": "Predicted total ride duration",
        "kpi.weight": "System Weight",
        "kpi.weight_tooltip": "Total weight: Rider + Bike + Equipment",
        "kpi.rel_ftp": "Rel. FTP",
        "kpi.rel_ftp_tooltip": "Relative threshold power (W/kg)",
        "kpi.avg_power": "Avg Power",
        "kpi.avg_power_tooltip": "Average target power (Watts)",
        "kpi.np": "NP (Coggan)",
        "kpi.np_tooltip": "Coggan Normalized Power (30s rolling 4th power average)",
        "kpi.elevation": "Total Ascent",
        "kpi.elevation_tooltip": "Cumulative elevation gain",

        # Tab 1 Dashboard & Profiles
        "dashboard.setup_title": "Pacing & Strategy Setup",
        "dashboard.reset_tooltip": "Restore default strategy values",
        "dashboard.help_tooltip": "Open instructions & help",
        "profile.rider_title": "Rider Profile",
        "profile.bike_title": "Bike & Gearing",
        "profile.customize": "Customize ↗",
        "profile.w_prime_battery": "W' Battery",
        "profile.rel": "Rel",
        "profile.cadence": "Cadence",

        # Dialogs
        "dialog.close": "Close",
        "dialog.done": "Done",
        "dialog.cancel": "Cancel",
        "dialog.reset_rider": "Default Rider Settings",
        "dialog.reset_bike": "Default Bike Settings",
        "dialog.rider_title": "Rider Settings",
        "dialog.bike_title": "Bike & Gearing Settings",
        "dialog.route_title": "Route Selection & GPX Import",
        "dialog.help_title": "Power-Planner Instructions & Help",
        "dialog.help_subtitle": "Complete feature and calculation model overview:",
        "dialog.elevation_title": "Fetching elevation data",
        "dialog.elevation_desc": "The route does not contain elevation data. Terrain altitudes are fetched automatically:",
        "dialog.elevation_connecting": "Connecting to elevation API...",

        # Sliders & Headers
        "slider.ftp_label": "Start FTP",
        "slider.ftp_help_title": "Start FTP (Functional Threshold Power)",
        "slider.ftp_help_text": "The maximum sustained power in Watts you can theoretically hold for 60 minutes. Represents the 100% reference for all training zones and aerobic pacing calculations.",
        "slider.wprime_label": "W' Capacity (Battery)",
        "slider.wprime_help_title": "W' Capacity (Anaerobic Battery)",
        "slider.wprime_help_text": "Your anaerobic work capacity in Joules. Every second ridden above FTP drains this tank. Riding below FTP recharges it (typically 15,000 J for beginners up to 25,000+ J for sprinters/pros).",
        "slider.rider_w_label": "Rider Weight",
        "slider.rider_w_help_title": "Rider Weight (kg)",
        "slider.rider_w_help_text": "Your net body weight without gear. Crucial for climbing resistance and power-to-weight ratio (W/kg).",
        "slider.bike_w_label": "Bike & Equipment",
        "slider.bike_w_help_title": "Bike & Equipment (kg)",
        "slider.bike_w_help_text": "The total weight of your bicycle including water bottles, clothing, helmet, shoes, tools, and nutrition.",
        "slider.lowest_gear_label": "Lowest Gear Ratio (Climbing)",
        "slider.highest_gear_label": "Highest Gear Ratio (Descent)",
        "slider.min_cadence_label": "Minimum Climbing Cadence",
        "slider.min_cadence_help_title": "Minimum Climbing Cadence (rpm)",
        "slider.min_cadence_help_text": "Target floor cadence on steep gradients. Prevents muscle-grinding at low rpm and enforces minimum necessary climbing power.",
        "slider.max_cadence_label": "Maximum Pedaling Cadence (Spin-Out)",
        "slider.max_cadence_help_title": "Maximum Pedaling Cadence (Spin-Out)",
        "slider.max_cadence_help_text": "Your personal cadence ceiling in descents. Once road speed in the highest gear exceeds this cadence, target power zeroes out (aerodynamic coasting).",
        "gearing.climb_speed": "Min climb speed:",
        "gearing.descent_speed": "Spin-out descent:",

        # Nutrition & Intensity Section
        "section.nutrition_title": "Nutrition Strategy & Intensity",
        "section.nutrition_help_title": "Nutrition Strategy & Intensity",
        "section.nutrition_help_text": "Controls target power and hourly energy intake. The body glycogen store holds ~2,000 kcal. Proper carbohydrate fueling ensures sustained performance through the final climbs.",
        "slider.carbs_label": "Carbohydrates (g/h)",
        "slider.carbs_help_title": "Carbohydrates per hour (g/h)",
        "slider.carbs_help_text": "Planned carbohydrate fueling per hour. Protects endogenous glycogen stores and delays the bonk. 80-100 g/h is recommended for marathons; >90 g/h requires dual-source fructose/maltodextrin and gut training.",
        "slider.target_f_label": "Intensity Factor (Target Factor)",
        "slider.target_f_help_title": "Intensity Factor (Target Factor)",
        "slider.target_f_help_text": "The fraction of your FTP targeted on flat and moderate terrain (e.g. 0.82 = 82% FTP). Higher values shorten ride time but drain energy tanks significantly faster.",

        # Badges
        "gi.friendly_title": "🟢 Stomach-friendly ({carbs} g/h)",
        "gi.friendly_sub": "High tolerance even after >5h and at high altitude (>2,000m)",
        "gi.limit_title": "🟡 Athletic Limit ({carbs} g/h, 2:1 Glucose:Fructose)",
        "gi.limit_sub": "After 4h and heat, gut absorption drops to ~70–80 g/h – plan water & electrolytes!",
        "gi.risk_title": "🔴 High GI Distress Risk ({carbs} g/h)",
        "gi.risk_sub": "Warning: Exceeds intestinal absorption on long passes! Risk of nausea – broth/Na+ mandatory after 3.5h",
        "pace.very_defensive_title": "🟢 Very defensive ({pct}% FTP)",
        "pace.very_defensive_sub": "Easy ride & recovery / Minimal glycogen fatigue",
        "pace.solid_endurance_title": "🟢 Solid endurance pace ({pct}% FTP)",
        "pace.solid_endurance_sub": "Marathon standard / Stable W' battery over many hours",
        "pace.ambitious_title": "🟡 Ambitious / Sportive ({pct}% FTP)",
        "pace.ambitious_sub": "High metabolic demand / Disciplined fueling required",
        "pace.race_title": "🔴 Race Pace / Elite ({pct}% FTP)",
        "pace.race_sub": "Very hard / High W' depletion and exertion on climbs",

        # Route Section
        "section.route_title": "Route Profile & GPX Import",
        "section.route_help_title": "Route Profile & GPX Import",
        "section.route_help_text": "Select GPX files via file browser, project folder, or paste raw XML code. Missing elevations are automatically augmented via the SRTM elevation API.",
        "route.change_button": "Change Route",
        "route.select_file": "📁 Select GPX (.gpx)",
        "route.paste_code": "📋 Paste GPX",
        "route.active_file": "Route file:",
        "route.from_folder": "Route from project folder",
        "route.dialog_select_prompt": "Select or paste GPX file:",
        "route.dialog_folder_prompt": "Select from available project routes:",
        "route.paste_dialog_title": "📋 Paste GPX-XML Code",
        "route.paste_dialog_desc": "Paste XML code of your GPX track here (ideal for Safari & Mobile):",
        "route.paste_dialog_apply": "Import GPX",
        "route.paste_dialog_label": "GPX-XML Content",
        "route.paste_dialog_hint": "Paste the contents of a GPX file here (<gpx ...> ... </gpx>)",

        # Tab 2 (Analysis & Nutrition)
        "tab2.map_preview": "Route Preview (Map)",
        "tab2.elevation_power": "Elevation Profile & Target Power",
        "tab2.energy_tanks": "Energy Stores (W' & Glycogen)",
        "tab2.intervals_zones": "Pacing Intervals & Zones",
        "tab2.shopping_title": "Nutrition Shopping List",
        "tab2.shopping_subtitle": "Recommended fueling supplies for the entire race:",
        "shopping.iso": "🥤 {count}x Carb drink mix packets (35g carbs each)",
        "shopping.gels": "🧪 {count}x Standard energy gels (30g carbs each)",
        "shopping.bars": "🥮 {count}x Energy bars / Hydro gels (40g carbs each)",

        # Charts
        "chart.dist_km": "Distance (km)",
        "chart.target_power_watt": "Target Power (Watts)",
        "chart.elevation_m": "Elevation above sea level (m)",
        "chart.elevation_label": "Elevation (m)",
        "chart.storage_pct": "Tank Level (%)",
        "chart.w_prime_label": "W' Battery (Anaerobic) %",
        "chart.glycogen_label": "Glycogen Tank (Metabolic) %",
        "chart.effective_ftp_label": "Effective FTP (Altitude & Fatigue) %",

        # Tab 3 (Karoo-Sync)
        "sync.quick_scan": "Quick Live Scan (Camera)",
        "sync.quick_scan_desc": "Scan the QR code on your Karoo screen with your camera for an instant connection:",
        "sync.scan_camera_btn": "Scan QR Code with Camera",
        "sync.pick_image_btn": "Pick QR Image",
        "sync.manual_entry": "Manual Entry (Code / WiFi-IP)",
        "sync.send_code_btn": "Send Track with Code to Karoo",
        "sync.send_url_btn": "Send to URL",
        "sync.cloud_sync": "Hammerhead Cloud Route Sync (.gpx)",
        "sync.browser_login_btn": "🌐 Log In via Browser",
        "sync.logout_btn": "Log Out",
        "sync.manual_upload_btn": "☁️ Send Route Now",
        "sync.auto_upload_switch": "Automatically upload to cloud after Karoo transfer",
        "sync.exports_title": "Local Workout & File Exports",
        "sync.protocol_title": "Transmission Protocol & Live Status",
        "sync.adb_push_btn": "🔌 Developer: Local ADB Push (USB Cable)",

        # Snacks & Notifications
        "snack.route_changed": "✅ Route switched: {name}",
        "snack.route_loaded": "✅ Route loaded: {name}",
        "snack.strategy_reset": "Default strategy settings restored.",
        "snack.rider_reset": "Default rider settings restored.",
        "snack.bike_reset": "Default bike settings restored.",
        "snack.calc_error": "Calculation error: {err}",
    }
}

GUIDE_SECTIONS: Dict[str, List[Tuple[str, str]]] = {
    "de": [
        ("🔧 Fahrereinstellungen & Physik", (
            "• Start-FTP (Watt): Deine maximale Schwellenleistung über 60 Minuten. Bildet die 100%-Basis für alle Zonen und Berechnungen.\n"
            "• W'-Kapazität (Joule): Dein anaerober 'Akku' (10.000–30.000 J). Jede Sekunde über der FTP entleert ihn; unterhalb der FTP lädt er sich wieder auf.\n"
            "• Fahrergewicht & Systemgewicht: Gewicht des Fahrers bzw. inklusive Rad und Ausrüstung. Bestimmt physikalisch den Steigungswiderstand an jedem Streckenmeter."
        )),
        ("🍏 Ernährungsstrategie & Magen-Absorption", (
            "• Kohlenhydrate (g/h): Geplante stündliche Energiezufuhr (Standard 80–90 g/h für Marathons).\n"
            "• Glykogenspeicher: Der 2.000 kcal Körpertank wird durch kontinuierliche Zufuhr geschützt, um den gefürchteten 'Hungerast' zu verhindern.\n"
            "• Magenverträglichkeit (GI): Bei Werten über 90 g/h warnt das System vor Magen-Darm-Stress und erhöhtem Flüssigkeits-/Elektrolytbedarf."
        )),
        ("⚙️ Schaltung, Kadenz & Pacing", (
            "• Berggang & Kletter-Kadenz: Verhindert zu schwere Gänge an Steilrampen; erzwingt im Notfall die nötige Watt-Mindestleistung.\n"
            "• Abfahrtsgang & Spin-Out: Sobald bergab die Maximal-Kadenz überschritten wird, schaltet das Pacing auf 0 W (aerodynamischer Freilauf).\n"
            "• Physiologische Dynamik: Kontinuierliche Steigungsanpassung mit Flachland-Erholung (Z2) und Tanh-Sättigung am Berg."
        )),
        ("🗺️ Streckenprofil & Höhen-API", (
            "• GPX-Import: Per Dateiauswahl, Projektordner oder GPX-XML Copy-Paste.\n"
            "• Höhen-API: Fehlen Höhendaten in der GPX-Datei, werden diese automatisch über die Open-Meteo SRTM-API abgerufen."
        )),
        ("🚴‍♂️ Karoo-Transfer & Hammerhead Cloud", (
            "• QR-Kamera-Scan: Hältst du die Kamera auf den Karoo-QR-Code, wird die Route sofort per WLAN übertragen.\n"
            "• Manuelle Eingabe: Schnelle Kopplung per IP und 6-stelligem Code oder URL.\n"
            "• Hammerhead Cloud Sync: Lädt nach erfolgreichem Karoo-Transfer die Route automatisch als .gpx in dein Hammerhead Dashboard hoch."
        )),
        ("💾 Workout-Exporte & Sportnahrungs-Einkaufsliste", (
            "• Dateiexporte: Karoo Power-Track JSON (.ptj), Zwift Workout (.zwo), Garmin Workout (.fit).\n"
            "• Einkaufsliste: Berechnet deinen exakten Bedarf an Iso-Flaschen, Gels und Riegeln für das gesamte Rennen."
        )),
    ],
    "en": [
        ("🔧 Rider Settings & Physics", (
            "• Start FTP (Watts): Your maximum 60-minute threshold power. Serves as the 100% reference for all training zones and calculations.\n"
            "• W' Capacity (Joules): Your anaerobic 'battery' (10,000–30,000 J). Every second above FTP depletes it; riding below FTP recharges it.\n"
            "• Rider & System Weight: Weight of the rider alone and combined with bicycle and gear. Governs gravity resistance on every gradient."
        )),
        ("🍏 Nutrition Strategy & Gut Absorption", (
            "• Carbohydrates (g/h): Planned hourly energy intake (standard 80–90 g/h for marathons).\n"
            "• Glycogen Stores: The body's 2,000 kcal tank is shielded by steady carbohydrate intake to prevent the bonk.\n"
            "• GI Tolerance: At fueling rates >90 g/h, the system alerts to GI distress risks and increased hydration/sodium needs."
        )),
        ("⚙️ Gearing, Cadence & Pacing", (
            "• Lowest Gear & Climbing Cadence: Prevents grinding on steep ramps; enforces minimum power when cadence floor is reached.\n"
            "• Highest Gear & Spin-Out: When descent speed exceeds maximum pedaling cadence, power drops to 0 W (aerodynamic coasting).\n"
            "• Physiological Dynamics: Continuous gradient adaptation with Zone 2 recovery on flats and tanh climb saturation."
        )),
        ("🗺️ Route Profile & Elevation API", (
            "• GPX Import: Via file picker, project folder, or direct XML copy-paste.\n"
            "• Elevation API: If GPX data lacks elevations, missing altitudes are fetched automatically via Open-Meteo SRTM API."
        )),
        ("🚴‍♂️ Karoo Transfer & Hammerhead Cloud", (
            "• QR Camera Scan: Point camera at Karoo QR code to transfer pacing tracks over WiFi in seconds.\n"
            "• Manual Entry: Fast pairing via IP and 6-digit code or URL.\n"
            "• Hammerhead Cloud Sync: Automatically uploads the route as a .gpx file to your Hammerhead dashboard after Karoo transfer."
        )),
        ("💾 Workout Exports & Nutrition Shopping List", (
            "• File Exports: Karoo Power-Track JSON (.ptj), Zwift Workout (.zwo), Garmin Workout (.fit).\n"
            "• Shopping List: Computes exact race demand for electrolyte drink mix packets, energy gels, and bars."
        )),
    ]
}


def t(key: str, **kwargs) -> str:
    """Translates key for the active language, with fallback to de and format interpolation."""
    lang_dict = TRANSLATIONS.get(_current_language, TRANSLATIONS[DEFAULT_LANGUAGE])
    val = lang_dict.get(key)
    if val is None:
        # Fallback to German
        val = TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
    if kwargs:
        try:
            return val.format(**kwargs)
        except Exception:
            return val
    return val


def get_guide_sections(lang: str = None) -> List[Tuple[str, str]]:
    """Returns the help guide sections for the specified or current language."""
    selected_lang = lang or _current_language
    return GUIDE_SECTIONS.get(selected_lang, GUIDE_SECTIONS[DEFAULT_LANGUAGE])
