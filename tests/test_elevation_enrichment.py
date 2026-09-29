import os
import json
import io
import urllib.request
import urllib.error
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from pacing_optimizer import AdvancedPacingOptimizer, ElevationFetchError, _get_elevation_cache_dir, _compute_route_hash


@pytest.fixture
def optimizer():
    return AdvancedPacingOptimizer()


@pytest.fixture
def karoo_gpx_path():
    path = os.path.join(os.path.dirname(__file__), "Karoo-WFH_20260925_Bassenge_Maastricht.gpx")
    if not os.path.exists(path):
        pytest.skip(f"Karoo test file not found at {path}")
    return path


def test_existing_elevation_does_not_call_api(optimizer):
    """Prüft, dass Routen mit vorhandenen Höhendaten die API nicht aufrufen."""
    df = pd.DataFrame({
        'latitude': [50.0, 50.1, 50.2],
        'longitude': [6.0, 6.1, 6.2],
        'distance_km': [0.0, 1.0, 2.0],
        'segment_len_m': [1000.0, 1000.0, 1000.0],
        'slope': [2.0, 3.0, 1.0],
        'elevation': [100.0, 120.0, 150.0]
    })
    
    with patch("urllib.request.urlopen") as mock_url:
        opt = AdvancedPacingOptimizer()
        has_valid = bool(df['elevation'].max() - df['elevation'].min() > 0.001)
        assert has_valid is True
        
        if os.path.exists("oetztaler_route.gpx"):
            df_oetztal = opt.parse_gpx("oetztaler_route.gpx")
            assert opt.elevation_source == "gpx"
            assert opt.elevation_error is None
        mock_url.assert_not_called()


def test_enrich_elevation_success_and_caching(optimizer, karoo_gpx_path):
    """Prüft erfolgreiche Höhenanreicherung via Open-Meteo und anschließendes Caching."""
    def mock_urlopen(req, timeout=8.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        query = url.split("?")[-1]
        lat_part = [p for p in query.split("&") if p.startswith("latitude=")][0]
        n_coords = len(lat_part.replace("latitude=", "").split(","))
        
        elevations = [120.0 + (i % 50) * 1.5 for i in range(n_coords)]
        payload = json.dumps({"elevation": elevations}).encode("utf-8")
        
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        return resp

    # Clean existing cache if present for clean test
    df_raw = optimizer.parse_gpx(karoo_gpx_path, auto_fetch_elevation=False)
    cache_key = _compute_route_hash(df_raw)
    cache_file = os.path.join(_get_elevation_cache_dir(), f"{cache_key}.json")
    if os.path.exists(cache_file):
        os.remove(cache_file)

    progress_updates = []
    def on_progress(frac, msg):
        progress_updates.append((frac, msg))

    # 1. First fetch: calls API
    with patch("urllib.request.urlopen", side_effect=mock_urlopen) as mock_api:
        with patch("time.sleep", return_value=None):
            df = optimizer.parse_gpx(karoo_gpx_path, auto_fetch_elevation=True, progress_callback=on_progress)
            
            assert not df.empty
            assert optimizer.elevation_source == "open-meteo"
            assert optimizer.elevation_error is None
            assert 'elevation' in df.columns
            assert (df['elevation'] > 0).all()
            assert mock_api.call_count > 0
            assert os.path.exists(cache_file)
            assert len(progress_updates) > 0

    # 2. Second fetch: loads from local cache with 0 API calls!
    with patch("urllib.request.urlopen") as mock_api_second:
        opt_second = AdvancedPacingOptimizer()
        df_cached = opt_second.parse_gpx(karoo_gpx_path, auto_fetch_elevation=True)
        
        assert not df_cached.empty
        assert opt_second.elevation_source == "cache"
        assert opt_second.elevation_error is None
        assert mock_api_second.call_count == 0
        np.testing.assert_allclose(df_cached['elevation'], df['elevation'])


def test_open_meteo_fallback_to_open_elevation(optimizer, karoo_gpx_path):
    """Prüft, dass bei einem Open-Meteo 429 Rate-Limit automatisch auf Open-Elevation umgeschaltet wird."""
    df_raw = optimizer.parse_gpx(karoo_gpx_path, auto_fetch_elevation=False)
    cache_key = _compute_route_hash(df_raw)
    cache_file = os.path.join(_get_elevation_cache_dir(), f"{cache_key}.json")
    if os.path.exists(cache_file):
        os.remove(cache_file)

    def mock_dual_urlopen(req, timeout=8.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "open-meteo" in url:
            # Simulate Open-Meteo Rate-Limit
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        elif "open-elevation" in url:
            # Open-Elevation receives POST with JSON
            data = json.loads(req.data.decode("utf-8"))
            results = [{"latitude": loc["latitude"], "longitude": loc["longitude"], "elevation": 140.0} for loc in data["locations"]]
            resp = MagicMock()
            resp.status = 200
            resp.read.return_value = json.dumps({"results": results}).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp
        raise ValueError(f"Unexpected url {url}")

    with patch("urllib.request.urlopen", side_effect=mock_dual_urlopen):
        with patch("time.sleep", return_value=None):
            df = optimizer.parse_gpx(karoo_gpx_path, auto_fetch_elevation=True)
            
            assert not df.empty
            assert optimizer.elevation_source == "open-elevation"
            assert optimizer.elevation_error is None
            assert (df['elevation'] == 140.0).all()


def test_both_providers_fail_error_handling(optimizer, karoo_gpx_path):
    """Prüft, dass eine verständliche Fehlermeldung gesetzt wird, wenn beide Provider scheitern."""
    df_raw = optimizer.parse_gpx(karoo_gpx_path, auto_fetch_elevation=False)
    cache_key = _compute_route_hash(df_raw)
    cache_file = os.path.join(_get_elevation_cache_dir(), f"{cache_key}.json")
    if os.path.exists(cache_file):
        os.remove(cache_file)

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        with patch("time.sleep", return_value=None):
            df = optimizer.parse_gpx(karoo_gpx_path, auto_fetch_elevation=True)
            
            assert not df.empty
            assert optimizer.elevation_source == "none"
            assert optimizer.elevation_error is not None
            assert "Höhendaten konnten weder über Open-Meteo" in optimizer.elevation_error
            assert (df['elevation'] == 0.0).all()


def test_enrich_elevation_network_error_direct_call(optimizer):
    """Prüft, dass der direkte Aufruf von enrich_elevation_from_api bei Netzwerkfehlern ElevationFetchError wirft."""
    df_missing_ele = pd.DataFrame({
        'latitude': [50.76941, 50.76945, 50.76954],
        'longitude': [6.04859, 6.0481, 6.04785],
        'distance_km': [0.0, 0.05, 0.1],
        'segment_len_m': [50.0, 50.0, 50.0],
        'slope': [0.0, 0.0, 0.0],
        'elevation': [0.0, 0.0, 0.0]
    })
    
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        with patch("time.sleep", return_value=None):
            with pytest.raises(ElevationFetchError) as exc_info:
                optimizer.enrich_elevation_from_api(df_missing_ele, timeout_per_request=1.0, total_timeout=2.0)
            
            assert "Höhendaten konnten weder über Open-Meteo" in str(exc_info.value)
            assert optimizer.elevation_source == "none"
            assert optimizer.elevation_error is not None
