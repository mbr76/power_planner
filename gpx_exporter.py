"""
GPX 1.1 Exporter for Power-Planner.
Converts the internal Pacing Track structure (metadata, trackpoints, and nutrition/pacing notifications)
into a standard-compliant GPX 1.1 XML string suitable for Hammerhead Dashboard import.
"""

import xml.etree.ElementTree as ET


def generate_gpx_from_pacing_track(meta: dict, trackpoints: list) -> str:
    """
    Erzeugt aus dem internen Streckenmodell des Pacing-Optimizers (meta + track)
    einen validen GPX 1.1 XML-String inkl. Höhenprofil und Waypoints für Notifications.
    """
    gpx = ET.Element("gpx", {
        "version": "1.1",
        "creator": "Power-Planner Pacing Optimizer",
        "xmlns": "http://www.topografix.com/GPX/1/1",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd",
    })

    route_name = (meta or {}).get("route_name") or "Pacing Route"

    # Metadata
    metadata_el = ET.SubElement(gpx, "metadata")
    name_el = ET.SubElement(metadata_el, "name")
    name_el.text = str(route_name)

    # POIs / Waypoints from notifications
    for pt in trackpoints:
        notif = pt.get("notification")
        if notif and isinstance(notif, dict):
            wpt = ET.SubElement(gpx, "wpt", {
                "lat": str(pt.get("lat", 0.0)),
                "lon": str(pt.get("lon", 0.0)),
            })
            if "ele" in pt and pt["ele"] is not None:
                ele_el = ET.SubElement(wpt, "ele")
                ele_el.text = str(pt["ele"])
            w_name = ET.SubElement(wpt, "name")
            w_name.text = str(notif.get("title", "Notice"))
            w_desc = ET.SubElement(wpt, "desc")
            w_desc.text = str(notif.get("message", ""))
            w_type = ET.SubElement(wpt, "type")
            w_type.text = str(notif.get("type", "GENERIC"))

    # Track
    trk = ET.SubElement(gpx, "trk")
    trk_name = ET.SubElement(trk, "name")
    trk_name.text = str(route_name)
    trkseg = ET.SubElement(trk, "trkseg")

    for pt in trackpoints:
        trkpt = ET.SubElement(trkseg, "trkpt", {
            "lat": str(pt.get("lat", 0.0)),
            "lon": str(pt.get("lon", 0.0)),
        })
        if "ele" in pt and pt["ele"] is not None:
            ele_el = ET.SubElement(trkpt, "ele")
            ele_el.text = str(pt["ele"])

    if hasattr(ET, "indent"):
        ET.indent(gpx, space="  ")

    xml_body = ET.tostring(gpx, encoding="unicode")
    return f'<?xml version="1.0" encoding="utf-8"?>\n{xml_body}\n'
