import os
import json
import xml.etree.ElementTree as ET
import pytest
from pacing_optimizer import AdvancedPacingOptimizer


@pytest.fixture
def optimizer_and_data():
    opt = AdvancedPacingOptimizer(
        initial_ftp=310,
        w_prime_max=20000,
        target_factor=0.82,
        carb_intake_per_hour=90,
        rider_weight=76.0,
        bike_weight=8.0
    )
    gpx_path = os.path.join(os.path.dirname(__file__), "..", "oetztaler_route.gpx")
    df_route = opt.parse_gpx(gpx_path)
    df_raw = opt.generate_raw_pacing_dataframe(df_route)
    df_intervals = opt._segment_intervals(df_raw)
    return opt, df_route, df_raw, df_intervals


def test_export_to_karoo_json(optimizer_and_data):
    """Test Karoo JSON structure, cues, and valid serialization."""
    opt, df_route, df_raw, df_intervals = optimizer_and_data
    json_str = opt.export_to_karoo_json(df_route, route_name="test_route")
    
    assert isinstance(json_str, str)
    assert len(json_str) > 100
    
    # Parse JSON to ensure valid syntax
    data = json.loads(json_str)
    assert "meta" in data
    assert data["meta"]["version"] == "1.0"
    assert data["meta"]["route_name"] == "test_route"
    assert "track" in data
    assert len(data["track"]) > 0
    
    # Verify point properties
    p0 = data["track"][0]
    assert "lat" in p0
    assert "lon" in p0
    assert "target_power" in p0
    assert "zone_color" in p0


def test_export_to_zwift_zwo(optimizer_and_data, tmp_path):
    """Test Zwift .zwo XML workout file export."""
    opt, _, _, df_intervals = optimizer_and_data
    out_file = tmp_path / "test_workout.zwo"
    
    opt.export_to_zwift(df_intervals, str(out_file))
    assert out_file.exists()
    assert out_file.stat().st_size > 0
    
    # Parse XML to verify valid format
    tree = ET.parse(str(out_file))
    root = tree.getroot()
    assert root.tag == "workout_file"
    
    workout_tag = root.find("workout")
    assert workout_tag is not None
    intervals = list(workout_tag)
    assert len(intervals) > 0
    assert all(child.tag == "SteadyState" for child in intervals)


def test_export_to_garmin_fit(optimizer_and_data, tmp_path):
    """Test Garmin .fit binary workout file export."""
    opt, _, _, df_intervals = optimizer_and_data
    out_file = tmp_path / "test_workout.fit"
    
    opt.export_to_garmin_fit(df_intervals, str(out_file))
    assert out_file.exists()
    assert out_file.stat().st_size > 0
