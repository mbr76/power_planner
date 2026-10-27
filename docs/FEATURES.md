# Power-Planner — Vollständige Feature-Dokumentation & Referenz

> **Zweck dieser Datei:**  
> Dieses Dokument dient als verbindliche Referenz für alle implementierten Funktionen, Berechnungsmodelle, UI-Komponenten und Schnittstellen des **Power-Planner**-Projekts. Bei zukünftigen Refactorings, Updates oder Erweiterungen darf **keine** der hier dokumentierten Funktionen ohne ausdrücklichen Nutzerwunsch entfernt, gekürzt oder „wegoptimiert“ werden.

---

## 1. Physikalisches Pacing- & Berechnungsmodell (`pacing_optimizer.py`)

### 1.1 Biorationales Steigungs- & Fahrzeitmodell
* **Vollständige physikalische Widerstandsgleichung:**
  * Rollwiderstand $F_{\text{roll}} = C_{rr} \cdot m_{\text{sys}} \cdot g \cdot \cos(\alpha)$
  * Steigungswiderstand $F_{\text{climb}} = m_{\text{sys}} \cdot g \cdot \sin(\alpha)$
  * Aerodynamischer Luftwiderstand $F_{\text{aero}} = \frac{1}{2} \cdot \rho(h) \cdot C_d A \cdot v^2$ (mit barometrischer Höhenanpassung der Luftdichte $\rho(h)$)
  * Antriebsverlust $F_{\text{drive}} = \eta_{\text{drive}} \approx 97.5\,\%$
* **Numerischer Solver (`_solve_velocity`):**
  * Findet die reale Geschwindigkeit $v$ in m/s iterativ mittels Newton-Raphson/Bisektion für jedes Streckensegment.
  * Berücksichtigt Höchstgeschwindigkeitsbegrenzungen bei Abfahrten aus Sicherheitsgründen (z. B. $v_{\max} \approx 85\,\text{km/h}$).

### 1.2 W'-Akku (Anaerober Speicher nach Skiba / Morton)
* **Start-Kapazität:** Einstellbar von $10.000\,\text{J}$ bis $30.000\,\text{J}$ (Standard: $20.000\,\text{J}$).
* **Dynamische Entleerung:** Jede Sekunde mit Leistung $P > \text{FTP}$ entleert den W'-Tank proportional zur Überziehung ($P - \text{FTP}$).
* **Erholung:** Bei $P < \text{FTP}$ lädt sich der W'-Speicher exponentiell nach Skiba et al. wieder auf.
* **Schutzfunktion:** Fällt der W'-Stand unter 20 %, regelt der Algorithmus die Maximalleistung an Steigungen automatisch auf maximal 100 % FTP ab, um Erschöpfung/Stillstand zu verhindern.

### 1.3 Metabolischer Glykogentank & Durability-Ermüdung
* **Initialer Glykogenspeicher:** $2.000\,\text{kcal}$ endogene Muskel- und Leberglykogenspeicher.
* **Substratnutzung & Verbrennung:** Berechnet den Anteil an Kohlenhydrat- vs. Fettverbrennung in Abhängigkeit von der relativen Intensität (% FTP).
* **Höhen-Hypoxie & Höhenakklimatisation:** Kontinuierliche Reduktion der effektiven Schwellenleistung (FTP) in großen Höhenlagen ($> 1.200\,\text{m}$ über NN) infolge reduzierten Sauerstoffpartialdrucks.
* **Muskuläre Ermüdung (Durability):** Mit fortschreitender Fahrzeit sinkt die anaerobe und aerobe Leistungsfähigkeit stufenweise ab, was zu realistischen Marathon-Zielzeiten führt.

### 1.4 Ernährungsstrategie & Magen-Darm-Absorption (GI)
* **Kohlenhydratzufuhr:** Einstellbar von $20$ bis $120\,\text{g/h}$ (Standard: $90\,\text{g/h}$).
* **Exogene Zufuhr:** Berechnet die tatsächliche Netto-Energieaufnahme aus Sportnahrung ($4{,}1\,\text{kcal/g}$).
* **Physiologische Obergrenzen & Warn-Badges:**
  * $< 60\,\text{g/h}$: Reicht meist nur für moderate oder kurze Touren.
  * $60–90\,\text{g/h}$: Goldstandard für Marathon-Events (Glucose:Fructose 2:1).
  * $> 90\,\text{g/h}$: Erfordert Darmtraining (Dual-Source Fructose/Maltodextrin 1:0.8) und hohe Magenverträglichkeit; visuelle Warnung vor Dehydrierung & Elektrolytbedarf.

### 1.5 Übersetzung, Kadenz & Freilaufabschaltung
* **Berggang (kleinste Übersetzung):** Dropdown mit realen Kettenblatt-/Ritzelkombinationen (z. B. 33/34, 34/34, 34/32, 35/36 etc.).
* **Minimale Kletter-Kadenz:** Einstellbar von $60$ bis $90\,\text{rpm}$ (Standard: $75\,\text{rpm}$). Verhindert unphysiologisch niedrige Trittfrequenzen; erzwingt im Notfall eine Mindestleistung am Steilhang.
* **Abfahrtsgang (größte Übersetzung):** Dropdown (z. B. 46/10, 48/10, 50/11, 52/11, 54/11 etc.).
* **Maximale Pedalier-Kadenz (Spin-Out):** Einstellbar von $90$ bis $125\,\text{rpm}$ (Standard: $105\,\text{rpm}$). Sobald die Abfahrtsgeschwindigkeit die Pedalierbarkeit übersteigt, schaltet das Pacing auf $0\,\text{W}$ (Freilauf/Rollen lassen).

### 1.6 Pacing-Kurven-Modi
* **📈 Dynamisch (kontinuierlich wattgesteuert):** Glatte, physikalisch stetige Leistungsanpassung. Im Flachen diszipliniertes GA1/Z2, an Anstiegen kraftsparend dosiertes Pacing, in Abfahrten Entlastung.
* **📊 Klassisch Stufe:** Fixe $130\,\text{W}$ Grundlast im Flachen und ab leichten Gefällen ($-1{,}5\,\%$), orientiert an traditionellen Intervallvorgaben.

### 1.7 Streckendaten & Automatische Geländehöhen-API
* **GPX-Parser:** Liest GPX-Dateien hochpräzise aus (Wegpunkte, Höhen, Distanzen, Glättung von GPS-Rauschen).
* **Geländehöhen-Enrichment (`elevation_enrichment.py`):** Fehlen in der GPX-Datei Höhendaten, werden diese automatisch über die **Open-Meteo Elevation API** (SRTM $90\,\text{m}$ Auflösung) mit Fallback auf **Open-Elevation** abgerufen und in `elevation_cache.json` persistent zwischengespeichert.

---

## 2. Benutzeroberfläche & Bedienung (`power_planner_flet.py`)

### 2.1 Dreiteilige Tab-Navigation
1. **Setup & Route (Tab 1):**
   * Einheitliche KPI-Übersichtsleiste (Dauer, Systemgewicht, Rel. FTP, ø Leistung, NP, Gesamtanstieg).
   * Fahrereinstellungen (Start-FTP, W'-Akku, Fahrergewicht, Fahrradgewicht).
   * Ernährungsstrategie & Intensitätsfaktor (Carbs g/h, Target Factor) mit Coach-Badges.
   * Übersetzung & Trittfrequenz (Berggang, Abfahrtsgang, Min-/Max-Kadenz, Pacing-Modell).
   * Streckenprofil & GPX-Import (Dateiauswahl, GPX-XML Paste Dialog, lokales Projekt-Dropdown).
2. **Analyse & Charts (Tab 2):**
   * Einheitliche KPI-Übersichtsleiste.
   * Strecken-Vorschau (2D-Streckenkarte via Matplotlib).
   * Höhenprofil & Ziel-Leistungs-Chart (kombinierter Plot aus Topografie und Wattvorgabe).
   * Energiespeicher-Chart (W'-Akku in % und Glykogentank in % über die Gesamtdistanz).
   * Berechnete Workout-Segmente nach Coggan-Zonen (Z1 bis Z7 mit Farbcodierung und exakter Dauer).
   * **Sportnahrungs-Einkaufsliste:** Aufgeschlüsselte Bedarfsplanung (Iso-Getränke-Portionen, Standard-Gels à 30g KH, Sportriegel / Hydro-Gels à 40g KH).
3. **Karoo-Sync & Exporte (Tab 3):**
   * Einheitliche KPI-Übersichtsleiste.
   * **Schneller Live-Scan via Kamera (OpenCV & ZXing-C++):** Erkennt den Karoo-QR-Code in Echtzeit und überträgt die Route sofort.
   * **QR-Bilddatei-Auswahl:** Fallback für Geräte ohne direkte Kamerafreigabe.
   * **Manuelle Eingabe:** Karoo WLAN-IP und 6-stelliger Kopplungscode oder vollständige Upload-URL.
   * **Hammerhead Cloud GPX-Sync:** Automatische Übertragung der GPX-Route nach erfolgreichem Karoo-Transfer inklusive Browser-Login.
   * **Lokale Exporte:** Karoo Power-Track JSON (`.ptj` / `_power_track.json`), Zwift Workout (`.zwo`), Garmin Workout (`.fit`).
   * **Übertragungs-Protokoll & Status:** Scrollbare Live-Log-Konsole.
   * **Entwickler-ADB-Push:** Direkte USB-Übertragung per `adb push` auf `/sdcard/PowerTracks/`.

### 2.2 Einheitliche KPI-Übersichtsleiste (auf allen 3 Tabs)
* **Sechs standardisierte Kacheln mit fester Maximalhöhe & klaren Bezeichnern:**
  1. `Dauer (Prognose)` (z. B. `07:42:15`)
  2. `Systemgewicht` (z. B. `84.0 kg`)
  3. `Rel. FTP` (z. B. `4.08 W/kg`)
  4. `ø Leistung` (z. B. `212 W`)
  5. `Normalisierte Leistung (NP)` (z. B. `238 W`)
  6. `Gesamtanstieg` (z. B. `5.180 Hm`)
* Bleibt beim Umschalten zwischen allen Tabs exakt identisch positioniert und formatiert.

### 2.3 Persistente Speicherung der Einstellungen
* Speichert alle Slider-Werte, Dropdown-Auswahlen und Zugangsdaten automatisch in `power_planner_settings.json` im Plattform-Datenverzeichnis.
* Übersteht App-Neustarts auf macOS, iOS, Android und im Web.
* Mit dem **Reset-Button** (`RESTART_ALT`) können jederzeit die Standardwerte wiederhergestellt werden.

### 2.4 Reaktives Slider-Design (Zero Lag)
* `on_change`: Aktualisiert sofort Live-Badges, Textwerte und Farbanzeigen (60 FPS flüssig).
* `on_change_end`: Löst die rechenintensive Physiksimulation und Chart-Generierung erst beim Loslassen des Sliders aus.

### 2.5 Integrierte Hilfe-Funktionen (UI)
* **Globaler Hilfe-Button (`HELP_OUTLINE`) in der App-Bar:**
  * Öffnet ein modales Fenster mit einer vollständigen Übersicht aller Funktionen, physikalischen Modelle, Zonen und Transferoptionen.
* **Kontextuelle Hilfe-Icons (`INFO_OUTLINE`) an jedem Eingabefeld:**
  * An jedem Slider und Dropdown befindet sich ein Info-Icon mit Tooltip und Klick-Dialog für mobile Touchscreens.

---

## 3. Schnittstellen & Synchronisation

### 3.1 Hammerhead Karoo Live-Transfer (HTTP)
* **Format:** Power-Track JSON (Spezifikation siehe `specification_power_track.md`).
* **Inhalt:** Jeder Streckenpunkt enthält GPS-Koordinaten, kumulierte Distanz, Ziel-Watt, erwarteten W'-Stand, Coggan-Zonenfarbe und ortsgebundene Benachrichtigungen (`PACING`, `NUTRITION`, `CAUTION`, `STATION`).
* **Endpunkt:** `POST http://<karoo-ip>:8080/upload?token=<CODE>` mit Header `X-Filename: <name>_power_track.json`.

### 3.2 Hammerhead Cloud GPX-Routensync (`hammerhead_client.py` & `gpx_exporter.py`)
* **GPX-Konvertierung:** Erzeugt aus den Pacing-Track-Punkten eine standardkonforme GPX-1.1-Datei mit Routen-Metadaten und Wegpunkten (`<wpt>`) für Verpflegungs- und Pacing-Hinweise.
* **Upload-Endpunkt:** `POST https://dashboard.hammerhead.io/v1/users/{user_id}/routes/import/file`.
* **Ausführungsreihenfolge:** Wird bei aktiviertem Schalter automatisch **unmittelbar nach** dem erfolgreichen Karoo-Transfer angestoßen.

### 3.3 Offizieller SRAM OAuth 2.0 PKCE-Browser-Login
* **Keine Passworteingabe in der App oder auf localhost:**
  * Die Authentifizierung erfolgt direkt auf der offiziellen Anmeldeseite von SRAM / Hammerhead (`https://sramid-auth.sram.com/authorize?...`).
* **Sicherer PKCE-Handshake:**
  * Client generiert `code_verifier` und `code_challenge` ($S256$).
  * Abfangen des Redirects auf `https://dashboard.hammerhead.io/accounts/callback/sram?code=...` in `WKNavigationDelegate` (macOS/iOS) bzw. `WebViewClient` (Android) **bevor** das Dashboard die Seite lädt.
  * Tauscht den Code serverseitig bei `POST https://sramid-auth.sram.com/oauth/token` und anschließend bei `POST https://dashboard.hammerhead.io/v1/auth/sram/mobile/token` gegen ein Hammerhead Cloud Bearer JWT ein.
  * Automatischer Token-Refresh bei Ablauf des Access-Tokens.

---

## 4. Multi-Plattform-Unterstützung

| Plattform | Technologie | Native Besonderheiten |
| :--- | :--- | :--- |
| **macOS Desktop** | Python 3.14 + Flet (Desktop) | Natives `WKWebView`-Fenster (`scripts/hh_webview_macos.swift`), OpenCV-Kamerazugriff |
| **iOS / iPadOS** | Flutter + Serious Python 4.7 (`Runner.app`) | Native Swift-Bridge (`AppDelegate.swift`) für SRAM-Login, SPM Resource Staging |
| **Android** | Flutter + Serious Python (`MainActivity.kt`) | Native Kotlin-Bridge mit `WebViewClient`, File-Trigger-Watcher |
| **Web Browser** | Flet Web (`--web`, Pyodide/HTML5) | Paste-Dialog für GPX-Code, Datei-Download-Fallback |

---

## 5. Entwickler-Regeln (Regression Prevention Checklist)

Bevor Änderungen eingecheckt werden, muss sichergestellt sein:
1. **Keine Features entfernen:** Slider, Badges, Badges-Reihenfolge, Einkaufsliste, Charts und Tabs bleiben vollständig erhalten.
2. **KPI-Karten-Konsistenz:** Die KPI-Leiste auf allen drei Tabs muss synchron bleiben und die gleichen sechs Felder enthalten.
3. **Persistenz:** Neue Parameter müssen in `DEFAULT_SETTINGS`, `save_settings` und `apply_settings` registriert werden.
4. **Testabdeckung:** Alle 45 Tests in `tests/` müssen fehlerfrei durchlaufen (`pytest tests/ -v`).
5. **iOS-Sync:** Nach Änderungen an Python-Dateien muss `./scripts/sync_ios_app.sh` ausgeführt werden.
