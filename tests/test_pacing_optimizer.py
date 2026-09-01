import os
import io
import math
import pytest
import pandas as pd
from pacing_optimizer import AdvancedPacingOptimizer


@pytest.fixture
def optimizer():
    return AdvancedPacingOptimizer(
        initial_ftp=300,
        w_prime_max=20000,
        target_factor=0.82,
        carb_intake_per_hour=90,
        rider_weight=75.0,
        bike_weight=8.5
    )


@pytest.fixture
def sample_gpx_path():
    return os.path.join(os.path.dirname(__file__), "..", "oetztaler_route.gpx")


def test_velocity_solver_flat(optimizer):
    """Test velocity on a flat road (0% slope). Higher watts should produce higher speed."""
    v_200w = optimizer._solve_velocity(200, 0.0)
    v_300w = optimizer._solve_velocity(300, 0.0)
    
    assert v_300w > v_200w
    # 200W flat is typically ~ 30-36 km/h (8.3 - 10 m/s)
    assert 7.0 < v_200w < 11.5
    # 300W flat is typically ~ 37-43 km/h (10.2 - 12.0 m/s)
    assert 9.0 < v_300w < 13.0


def test_velocity_solver_climb_and_descent(optimizer):
    """Test velocity uphill (+8%) vs downhill (-5%)."""
    v_uphill = optimizer._solve_velocity(300, 8.0)
    v_downhill = optimizer._solve_velocity(150, -5.0)
    
    assert v_downhill > v_uphill
    # Uphill 300W on 8% is typically ~ 13-16 km/h (3.6 - 4.5 m/s)
    assert 3.0 < v_uphill < 5.5
    # Downhill is significantly faster
    assert v_downhill > 10.0


def test_parse_gpx_from_file(optimizer, sample_gpx_path):
    """Test parsing GPX route from local filesystem file."""
    if os.path.exists(sample_gpx_path):
        df = optimizer.parse_gpx(sample_gpx_path)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert 'distance_km' in df.columns
        assert 'slope' in df.columns
        assert 'elevation' in df.columns
        assert 'latitude' in df.columns
        assert 'longitude' in df.columns
        assert df['distance_km'].iloc[-1] > 100.0  # Ötztaler is ~220km


def test_parse_gpx_from_bytes(optimizer, sample_gpx_path):
    """Test parsing GPX route directly from raw bytes (Web mode simulation)."""
    if os.path.exists(sample_gpx_path):
        with open(sample_gpx_path, "rb") as f:
            raw_bytes = f.read()
            
        df = optimizer.parse_gpx(raw_bytes)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert len(df) > 1000
        assert df['distance_km'].iloc[-1] > 100.0


def test_parse_gpx_fallback_on_missing_file(optimizer):
    """Test that parser gracefully generates synthetic data if file is missing."""
    df = optimizer.parse_gpx("non_existent_file_path_12345.gpx")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert 'slope' in df.columns


def test_raw_pacing_dataframe_generation(optimizer, sample_gpx_path):
    """Test pacing calculations, W'-balance, and glycogen tank depletion."""
    df_route = optimizer.parse_gpx(sample_gpx_path)
    df_raw = optimizer.generate_raw_pacing_dataframe(df_route)
    
    assert 'target_power' in df_raw.columns
    assert 'w_prime_pct' in df_raw.columns
    assert 'glycogen_pct' in df_raw.columns
    assert 'duration_sec' in df_raw.columns
    
    # Power bounds check
    assert (df_raw['target_power'] >= 0).all()
    assert (df_raw['target_power'] <= optimizer.initial_ftp * 1.5).all()
    
    # W' balance bounds: 0% to 100%
    assert (df_raw['w_prime_pct'] >= 0.0).all()
    assert (df_raw['w_prime_pct'] <= 100.0).all()
    
    # Glycogen tank bounds: 0% to 100%
    assert (df_raw['glycogen_pct'] >= 0.0).all()
    assert (df_raw['glycogen_pct'] <= 100.0).all()
    
    # Glycogen should decrease over a long marathon
    assert df_raw['glycogen_pct'].iloc[-1] < df_raw['glycogen_pct'].iloc[0]


def test_interval_segmentation(optimizer, sample_gpx_path):
    """Test grouping raw data points into actionable intervals."""
    df_route = optimizer.parse_gpx(sample_gpx_path)
    df_raw = optimizer.generate_raw_pacing_dataframe(df_route)
    df_intervals = optimizer._segment_intervals(df_raw)
    
    assert isinstance(df_intervals, pd.DataFrame)
    assert not df_intervals.empty
    assert 'start_km' in df_intervals.columns
    assert 'end_km' in df_intervals.columns
    assert 'duration_min' in df_intervals.columns
    assert 'target_watt' in df_intervals.columns
    assert 'pct_ftp' in df_intervals.columns
    
    # Check that intervals cover the distance continuously
    assert df_intervals['start_km'].iloc[0] == pytest.approx(0.0, abs=0.1)
    for i in range(len(df_intervals) - 1):
        assert df_intervals['end_km'].iloc[i] == pytest.approx(df_intervals['start_km'].iloc[i+1], abs=0.1)
