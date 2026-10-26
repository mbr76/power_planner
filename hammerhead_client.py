"""
Hammerhead Cloud Client & Official SRAM OAuth2 PKCE Browser Authentication Flow.
Redirects the user directly to the official SRAM Single Sign-On page
(https://sramid-auth.sram.com/authorize) inside a native browser window,
intercepts the authorization code on redirect, and exchanges it via PKCE for a
Hammerhead Cloud Bearer JWT token — without ever asking for credentials in the app or on localhost.
"""

import base64
import hashlib
import html
import http.server
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from typing import Callable, Optional, Tuple
import requests


HAMMERHEAD_DASHBOARD_URL = "https://dashboard.hammerhead.io"
SRAM_AUTH_DOMAIN = "sramid-auth.sram.com"
SRAM_AUTH_CLIENT_ID = "MFhsYcUUMGGBPaA4KpGKxUuzyqOY9ReM"
SRAM_AUTH_AUDIENCE = "https://api.quarqnet.com"
SRAM_REDIRECT_URI = "https://dashboard.hammerhead.io/accounts/callback/sram"
SRAM_SCOPES = "offline_access profile email openid"


def generate_pkce_pair() -> Tuple[str, str]:
    """Erzeugt ein kryptographisches PKCE (code_verifier, code_challenge) Paar (S256)."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_sram_authorize_url(code_challenge: str, state: str = "sram") -> str:
    """Erzeugt die offizielle SRAM OAuth2 PKCE Autorisierungs-URL für das Hammerhead Dashboard."""
    params = {
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "client_id": SRAM_AUTH_CLIENT_ID,
        "redirect_uri": SRAM_REDIRECT_URI,
        "prompt": "login",
        "scope": SRAM_SCOPES,
        "audience": SRAM_AUTH_AUDIENCE,
        "state": state,
    }
    return f"https://{SRAM_AUTH_DOMAIN}/authorize?{urllib.parse.urlencode(params)}"


def extract_user_id_from_jwt(token: str) -> Optional[str]:
    """
    Extrahiert die Hammerhead User-ID ('sub', 'user_id' oder 'id') aus einem JWT Bearer-Token.
    """
    if not token or not isinstance(token, str):
        return None
    clean = token.strip()
    if clean.lower().startswith("bearer "):
        clean = clean[7:].strip()
    parts = clean.split(".")
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    rem = len(payload_b64) % 4
    if rem:
        payload_b64 += "=" * (4 - rem)
    try:
        raw = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            uid = payload.get("sub") or payload.get("user_id") or payload.get("id")
            if uid:
                return str(uid)
    except Exception:
        return None
    return None


def extract_email_from_jwt(token: str) -> Optional[str]:
    """
    Extrahiert optional E-Mail oder Nutzername aus einem JWT Bearer-Token.
    """
    if not token or not isinstance(token, str):
        return None
    clean = token.strip()
    if clean.lower().startswith("bearer "):
        clean = clean[7:].strip()
    parts = clean.split(".")
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    rem = len(payload_b64) % 4
    if rem:
        payload_b64 += "=" * (4 - rem)
    try:
        raw = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            ident = (
                payload.get("email")
                or payload.get("sramEmail")
                or payload.get("preferred_username")
                or payload.get("name")
            )
            if ident:
                return str(ident)
    except Exception:
        return None
    return None


class HammerheadClient:
    """
    Client für die Hammerhead Dashboard Cloud-API (https://dashboard.hammerhead.io/v1).
    Unterstützt den offiziellen SRAM OAuth2 PKCE Token-Austausch, Token-Refresh
    und den Upload von GPX-Routen.
    """
    BASE_URL = "https://dashboard.hammerhead.io/v1"

    def __init__(
        self,
        token: Optional[str] = None,
        user_id: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.refresh_token: Optional[str] = refresh_token.strip() if refresh_token else None
        if token:
            clean_token = token.strip()
            if clean_token.lower().startswith("bearer "):
                clean_token = clean_token[7:].strip()
            self.token = clean_token
            self.user_id = (user_id.strip() if user_id else None) or extract_user_id_from_jwt(clean_token)
        elif user_id:
            self.user_id = user_id.strip()

    @property
    def is_authenticated(self) -> bool:
        return bool(self.token and self.user_id)

    def set_token(
        self,
        token: str,
        user_id: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Setzt ein vorhandenes JWT-Token und ermittelt (falls nicht angegeben) die User-ID aus dem JWT-Payload.
        """
        if not token or not token.strip():
            raise ValueError("Kein gültiges Token übergeben.")
        clean_token = token.strip()
        if clean_token.lower().startswith("bearer "):
            clean_token = clean_token[7:].strip()
        resolved_uid = (user_id.strip() if user_id and user_id.strip() else None) or extract_user_id_from_jwt(clean_token)
        if not resolved_uid:
            raise ValueError("User-ID konnte nicht aus dem Token ermittelt werden.")
        self.token = clean_token
        self.user_id = resolved_uid
        if refresh_token is not None:
            self.refresh_token = refresh_token.strip() or None
        return self.token, self.user_id

    def clear_auth(self) -> None:
        self.token = None
        self.user_id = None
        self.refresh_token = None

    def exchange_sram_code(self, code: str, code_verifier: str, timeout: int = 15) -> Tuple[str, str, str]:
        """
        Tauscht den nach dem offiziellen SRAM-Browser-Login erhaltenen OAuth-Authorization-Code
        per PKCE in ein SRAM-Token und anschließend über /v1/auth/sram/mobile/token in ein
        Hammerhead-JWT-Token um. Gibt (hh_token, hh_user_id, email) zurück.
        """
        if not code or not code_verifier:
            raise ValueError("Authorization-Code oder PKCE-Verifier fehlt.")

        # Schritt 1: OAuth-Code gegen SRAM-Tokens tauschen (sramid-auth.sram.com/oauth/token)
        sram_token_url = f"https://{SRAM_AUTH_DOMAIN}/oauth/token"
        sram_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Origin": HAMMERHEAD_DASHBOARD_URL,
            "Referer": f"{HAMMERHEAD_DASHBOARD_URL}/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        }
        sram_payload = {
            "grant_type": "authorization_code",
            "client_id": SRAM_AUTH_CLIENT_ID,
            "code_verifier": code_verifier,
            "code": code,
            "redirect_uri": SRAM_REDIRECT_URI,
        }
        sram_resp = requests.post(sram_token_url, data=sram_payload, headers=sram_headers, timeout=timeout)
        if sram_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"SRAM OAuth Token-Austausch fehlgeschlagen (HTTP {sram_resp.status_code}): {sram_resp.text.strip()[:200]}"
            )

        sram_data = sram_resp.json()
        sram_access = sram_data.get("access_token")
        sram_refresh = sram_data.get("refresh_token")
        sram_id_token = sram_data.get("id_token") or ""
        if not sram_access or not sram_refresh:
            raise RuntimeError("SRAM OAuth-Antwort enthielt kein access_token oder refresh_token.")

        sram_email = extract_email_from_jwt(sram_id_token) or extract_email_from_jwt(sram_access)

        # Schritt 2: SRAM-Tokens gegen Hammerhead-Dashboard-Tokens tauschen (/v1/auth/sram/mobile/token)
        hh_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": HAMMERHEAD_DASHBOARD_URL,
            "Referer": f"{HAMMERHEAD_DASHBOARD_URL}/",
            "User-Agent": sram_headers["User-Agent"],
        }
        hh_resp = requests.post(
            f"{self.BASE_URL}/auth/sram/mobile/token",
            json={"accessToken": sram_access, "refreshToken": sram_refresh},
            headers=hh_headers,
            timeout=timeout,
        )

        if hh_resp.status_code not in (200, 201, 409):
            raise RuntimeError(
                f"Hammerhead SRAM-Token-Austausch fehlgeschlagen (HTTP {hh_resp.status_code}): {hh_resp.text.strip()[:200]}"
            )

        hh_data = hh_resp.json()

        # Schritt 2b: Falls mehrere Hammerhead-Accounts mit diesem SRAM-Konto verknüpft sind (HTTP 409 / temp token)
        if "token" in hh_data and "access_token" not in hh_data:
            temp_token = hh_data["token"]
            acc_resp = requests.get(
                f"{self.BASE_URL}/auth/sram/{temp_token}/accounts",
                headers={"Accept": "application/json", "Origin": HAMMERHEAD_DASHBOARD_URL},
                timeout=timeout,
            )
            if acc_resp.status_code != 200:
                raise RuntimeError(f"Hammerhead Account-Auswahl fehlgeschlagen (HTTP {acc_resp.status_code}).")
            acc_json = acc_resp.json()
            accounts = acc_json.get("accounts") or []
            if not accounts:
                raise RuntimeError("Kein verknüpftes Hammerhead-Konto zum SRAM-Account gefunden.")
            chosen_uid = accounts[0].get("userId")
            sram_email = sram_email or accounts[0].get("email") or acc_json.get("email")
            sel_resp = requests.post(
                f"{self.BASE_URL}/auth/sram/{temp_token}",
                data={"userId": chosen_uid},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "Origin": HAMMERHEAD_DASHBOARD_URL,
                },
                timeout=timeout,
            )
            if sel_resp.status_code not in (200, 201):
                raise RuntimeError(f"Hammerhead Account-Aktivierung fehlgeschlagen (HTTP {sel_resp.status_code}).")
            hh_data = sel_resp.json()

        hh_access = hh_data.get("access_token")
        hh_refresh = hh_data.get("refresh_token")
        if not hh_access:
            raise RuntimeError("Hammerhead-Antwort enthielt kein gültiges access_token.")

        tok, uid = self.set_token(hh_access, refresh_token=hh_refresh)
        resolved_email = (
            extract_email_from_jwt(tok)
            or sram_email
            or f"SRAM Account ({uid[:8]})"
        )
        return tok, uid, resolved_email

    def refresh_access_token(self, timeout: int = 12) -> bool:
        """Erneuert das Hammerhead access_token über das gespeicherte refresh_token."""
        if not self.refresh_token:
            return False
        try:
            resp = requests.post(
                f"{self.BASE_URL}/auth/token",
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "Origin": HAMMERHEAD_DASHBOARD_URL,
                },
                timeout=timeout,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                new_tok = data.get("access_token")
                new_ref = data.get("refresh_token") or self.refresh_token
                if new_tok:
                    self.set_token(new_tok, self.user_id, refresh_token=new_ref)
                    return True
        except Exception:
            pass
        return False

    def upload_gpx(self, gpx_content: str, route_name: str, timeout: int = 20) -> dict:
        """
        Lädt einen GPX-XML-String als Route in die Hammerhead Cloud hoch.
        Nutzt primär /v1/users/{user_id}/routes/import/file (mit Fallback auf /v1/users/{user_id}/routes).
        Wichtig: Dateiname muss zwingend die Endung '.gpx' in Kleinbuchstaben besitzen.
        """
        if not self.is_authenticated:
            raise ValueError("Nicht bei Hammerhead angemeldet (Token oder User-ID fehlt).")
        if not gpx_content or not gpx_content.strip():
            raise ValueError("Leerer GPX-Inhalt kann nicht hochgeladen werden.")

        base_name = re.sub(r'[\\/*?:"<>|]', "_", (route_name or "Pacing_Route").strip())
        if base_name.lower().endswith(".gpx"):
            base_name = base_name[:-4]
        filename = f"{base_name}.gpx"
        gpx_bytes = gpx_content.encode("utf-8")

        endpoints = [
            f"{self.BASE_URL}/users/{self.user_id}/routes/import/file",
            f"{self.BASE_URL}/users/{self.user_id}/routes",
        ]

        for attempt in range(2):
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Origin": HAMMERHEAD_DASHBOARD_URL,
                "Referer": f"{HAMMERHEAD_DASHBOARD_URL}/routes",
                "User-Agent": "PowerPlanner/1.0",
            }

            last_resp = None
            got_401 = False
            for idx, url in enumerate(endpoints):
                files = {
                    "file": (filename, gpx_bytes, "application/gpx+xml")
                }
                resp = requests.post(url, headers=headers, files=files, timeout=timeout)
                last_resp = resp
                if resp.status_code in (200, 201):
                    try:
                        return resp.json()
                    except Exception:
                        return {"status": "ok", "filename": filename}
                if resp.status_code == 401:
                    got_401 = True
                    break
                if resp.status_code in (404, 405) and idx == 0:
                    continue
                break

            if got_401 and attempt == 0 and self.refresh_access_token():
                continue
            break

        status_code = last_resp.status_code if last_resp is not None else "N/A"
        body_preview = (last_resp.text.strip()[:250] if last_resp is not None and last_resp.text else "")
        raise RuntimeError(f"Hammerhead GPX-Upload fehlgeschlagen (HTTP {status_code}): {body_preview}")


class BrowserAuthSession:
    """
    Öffnet ein dediziertes Browserfenster direkt auf der offiziellen SRAM-Anmeldeseite
    (https://sramid-auth.sram.com/authorize?...) mittels OAuth 2.0 PKCE.
    Sobald SRAM nach dem Login an https://dashboard.hammerhead.io/accounts/callback/sram?code=...
    weiterleitet, fängt das Browserfenster den Authorization-Code ab und tauscht ihn
    im Hintergrund gegen das Hammerhead-Cloud-Token ein.
    """

    def __init__(
        self,
        on_success: Callable[..., None],
        auth_client_factory: Callable[[], HammerheadClient] = HammerheadClient,
        clear_session: bool = False,
    ):
        self.on_success = on_success
        self.auth_client_factory = auth_client_factory
        self.clear_session = clear_session
        self.code_verifier, self.code_challenge = generate_pkce_pair()
        self.sram_authorize_url = build_sram_authorize_url(self.code_challenge)
        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._webview_proc: Optional[subprocess.Popen] = None
        self.port: int = 0

    def process_request(self, method: str, path: str, body: str = "") -> Tuple[int, str]:
        """
        Verarbeitet den lokalen Callback (/callback?code=... oder /callback?token=...).
        Fragt niemals Passwörter auf localhost ab.
        """
        parsed = urllib.parse.urlparse(path)
        method_upper = (method or "GET").upper()

        if method_upper == "GET":
            if parsed.path == "/callback":
                qs = urllib.parse.parse_qs(parsed.query)
                code = (qs.get("code") or [""])[0].strip()
                token = (qs.get("token") or qs.get("access_token") or [""])[0].strip()
                user_id = (qs.get("user_id") or [""])[0].strip() or None
                email = (qs.get("email") or [""])[0].strip()

                if code:
                    try:
                        client = self.auth_client_factory()
                        tok, uid, resolved_email = client.exchange_sram_code(code, self.code_verifier)
                        html_out = self._render_success_page(resolved_email, uid)
                        threading.Thread(
                            target=self._complete_and_stop,
                            args=(tok, uid, resolved_email, client.refresh_token),
                            daemon=True,
                        ).start()
                        return 200, html_out
                    except Exception as e:
                        return 400, self._render_redirect_page(error=str(e))

                if token:
                    try:
                        client = self.auth_client_factory()
                        tok, uid = client.set_token(token, user_id)
                        resolved_email = email or extract_email_from_jwt(tok) or f"SRAM Account ({uid[:8]})"
                        html_out = self._render_success_page(resolved_email, uid)
                        threading.Thread(
                            target=self._complete_and_stop,
                            args=(tok, uid, resolved_email, client.refresh_token),
                            daemon=True,
                        ).start()
                        return 200, html_out
                    except Exception as e:
                        return 400, self._render_redirect_page(error=str(e))

            return 200, self._render_redirect_page()

        if method_upper == "POST" and parsed.path == "/token":
            form = urllib.parse.parse_qs(body or "")
            raw_val = (form.get("token") or [""])[0].strip()
            user_id = (form.get("user_id") or [""])[0].strip() or None
            email = (form.get("email") or [""])[0].strip()
            try:
                client = self.auth_client_factory()
                # Unterstützt auch das Einfügen der Callback-URL (?code=...) im externen Browser-Fallback
                if "code=" in raw_val:
                    parsed_cb = urllib.parse.urlparse(raw_val if "://" in raw_val else f"https://x/?{raw_val.lstrip('?')}")
                    cb_code = (urllib.parse.parse_qs(parsed_cb.query).get("code") or [""])[0].strip()
                    if cb_code:
                        tok, uid, resolved_email = client.exchange_sram_code(cb_code, self.code_verifier)
                        html_out = self._render_success_page(resolved_email, uid)
                        threading.Thread(
                            target=self._complete_and_stop,
                            args=(tok, uid, resolved_email, client.refresh_token),
                            daemon=True,
                        ).start()
                        return 200, html_out

                tok, uid = client.set_token(raw_val, user_id)
                resolved_email = email or extract_email_from_jwt(tok) or f"SRAM Account ({uid[:8]})"
                html_out = self._render_success_page(resolved_email, uid)
                threading.Thread(
                    target=self._complete_and_stop,
                    args=(tok, uid, resolved_email, client.refresh_token),
                    daemon=True,
                ).start()
                return 200, html_out
            except Exception as e:
                return 400, self._render_redirect_page(error=str(e))

        return 404, "Not Found"

    def start(self) -> str:
        """Startet den lokalen Callback-Empfänger und gibt die Login-URL zurück."""
        if self._server is not None:
            return self.get_login_url()

        session = self

        class AuthHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format_str, *args):
                pass

            def _send_html(self, status: int, content: str):
                encoded = content.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                self.close_connection = True

            def do_GET(self):
                status, html_out = session.process_request("GET", self.path)
                self._send_html(status, html_out)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
                status, html_out = session.process_request("POST", self.path, raw_body)
                self._send_html(status, html_out)

        server_cls = getattr(http.server, "ThreadingHTTPServer", http.server.HTTPServer)
        self._server = server_cls(("127.0.0.1", 0), AuthHandler)
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.get_login_url()

    def get_login_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/login"

    def get_callback_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/callback"

    def launch_native_hammerhead_browser(self) -> bool:
        """
        Öffnet ein natives Browserfenster (WKWebView auf macOS & iOS, WebView auf Android),
        das direkt die offizielle SRAM-Anmeldeseite (https://sramid-auth.sram.com/authorize?...)
        lädt und beim Redirect auf /accounts/callback/sram?code=... automatisch den Code
        an den lokalen Callback-Server übergibt.
        """
        if self._server is None:
            self.start()

        callback_url = self.get_callback_url()
        target_url = self.sram_authorize_url

        # 1. iOS / iPadOS & Android: Trigger an AppDelegate.swift bzw. MainActivity.kt senden
        flet_platform = (os.environ.get("FLET_PLATFORM") or "").lower()
        is_mobile_native = (
            flet_platform in ("ios", "ipados", "android")
            or sys.platform in ("ios", "android")
            or "ANDROID_DATA" in os.environ
        )
        if is_mobile_native:
            payload = {
                "target_url": target_url,
                "callback_url": callback_url,
                "clear_session": bool(self.clear_session),
            }
            wrote_any = False
            candidate_dirs = [tempfile.gettempdir()]
            for env_key in ("FLET_APP_STORAGE_TEMP", "FLET_APP_STORAGE_CACHE", "FLET_APP_STORAGE_DATA"):
                if os.environ.get(env_key) and os.environ[env_key] not in candidate_dirs:
                    candidate_dirs.append(os.environ[env_key])
            for d in candidate_dirs:
                try:
                    os.makedirs(d, exist_ok=True)
                    trig_path = os.path.join(d, "hh_webview_trigger.json")
                    with open(trig_path, "w", encoding="utf-8") as f:
                        json.dump(payload, f)
                    wrote_any = True
                except Exception:
                    continue
            if wrote_any:
                return True

        # 2. macOS Desktop: Natives WKWebView-Fenster starten
        if sys.platform == "darwin":
            bin_path = self._ensure_macos_webview_binary()
            if bin_path and os.path.isfile(bin_path):
                cmd = [bin_path, target_url, callback_url]
                if self.clear_session:
                    cmd.append("--clear")
                try:
                    self._webview_proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return True
                except Exception:
                    pass

        return False

    @staticmethod
    def _ensure_macos_webview_binary() -> Optional[str]:
        """Kompiliert bei Bedarf den nativen macOS WKWebView-Helper und cached das Binary."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        swift_src = os.path.join(script_dir, "scripts", "hh_webview_macos.swift")
        if not os.path.isfile(swift_src):
            return None

        bin_path = os.path.join(tempfile.gettempdir(), "power_planner_hh_webview_macos_v3")
        try:
            if os.path.isfile(bin_path) and os.access(bin_path, os.X_OK):
                if os.path.getmtime(bin_path) >= os.path.getmtime(swift_src):
                    return bin_path
        except Exception:
            pass

        swiftc = shutil.which("swiftc") or "/usr/bin/swiftc"
        if not os.path.isfile(swiftc):
            return None

        mod_cache = os.path.join(tempfile.gettempdir(), "swift-module-cache")
        os.makedirs(mod_cache, exist_ok=True)
        try:
            subprocess.run(
                [swiftc, "-disable-sandbox", "-module-cache-path", mod_cache, swift_src, "-o", bin_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=25,
            )
            return bin_path
        except Exception:
            return None

    def _complete_and_stop(self, token: str, user_id: str, identifier: str, refresh_token: Optional[str] = None):
        try:
            if self.on_success:
                try:
                    self.on_success(token, user_id, identifier, refresh_token)
                except TypeError:
                    self.on_success(token, user_id, identifier)
        finally:
            time.sleep(0.5)
            self.stop()

    def stop(self):
        proc = self._webview_proc
        self._webview_proc = None
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass

        srv = self._server
        self._server = None
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass

    def _render_redirect_page(self, error: Optional[str] = None) -> str:
        err_html = ""
        if error:
            err_html = f'<div class="alert">⚠️ {html.escape(error)}</div>'

        return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Weiterleitung zu Hammerhead / SRAM — Power-Planner</title>
    <style>
        :root {{ color-scheme: dark; }}
        body {{
            margin: 0; padding: 24px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0f1318; color: #f3f4f6;
            display: flex; justify-content: center; align-items: center; min-height: 90vh;
        }}
        .card {{
            width: 100%; max-width: 480px;
            background: #1a2028; border: 1px solid #2d3748;
            border-radius: 16px; padding: 28px;
            box-shadow: 0 16px 40px rgba(0,0,0,0.45);
        }}
        .badge {{
            display: inline-block; background: rgba(251, 191, 36, 0.15);
            color: #fbbf24; padding: 4px 10px; border-radius: 999px;
            font-size: 12px; font-weight: 600; margin-bottom: 12px;
        }}
        h1 {{ margin: 0 0 10px 0; font-size: 21px; }}
        p {{ color: #9ca3af; font-size: 13.5px; line-height: 1.5; margin: 0 0 16px 0; }}
        .alert {{
            background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4);
            color: #fca5a5; padding: 12px; border-radius: 10px; font-size: 13px; margin-bottom: 16px;
        }}
        a.btn {{
            display: block; text-align: center; text-decoration: none;
            padding: 13px 16px; border-radius: 10px;
            background: #fbbf24; color: #111827; font-weight: 700; font-size: 14px;
            margin-bottom: 18px;
        }}
        a.btn:hover {{ background: #f59e0b; }}
        input {{
            width: 100%; box-sizing: border-box; padding: 10px 12px;
            border-radius: 8px; border: 1px solid #374151;
            background: #0f1318; color: #f9fafb; font-size: 13px; margin: 8px 0 10px 0;
        }}
        button.sec {{
            width: 100%; padding: 10px; border: 1px solid #4b5563;
            border-radius: 8px; background: #1f2937; color: #e5e7eb;
            font-weight: 600; cursor: pointer;
        }}
    </style>
</head>
<body>
    <div class="card">
        <span class="badge">🔒 Offizieller Hammerhead / SRAM Login</span>
        <h1>Auf Hammerhead / SRAM anmelden</h1>
        <p>
            Deine Zugangsdaten werden <strong>niemals</strong> im Power-Planner oder auf localhost eingegeben,
            sondern direkt auf der offiziellen Webseite von <strong>Hammerhead / SRAM</strong> ({HAMMERHEAD_DASHBOARD_URL}).
        </p>
        {err_html}
        <a class="btn" href="{html.escape(self.sram_authorize_url)}" target="_blank" rel="noopener">
            Offiziellen SRAM / Hammerhead Login öffnen ↗
        </a>
        <details>
            <summary style="cursor:pointer;font-size:12.5px;color:#9ca3af;">Fallback für externe Browser: Callback-URL oder Token übergeben</summary>
            <form method="POST" action="/token" style="margin-top:10px;">
                <input name="token" type="text" placeholder="Callback-URL (?code=...) oder Bearer JWT-Token" required>
                <button type="submit" class="sec">Verbinden</button>
            </form>
        </details>
    </div>
</body>
</html>"""

    @staticmethod
    def _render_success_page(identifier: str, user_id: str) -> str:
        safe_id = html.escape(identifier or "Hammerhead Account")
        safe_uid = html.escape(user_id or "")
        return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Anmeldung erfolgreich — Power-Planner</title>
    <style>
        body {{
            margin: 0; padding: 24px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0f1318; color: #f3f4f6;
            display: flex; justify-content: center; align-items: center; min-height: 90vh;
        }}
        .card {{
            width: 100%; max-width: 420px;
            background: #1a2028; border: 1px solid #10b981;
            border-radius: 16px; padding: 28px; text-align: center;
            box-shadow: 0 16px 40px rgba(0,0,0,0.45);
        }}
        .icon {{ font-size: 42px; margin-bottom: 12px; }}
        h1 {{ margin: 0 0 8px 0; font-size: 21px; color: #34d399; }}
        p {{ color: #d1d5db; font-size: 14px; line-height: 1.5; }}
        .meta {{
            margin-top: 14px; padding: 10px; border-radius: 8px;
            background: #111827; font-family: monospace; font-size: 12px; color: #9ca3af;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✅</div>
        <h1>Hammerhead Cloud verbunden!</h1>
        <p>Die Anmeldung über Hammerhead / SRAM für <strong>{safe_id}</strong> war erfolgreich.<br>Das Fenster schließt sich automatisch.</p>
        <div class="meta">User-ID: {safe_uid}</div>
    </div>
</body>
</html>"""
