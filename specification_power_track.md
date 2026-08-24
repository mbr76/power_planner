# Specification: Power-Planner Course Pacing Profile (v1.0)

Dieses Dokument spezifiziert das JSON-Datenformat für den Datenaustausch zwischen dem **Power-Planner** (Python-Backend) und der **Hammerhead Karoo Extension** (Android-App). Das Format kombiniert geografische Track-Informationen mit physikalischen Leistungsdaten, Zonen-Farbcodierungen und ortsgebundenen Benachrichtigungen.

## 1. Dateistruktur (Übersicht)

Die Datei ist als valides JSON-Objekt aufgebaut und gliedert sich in ein globales Metadaten-Objekt (`meta`) sowie ein fortlaufendes Array aus Streckenpunkten (`track`).

```json
{
  "meta": {
    "version": "1.0",
    "route_name": "Ötztaler Radmarathon - Race Strategy",
    "generated_at": "2026-08-24T09:12:00Z",
    "athlete_ftp": 310,
    "system_weight_kg": 80.0,
    "target_carb_intake_gh": 90
  },
  "track": [
    {
      "index": 0,
      "lat": 47.25142,
      "lon": 11.01241,
      "ele": 1377.2,
      "dist_km": 0.00,
      "target_power": 210,
      "expected_w_prime_pct": 100.0,
      "zone_color": "#E5E7EB",
      "notification": null
    },
    {
      "index": 1240,
      "lat": 47.20145,
      "lon": 10.98412,
      "ele": 1540.8,
      "dist_km": 31.52,
      "target_power": 325,
      "expected_w_prime_pct": 98.4,
      "zone_color": "#FFEDD5",
      "notification": {
        "type": "NUTRITION", 
        "trigger_radius_m": 50,
        "title": "Verpflegung",
        "message": "Jetzt 1 Gel (30g KH) nehmen!",
        "audio_alert": true
      }
    }
  ]
}
```

---

## 2. Daten-Dictionary (Feldbeschreibung)

### 2.1 Das `meta` Objekt
Enthält globale Rahmenparameter des berechneten Szenarios, die beim Laden der Datei auf dem Hammerhead Karoo für Übersichtsseiten oder zur Verifizierung genutzt werden können.

| Feld | Datentyp | Beschreibung | Beispiel |
| :--- | :--- | :--- | :--- |
| `version` | string | Versionsnummer der Spezifikation für Abwärtskompatibilität. | `"1.0"` |
| `route_name` | string | Name der Route, der im Menü des Karoo angezeigt wird. | `"Ötztaler RM"` |
| `generated_at` | string | Zeitstempel der Erstellung im ISO-8601 Format (UTC). | `"2026-08-24T09:12:00Z"` |
| `athlete_ftp` | integer | Die der Berechnung zugrundeliegende FTP (Watt). | `310` |
| `system_weight_kg` | float | Gesamtgewicht aus Fahrer, Bekleidung und Fahrrad (kg). | `80.0` |
| `target_carb_intake_gh` | integer | Angestrebte Kohlenhydratzufuhr pro Stunde (Gramm). | `90` |

---

### 2.2 Das `track` Array
Eine hochauflösende, chronologische Liste aller Wegpunkte entlang der Route. Die Android-Extension nutzt diese Daten für die *Nearest-Neighbor-Suche* via GPS, um den aktuellen Leistungs-Sollwert zu ermitteln.

| Feld | Datentyp | Beschreibung | Beispiel |
| :--- | :--- | :--- | :--- |
| `index` | integer | Eindeutige, fortlaufende ID des Datenpunktes ab 0. | `1240` |
| `lat` | float | Breitengrad im WGS84-Format (Dezimalgrad). | `47.25142` |
| `lon` | float | Längengrad im WGS84-Format (Dezimalgrad). | `11.01241` |
| `ele` | float | Höhe über dem Meeresspiegel in Metern (NN). | `1377.2` |
| `dist_km` | float | Kumulierte Distanz ab dem Startpunkt in Kilometern. | `31.52` |
| `target_power` | integer | Physikbasierte Soll-Leistung für diesen Punkt (Watt). | `325` |
| `expected_w_prime_pct`| float | Prognostizierter anaerober Ladestand (0.0 bis 100.0 %). | `98.4` |
| `zone_color` | string | HEX-Farbcode der aktuellen Coggan-Intensitätszone. | `"#FFEDD5"` |
| `notification` | object/null | Enthält ein Info-Objekt bei Ereignissen, andernfalls `null`. | *(siehe 2.3)* |

---

### 2.3 Das `notification` Objekt (Optional)
Wird vom Power-Planner an spezifischen Koordinaten injiziert (z.B. zeitbasiert alle 20 Minuten berechnet oder distanzbasiert 100 Meter *vor* echten Strecken-Features), um visuelle und akustische Alarme auf dem Karoo-Display auszulösen.

| Feld | Datentyp | Beschreibung | Optionen / Beispiel |
| :--- | :--- | :--- | :--- |
| `type` | string | Kategorie des Hinweises zur Steuerung von Icons/Farben im UI. | `"NUTRITION"`, `"STATION"`, `"PACING"`, `"CAUTION"` |
| `trigger_radius_m` | integer | GPS-Toleranzradius in Metern, in dem der Alarm auslöst. | `50` |
| `title` | string | Kurze, prägnante Überschrift für das Android-Overlay. | `"Verpflegung"` |
| `message` | string | Detaillierter Instruktionstext für den Athleten. | `"Jetzt 1 Gel nehmen!"` |
| `audio_alert` | boolean | Steuert, ob das Karoo-Gerät einen Signalton abgibt. | `true` / `false` |

#### Zulässige Enums für `type`:
*   `"NUTRITION"`: Erinnerungen an regelmäßiges Essen und Trinken (z.B. alle 20 Minuten).
*   `"STATION"`: Geografische Labestationen und offizielle Kontrollpunkte des Veranstalters.
*   `"PACING"`: Ankündigungen gravierender Streckenänderungen (z.B. *"Achtung, Kühtai-Rampe beginnt!"*).
*   `"CAUTION"`: Reine Sicherheits- und Gefahrenhinweise (z.B. *"Gefährliche Kurven/Belag in Abfahrt"*).

---

## 3. Implementierungshinweise (Best Practices)

### 3.1 Für das Python-Backend (Power-Planner)
*   **Glättung:** Vor dem Schreiben des JSON-Track-Arrays sollten Ausreißer im GPS-Signal entfernt werden, um "Zuckungen" der Ziel-Leistung auf dem Gerät zu verhindern.
*   **Vorwarnung bei Stations:** Alarme für physische Labestationen (`"type": "STATION"`) sollten vom Algorithmus mathematisch ca. **100 bis 200 Meter vor** der eigentlichen Koordinate in den Track injiziert werden, damit der Fahrer rechtzeitig reagieren kann.

### 3.2 Für die Hammerhead Karoo Extension (Android)
*   **Ressourcenschonung:** Da das JSON mehrere tausend Punkte umfassen kann, sollte beim Laden der Datei im Android-Service ein effizienter Suchbaum (z.B. ein *Spatial Index* oder ein vereinfachter *K-D-Tree*) aufgebaut werden, um die Core-CPU bei der permanenten Standortermittlung (1Hz-Taktung) zu entlasten.
*   **Einmalige Notification-Trigger:** Sobald eine Koordinate mit einem `notification`-Inhalt getriggert wurde, muss die Extension diesen spezifischen Index temporär sperren ("de-bouncen"), damit der Alarm bei GPS-Ungenauigkeiten (Vor- und Zurückspringen am Berg) nicht mehrfach hintereinander aufploppt.
