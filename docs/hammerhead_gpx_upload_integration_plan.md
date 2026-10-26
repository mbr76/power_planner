# Implementation Plan: Hammerhead Cloud Sync in `pacing_optimizer` (Flet App)

## 1. Übersicht & Ziel
In der Flet-basierten Planner-App (`pacing_optimizer` für Android, iOS und Desktop) soll ein automatisierter **„An Karoo senden“**-Workflow integriert werden.
Da der Karoo 2 und Karoo 3 keine lokalen GPX-Dateien im Dateisystem importieren können, erfolgt ein dualer Export:
1. **Power Track (`.ptj`):** Übertragung per lokalem WLAN/QR-Code an die Karoo-Extension (für Pacing, Zonen, Glykogen & Cue-Alarme).
2. **Native Route (`.gpx`):** Automatischer Push per HTTPS REST an die Hammerhead Cloud (`dashboard.hammerhead.io`), wodurch die Route automatisch auf den Karoo synchronisiert wird (für native Karte, Turn-by-Turn und *Climber*).

---

## 2. Hammerhead REST API Spezifikation

### 2.1 Authentifizierung (Login)
* **Endpoint:** `POST https://dashboard.hammerhead.io/v1/auth/login`
* **Headers:** `Content-Type: application/json`
* **Request Body:**
  ```json
  {
    "email": "user@example.com",
    "password": "secretpassword"
  }
  ```
* **Response (200 OK):**
  ```json
  {
    "token": "eyJhbGciOiJIUzI1NiIsIn...",
    "user": {
      "id": "usr_abc123456",
      "email": "user@example.com",
      "name": "Max Mustermann"
    }
  }
  ```

### 2.2 GPX-Route hochladen (Import)
* **Endpoint:** `POST https://dashboard.hammerhead.io/v1/users/{user_id}/routes`
* **Headers:**
  * `Authorization: Bearer <token>`
* **Payload (Multipart / Form-Data):**
  * `file`: Dateiname z. B. `oetztaler.gpx`, MIME-Type `application/gpx+xml`, Binärinhalt der GPX-Datei.
* **Response (200 / 201 Created):**
  ```json
  {
    "id": "route_xyz987",
    "name": "Ötztaler Radmarathon - Race Strategy",
    "distance": 227000,
    "elevation": 5500
  }
  ```

---

## 3. Architektur & Python-Module in `pacing_optimizer`

### 3.1 Service-Klasse: `hammerhead_client.py`
```python
import requests
from typing import Optional, Tuple

class HammerheadClient:
    BASE_URL = "https://dashboard.hammerhead.io/v1"

    def __init__(self, token: Optional[str] = None, user_id: Optional[str] = None):
        self.token = token
        self.user_id = user_id

    def login(self, email: str, password: str) -> Tuple[str, str]:
        """Authentifiziert gegen Hammerhead und liefert (token, user_id)."""
        url = f"{self.BASE_URL}/auth/login"
        resp = requests.post(url, json={"email": email, "password": password}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self.token = data["token"]
        self.user_id = data["user"]["id"]
        return self.token, self.user_id

    def upload_gpx(self, gpx_content: str, route_name: str) -> dict:
        """Lädt einen GPX-XML-String als neue Route in den Hammerhead-Account."""
        if not self.token or not self.user_id:
            raise ValueError("Hammerhead client is not authenticated.")

        url = f"{self.BASE_URL}/users/{self.user_id}/routes"
        headers = {"Authorization": f"Bearer {self.token}"}
        filename = f"{route_name.replace(' ', '_')}.gpx"
        files = {
            "file": (filename, gpx_content.encode("utf-8"), "application/gpx+xml")
        }
        resp = requests.post(url, headers=headers, files=files, timeout=30)
        resp.raise_for_status()
        return resp.json()
```

### 3.2 GPX-Konverter: `gpx_exporter.py`
Erzeugt aus dem internen Streckenmodell des Pacing-Optimizers ein sauberes GPX 1.1:
```python
import xml.etree.ElementTree as ET
from xml.dom import minidom

def generate_gpx_from_pacing_track(meta: dict, trackpoints: list) -> str:
    gpx = ET.Element("gpx", {
        "version": "1.1",
        "creator": "Pacing Optimizer",
        "xmlns": "http://www.topografix.com/GPX/1/1",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd"
    })

    # Metadata
    metadata_el = ET.SubElement(gpx, "metadata")
    name_el = ET.SubElement(metadata_el, "name")
    name_el.text = meta.get("route_name", "Pacing Route")

    # POIs / Waypoints from notifications
    for pt in trackpoints:
        notif = pt.get("notification")
        if notif:
            wpt = ET.SubElement(gpx, "wpt", {"lat": str(pt["lat"]), "lon": str(pt["lon"])})
            if "ele" in pt:
                ele_el = ET.SubElement(wpt, "ele")
                ele_el.text = str(pt["ele"])
            w_name = ET.SubElement(wpt, "name")
            w_name.text = notif.get("title", "Notice")
            w_desc = ET.SubElement(wpt, "desc")
            w_desc.text = notif.get("message", "")
            w_type = ET.SubElement(wpt, "type")
            w_type.text = notif.get("type", "GENERIC")

    # Track
    trk = ET.SubElement(gpx, "trk")
    trk_name = ET.SubElement(trk, "name")
    trk_name.text = meta.get("route_name", "Pacing Route")
    trkseg = ET.SubElement(trk, "trkseg")

    for pt in trackpoints:
        trkpt = ET.SubElement(trkseg, "trkpt", {"lat": str(pt["lat"]), "lon": str(pt["lon"])})
        if "ele" in pt:
            ele_el = ET.SubElement(trkpt, "ele")
            ele_el.text = str(pt["ele"])

    xml_str = ET.tostring(gpx, encoding="utf-8")
    return minidom.parseString(xml_str).toprettyxml(indent="  ")
```

---

## 4. Flet-Integration (UI & Persistenz)

### 4.1 Token-Speicherung mit `client_storage`
```python
# Beim Starten der Flet-App:
saved_token = page.client_storage.get("hh_token")
saved_user_id = page.client_storage.get("hh_user_id")
hh_client = HammerheadClient(token=saved_token, user_id=saved_user_id)

# Beim erfolgreichen Login:
page.client_storage.set("hh_token", token)
page.client_storage.set("hh_user_id", user_id)

# Beim Abmelden:
page.client_storage.remove("hh_token")
page.client_storage.remove("hh_user_id")
```

### 4.2 Der kombinierte Export-Button
```python
def on_send_to_karoo_clicked(e):
    # 1. GPX direkt an Hammerhead Cloud pushen (sofern eingeloggt)
    if hh_client.token:
        try:
            gpx_data = generate_gpx_from_pacing_track(plan.meta, plan.track)
            hh_client.upload_gpx(gpx_data, plan.meta["route_name"])
            show_snackbar("Route erfolgreich an Hammerhead gesendet! Synchronisiert sich automatisch.")
        except Exception as err:
            show_snackbar(f"Fehler beim Hammerhead-Upload: {err}")

    # 2. Power-Track (.ptj) via lokalen Karoo-Server senden oder QR-Code Dialog öffnen
    open_karoo_qr_transmission_dialog(plan.to_json())
```

---

## 5. Anweisung zur Übergabe an den Antigravity-Agenten in `pacing_optimizer`
Wenn du im Projekt `pacing_optimizer` bist, kannst du dem Agenten einfach folgende Anweisung geben:
> *„Bitte lies das Dokument `hammerhead_integration_plan.md` und baue den Hammerhead-Cloud-Sync (Login-Verwaltung, GPX-Generierung und Upload) in unsere Flet-App ein.“*
