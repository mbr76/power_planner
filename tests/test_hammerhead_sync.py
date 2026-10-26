"""
Unit & Integration Tests for Hammerhead Cloud GPX Route Sync,
Browser Authentication Flow, and Post-Karoo-Transfer Execution Order.
"""

import asyncio
import base64
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

from gpx_exporter import generate_gpx_from_pacing_track
from hammerhead_client import (
    BrowserAuthSession,
    HammerheadClient,
    build_sram_authorize_url,
    extract_user_id_from_jwt,
    generate_pkce_pair,
)


def _make_jwt(payload: dict) -> str:
    header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header_b64}.{payload_b64}.signature123"


def test_extract_user_id_from_jwt():
    token = _make_jwt({"sub": "hh_user_9876", "exp": 9999999999})
    assert extract_user_id_from_jwt(token) == "hh_user_9876"
    assert extract_user_id_from_jwt(f"Bearer {token}") == "hh_user_9876"
    assert extract_user_id_from_jwt("invalid.token") is None
    assert extract_user_id_from_jwt("") is None


def test_generate_gpx_from_pacing_track():
    meta = {"route_name": "Ötztaler Radmarathon", "total_distance_m": 227000}
    track = [
        {
            "lat": 46.968,
            "lon": 11.009,
            "ele": 1377.0,
            "target_power": 240,
            "notification": {
                "type": "PACING",
                "title": "Anstieg Kühtai",
                "message": "Pacing: 265W für 18km",
            },
        },
        {
            "lat": 47.214,
            "lon": 11.020,
            "ele": 2017.5,
            "target_power": 265,
            "notification": {
                "type": "CARBS",
                "title": "Verpflegung",
                "message": "90g Carbs / 1 Gel",
            },
        },
        {
            "lat": 47.250,
            "lon": 11.100,
            "ele": 800.0,
            "target_power": 150,
        },
    ]

    gpx_xml = generate_gpx_from_pacing_track(meta, track)
    assert gpx_xml.startswith('<?xml version="1.0" encoding="utf-8"?>')
    root = ET.fromstring(gpx_xml)
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}

    name_el = root.find("gpx:metadata/gpx:name", ns)
    assert name_el is not None
    assert name_el.text == "Ötztaler Radmarathon"

    wpts = root.findall("gpx:wpt", ns)
    assert len(wpts) == 2
    assert wpts[0].find("gpx:name", ns).text == "Anstieg Kühtai"
    assert wpts[0].find("gpx:desc", ns).text == "Pacing: 265W für 18km"
    assert wpts[1].find("gpx:type", ns).text == "CARBS"

    trkpts = root.findall("gpx:trk/gpx:trkseg/gpx:trkpt", ns)
    assert len(trkpts) == 3
    assert trkpts[0].attrib["lat"] == "46.968"
    assert trkpts[0].find("gpx:ele", ns).text == "1377.0"


def test_hammerhead_client_set_token_and_upload():
    jwt_tok = _make_jwt({"sub": "user_42", "email": "rider@sram.com"})
    client = HammerheadClient()
    assert not client.is_authenticated

    tok, uid = client.set_token(jwt_tok)
    assert tok == jwt_tok
    assert uid == "user_42"
    assert client.is_authenticated

    mock_upload_resp = MagicMock()
    mock_upload_resp.status_code = 201
    mock_upload_resp.json.return_value = {"id": "route_999", "name": "TestRoute"}

    with patch("hammerhead_client.requests.post", return_value=mock_upload_resp) as mock_post:
        res = client.upload_gpx("<gpx></gpx>", "MyRoute.GPX")
        assert res["id"] == "route_999"
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == f"Bearer {jwt_tok}"
        uploaded_file_tuple = kwargs["files"]["file"]
        # Ensure lowercase .gpx extension
        assert uploaded_file_tuple[0] == "MyRoute.gpx"
        assert uploaded_file_tuple[2] == "application/gpx+xml"


def test_pkce_and_sram_authorize_url():
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 40
    assert len(challenge) >= 40
    assert "=" not in challenge

    auth_url = build_sram_authorize_url(challenge)
    assert auth_url.startswith("https://sramid-auth.sram.com/authorize?")
    parsed = urllib.parse.urlparse(auth_url)
    qs = urllib.parse.parse_qs(parsed.query)
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge"] == [challenge]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["client_id"] == ["MFhsYcUUMGGBPaA4KpGKxUuzyqOY9ReM"]
    assert qs["redirect_uri"] == ["https://dashboard.hammerhead.io/accounts/callback/sram"]


def test_exchange_sram_code_single_and_multi_account():
    sram_jwt = _make_jwt({"sub": "sram_id_1", "email": "rider@sram.com"})
    hh_jwt = _make_jwt({"sub": "hh_uid_555"})

    sram_resp = MagicMock()
    sram_resp.status_code = 200
    sram_resp.json.return_value = {
        "access_token": sram_jwt,
        "refresh_token": "sram_ref_1",
        "id_token": sram_jwt,
    }

    hh_resp = MagicMock()
    hh_resp.status_code = 200
    hh_resp.json.return_value = {
        "access_token": hh_jwt,
        "refresh_token": "hh_ref_99",
    }

    client = HammerheadClient()
    with patch("hammerhead_client.requests.post", side_effect=[sram_resp, hh_resp]) as mock_post:
        tok, uid, email = client.exchange_sram_code("auth_code_xyz", "verifier_abc")
        assert tok == hh_jwt
        assert uid == "hh_uid_555"
        assert email == "rider@sram.com"
        assert client.refresh_token == "hh_ref_99"
        assert mock_post.call_count == 2
        # Verify SRAM token call headers & payload
        sram_call = mock_post.call_args_list[0]
        assert sram_call[0][0] == "https://sramid-auth.sram.com/oauth/token"
        assert sram_call[1]["data"]["code"] == "auth_code_xyz"
        assert sram_call[1]["data"]["code_verifier"] == "verifier_abc"


def test_browser_auth_session_redirect_and_callback_flow():
    jwt_tok = _make_jwt({"sub": "browser_user_77", "email": "cyclist@sram.com"})
    results = []

    def on_success(tok, uid, ident, refresh_tok=None):
        results.append((tok, uid, ident, refresh_tok))

    session = BrowserAuthSession(on_success=on_success)
    login_url = session.start()
    try:
        assert login_url.startswith("http://127.0.0.1:")
        assert login_url.endswith("/login")

        # 1. GET /login renders redirect instructions to official Hammerhead/SRAM site
        # and NEVER asks for password on localhost
        status, html_body = session.process_request("GET", "/login")
        assert status == 200
        assert "https://sramid-auth.sram.com/authorize" in html_body
        assert 'type="password"' not in html_body

        # 2. GET /callback?code=... exchanges SRAM authorization code via PKCE
        with patch.object(
            HammerheadClient,
            "exchange_sram_code",
            return_value=(jwt_tok, "browser_user_77", "cyclist@sram.com"),
        ) as mock_exchange:
            qs = urllib.parse.urlencode({"code": "sram_oauth_code_123"})
            status, success_body = session.process_request("GET", f"/callback?{qs}")
            assert status == 200
            assert "Hammerhead Cloud verbunden!" in success_body
            mock_exchange.assert_called_once_with("sram_oauth_code_123", session.code_verifier)

        # Wait briefly for async completion thread
        for _ in range(20):
            if results:
                break
            time.sleep(0.05)

        assert len(results) == 1
        assert results[0][:3] == (jwt_tok, "browser_user_77", "cyclist@sram.com")
    finally:
        session.stop()


def test_mobile_webview_trigger_for_ios_and_android(tmp_path, monkeypatch):
    monkeypatch.setenv("FLET_PLATFORM", "android")
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))

    session = BrowserAuthSession(on_success=lambda *_: None, clear_session=True)
    try:
        launched = session.launch_native_hammerhead_browser()
        assert launched is True
        trig_file = tmp_path / "hh_webview_trigger.json"
        assert trig_file.exists()
        payload = json.loads(trig_file.read_text(encoding="utf-8"))
        assert payload["target_url"].startswith("https://sramid-auth.sram.com/authorize?")
        assert "code_challenge_method=S256" in payload["target_url"]
        assert payload["callback_url"].endswith("/callback")
        assert payload["clear_session"] is True
    finally:
        session.stop()


def test_karoo_transfer_then_hammerhead_gpx_upload_order():
    """
    Prüft, dass die GPX-Routendatei erst NACH einem erfolgreichen Transfer des PTJ
    an den Karoo an Hammerhead Cloud übermittelt wird (und bei Karoo-Fehler unterbleibt).
    """
    async def run():
        import power_planner_flet as app

        jwt_tok = _make_jwt({"sub": "hh_sync_user_1"})
        saved = {
            "hh_token": jwt_tok,
            "hh_user_id": "hh_sync_user_1",
            "hh_email": "pro@rider.io",
            "hh_auto_sync": True,
            "karoo_ip": "192.168.1.50",
            "karoo_token": "ABCDEF",
        }
        with open(app.get_settings_file_path(), "w", encoding="utf-8") as f:
            json.dump(saved, f)

        page = MagicMock()
        page.theme_mode = app.ft.ThemeMode.DARK
        page.window = MagicMock()
        page.overlay = []
        page.controls = []

        def add_mock(*controls):
            page.controls.extend(controls)

        page.add = MagicMock(side_effect=add_mock)
        page.update = MagicMock()
        page.show_dialog = MagicMock()
        page.pop_dialog = MagicMock()

        await app.main(page)

        # Switch to Tab 3 (Karoo-Sync)
        nav_event = MagicMock()
        nav_event.control.selected_index = 2
        page.navigation_bar.on_change(nav_event)

        tab_sync_col = page.controls[0].content.content
        # Manual entry card is at index 4 (KPI=0, Divider=1, Header=2, QR-Card=3, Manual-Card=4, HH-Card=5)
        manual_card_col = tab_sync_col.controls[4].content.content
        send_code_btn = manual_card_col.controls[2]

        call_order = []

        def fake_karoo_push(url, json_str, target_filename, log_cb=None, max_retries=2, timeout=6):
            call_order.append(("karoo_ptj_push", url, target_filename))
            return True, "HTTP 200 OK", []

        def fake_hh_upload(self, gpx_content, route_name, timeout=20):
            call_order.append(("hammerhead_gpx_upload", route_name, gpx_content[:38]))
            return {"id": "route_123"}

        with patch("power_planner_flet.push_to_karoo_http", side_effect=fake_karoo_push), \
             patch.object(HammerheadClient, "upload_gpx", autospec=True, side_effect=fake_hh_upload):
            await send_code_btn.on_click(None)

        # 1. Verify strict sequential order: Karoo PTJ transfer FIRST, Hammerhead GPX upload SECOND
        assert len(call_order) == 2
        assert call_order[0][0] == "karoo_ptj_push"
        assert call_order[1][0] == "hammerhead_gpx_upload"
        assert "<?xml" in call_order[1][2]

        # 2. Verify that if Karoo transfer fails, Hammerhead upload is NOT triggered
        call_order.clear()

        def fake_karoo_fail(url, json_str, target_filename, log_cb=None, max_retries=2, timeout=6):
            call_order.append(("karoo_ptj_fail", url))
            return False, "Connection refused", []

        with patch("power_planner_flet.push_to_karoo_http", side_effect=fake_karoo_fail), \
             patch.object(HammerheadClient, "upload_gpx", autospec=True, side_effect=fake_hh_upload):
            await send_code_btn.on_click(None)

        assert len(call_order) == 1
        assert call_order[0][0] == "karoo_ptj_fail"

    asyncio.run(run())
