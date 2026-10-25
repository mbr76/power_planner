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


def test_steep_climbing_power_and_coasting():
    """Verify that 18% steep climbs demand >300W even when relaxed, and descents allow coasting (0W)."""
    opt = AdvancedPacingOptimizer(initial_ftp=300, target_factor=0.65, rider_weight=75.0, bike_weight=8.5)
    
    # 1. Steep ramp (18%)
    df_steep = pd.DataFrame([{
        'distance_km': 0.1, 'segment_len_m': 100.0, 'slope': 18.0,
        'latitude': 50.0, 'longitude': 5.0, 'elevation': 118.0
    }])
    raw_steep = opt.generate_raw_pacing_dataframe(df_steep)
    # Power must be well above 300W on 18% to maintain minimum rideable cadence/speed
    assert raw_steep['target_power'].iloc[0] >= 320
    
    # 2. Steep descent (-6%)
    df_desc = pd.DataFrame([{
        'distance_km': 0.1, 'segment_len_m': 100.0, 'slope': -6.0,
        'latitude': 50.0, 'longitude': 5.0, 'elevation': 94.0
    }])
    raw_desc = opt.generate_raw_pacing_dataframe(df_desc)
    # Coasting on steep downhill
    assert raw_desc['target_power'].iloc[0] == 0
    
    # 3. Flat (0%)
    df_flat = pd.DataFrame([{
        'distance_km': 0.1, 'segment_len_m': 100.0, 'slope': 0.0,
        'latitude': 50.0, 'longitude': 5.0, 'elevation': 100.0
    }])
    raw_flat = opt.generate_raw_pacing_dataframe(df_flat)
    # Dynamic mode saves energy on flats (Zone 2 cruising around 77% of target factor)
    assert raw_flat['target_power'].iloc[0] == pytest.approx(opt.initial_ftp * opt.target_factor * 0.775, abs=15)
    
    # In steady mode, flat is strictly initial_ftp * target_factor
    opt_steady = AdvancedPacingOptimizer(initial_ftp=300, target_factor=0.65, pacing_mode="steady")
    raw_flat_steady = opt_steady.generate_raw_pacing_dataframe(df_flat)
    assert raw_flat_steady['target_power'].iloc[0] == pytest.approx(opt_steady.initial_ftp * opt_steady.target_factor, abs=10)


def test_short_steep_kicker_interval_isolation():
    """Verify that a 200m kicker with >10m elevation gain is isolated into its own distinct interval."""
    opt = AdvancedPacingOptimizer(initial_ftp=300, target_factor=0.70, rider_weight=75.0, bike_weight=8.5)
    
    # Build 2km flat, 200m climb with 16m gain (8% slope), 2km flat
    points = []
    dist = 0.0
    ele = 100.0
    # 2km flat
    for _ in range(40):
        dist += 0.05
        points.append({'distance_km': dist, 'segment_len_m': 50.0, 'slope': 0.0, 'latitude': 50.0, 'longitude': 5.0, 'elevation': ele})
    # 200m kicker (4 steps of 50m, 4m gain each -> 16m gain total, 8% slope)
    for _ in range(4):
        dist += 0.05
        ele += 4.0
        points.append({'distance_km': dist, 'segment_len_m': 50.0, 'slope': 8.0, 'latitude': 50.0, 'longitude': 5.0, 'elevation': ele})
    # 2km flat
    for _ in range(40):
        dist += 0.05
        points.append({'distance_km': dist, 'segment_len_m': 50.0, 'slope': 0.0, 'latitude': 50.0, 'longitude': 5.0, 'elevation': ele})
        
    df_route = pd.DataFrame(points)
    df_intervals = opt.optimize_pacing(df_route)
    
    # Should identify the kicker as a distinct interval with higher wattage
    assert len(df_intervals) >= 3
    
    # Find the kicker interval
    kicker_int = df_intervals[(df_intervals['start_km'] >= 1.9) & (df_intervals['end_km'] <= 2.4)]
    assert not kicker_int.empty
    kicker_row = kicker_int.iloc[0]
    
    # Kicker target wattage must be significantly higher than flat pacing (~210W)
    assert kicker_row['target_watt'] >= 250
    # Duration of kicker should be ~ 1 minute
    assert kicker_row['duration_min'] < 2.5


def test_duration_spread_between_min_and_max_effort(sample_gpx_path):
    """Verify noticeable time spread between minimal effort (TF 0.65) and maximal effort (0.95)."""
    if os.path.exists(sample_gpx_path):
        opt_min = AdvancedPacingOptimizer(initial_ftp=300, target_factor=0.65)
        df_route = opt_min.parse_gpx(sample_gpx_path, auto_fetch_elevation=False)
        raw_min = opt_min.generate_raw_pacing_dataframe(df_route)
        time_min_sec = raw_min['duration_sec'].sum()
        
        opt_max = AdvancedPacingOptimizer(initial_ftp=300, target_factor=0.95)
        raw_max = opt_max.generate_raw_pacing_dataframe(df_route)
        time_max_sec = raw_max['duration_sec'].sum()
        
        # On a 220+ km route like Ötztaler, spread between 0.65 and 0.95 should be >= 1 hour (3600s)
        time_diff_hours = (time_min_sec - time_max_sec) / 3600.0
        assert time_diff_hours >= 1.0


def test_velocity_descent_speed_cap():
    """Verify that descent speed is physically constrained to realistic technical speeds."""
    opt = AdvancedPacingOptimizer(max_descent_kmh=56.0)
    v_steep_descent = opt._solve_velocity(target_watt=200, slope_pct=-12.0)
    
    # Speed in km/h must not exceed max_descent_kmh
    assert v_steep_descent * 3.6 <= 56.01


def test_lowest_gear_ratio_affects_climbing_floor():
    """Verify that a harder lowest gear (e.g. 39/28 vs 33/34) raises the minimum power floor on steep ramps."""
    opt_easy = AdvancedPacingOptimizer(
        initial_ftp=300, target_factor=0.65, rider_weight=80.0, bike_weight=10.0,
        lowest_gear_ratio=33.0 / 34.0, min_climb_cadence=75.0
    )
    opt_hard = AdvancedPacingOptimizer(
        initial_ftp=300, target_factor=0.65, rider_weight=80.0, bike_weight=10.0,
        lowest_gear_ratio=39.0 / 28.0, min_climb_cadence=75.0
    )
    
    df_steep = pd.DataFrame([{
        'distance_km': 0.1, 'segment_len_m': 100.0, 'slope': 12.0,
        'latitude': 50.0, 'longitude': 5.0, 'elevation': 112.0
    }])
    
    raw_easy = opt_easy.generate_raw_pacing_dataframe(df_steep)
    raw_hard = opt_hard.generate_raw_pacing_dataframe(df_steep)
    
    # Harder gear requires higher speed and therefore significantly higher floor wattage at the same cadence
    assert raw_hard['target_power'].iloc[0] > raw_easy['target_power'].iloc[0]
    assert raw_hard['target_power'].iloc[0] >= 340


def test_highest_gear_ratio_limits_downhill_pedaling_speed():
    """Verify that pedaling speed on mild descents is constrained by top gear spin-out limit."""
    # 46/10 at 105 rpm -> ~61.4 km/h max pedaling speed
    opt_46_10 = AdvancedPacingOptimizer(
        highest_gear_ratio=46.0 / 10.0, max_pedal_cadence=105.0,
        wheel_circumference_m=2.12, max_descent_kmh=75.0
    )
    # 46/11 at 95 rpm -> ~50.6 km/h max pedaling speed
    opt_46_11 = AdvancedPacingOptimizer(
        highest_gear_ratio=46.0 / 11.0, max_pedal_cadence=95.0,
        wheel_circumference_m=2.12, max_descent_kmh=75.0
    )
    
    # Mild descent (-3.5%) with 300W pedaling
    v_fast_gear = opt_46_10._solve_velocity(target_watt=300, slope_pct=-3.5)
    v_slow_gear = opt_46_11._solve_velocity(target_watt=300, slope_pct=-3.5)
    
    assert v_fast_gear > v_slow_gear
    # The slow gear must be capped near its spin-out speed (~50.6 km/h)
    assert v_slow_gear * 3.6 <= 52.0


def test_downhill_spin_out_zeros_target_power():
    """Verify that on steep descents where coasting speed exceeds pedaling capability, target power is 0W."""
    opt = AdvancedPacingOptimizer(
        highest_gear_ratio=46.0 / 10.0, max_pedal_cadence=105.0,
        cda=0.32, crr=0.0045, rider_weight=80.0, bike_weight=10.0
    )
    # On an 8% descent, 90kg will coast at >65 km/h, well beyond 46/10 pedaling range (61.4 km/h)
    df_steep_desc = pd.DataFrame([{
        'distance_km': 0.1, 'segment_len_m': 100.0, 'slope': -8.0,
        'latitude': 50.0, 'longitude': 5.0, 'elevation': 92.0
    }])
    raw = opt.generate_raw_pacing_dataframe(df_steep_desc)
    assert raw['target_power'].iloc[0] == 0


def test_altitude_hypoxia_and_air_density():
    """Verify Bassett/Peronnet altitude hypoxia factor and barometric air density speed effect."""
    opt = AdvancedPacingOptimizer(initial_ftp=300, target_factor=0.78)
    # Below 1000m: no hypoxia penalty
    assert opt.get_altitude_factor(500.0) == 1.0
    assert opt.get_altitude_factor(1000.0) == 1.0
    # At 2500m (Timmelsjoch / Kühtai / Giau): ~88-90% aerobic availability
    alt_2500 = opt.get_altitude_factor(2500.0)
    assert 0.86 <= alt_2500 <= 0.91

    # At equal mechanical power (250W) on flat road, thinner air at 2500m yields higher velocity
    v_sea = opt._solve_velocity(250, 0.0, elevation_m=200.0)
    v_high = opt._solve_velocity(250, 0.0, elevation_m=2500.0)
    assert v_high > v_sea


def test_muscular_durability_and_marathon_climb_saturation(sample_gpx_path):
    """Verify that on an Alpine marathon (Ötztaler), climb power is aerobically capped and effective FTP reflects altitude & kJ durability."""
    if os.path.exists(sample_gpx_path):
        opt = AdvancedPacingOptimizer(
            initial_ftp=300, target_factor=0.75, rider_weight=80.0, bike_weight=12.0,
            lowest_gear_ratio=33.0 / 36.0, min_climb_cadence=75.0
        )
        df_route = opt.parse_gpx(sample_gpx_path, auto_fetch_elevation=False)
        df_raw = opt.generate_raw_pacing_dataframe(df_route)

        assert 'effective_ftp_pct' in df_raw.columns
        # Late in the race on high passes, effective FTP must be noticeably below 100%
        assert df_raw['effective_ftp_pct'].min() < 90.0

        # Average climb power (>5% slope) should be realistic (~225-260W for 300W FTP at 0.75 TF), not >285W
        climbs = df_raw[df_raw['slope'] >= 5.0]
        avg_climb_w = (climbs['target_power'] * climbs['duration_sec']).sum() / climbs['duration_sec'].sum()
        assert 215.0 <= avg_climb_w <= 265.0


def test_gut_absorption_ceiling_and_electrolyte_alerts(sample_gpx_path):
    """Verify gut absorption decay over time/altitude and ELECTROLYTE_SOUP notifications after 3.5h."""
    opt_overload = AdvancedPacingOptimizer(
        initial_ftp=300, target_factor=0.80, carb_intake_per_hour=115
    )
    # Fresh at 500m: ~95 g/h ceiling; after 6h at 2200m: <75 g/h ceiling
    assert opt_overload.get_max_carb_absorption(elapsed_hours=1.0, elevation_m=500.0) == pytest.approx(95.0)
    late_high_abs = opt_overload.get_max_carb_absorption(elapsed_hours=6.5, elevation_m=2200.0)
    assert late_high_abs < 75.0

    if os.path.exists(sample_gpx_path):
        df_route = opt_overload.parse_gpx(sample_gpx_path, auto_fetch_elevation=False)
        df_raw = opt_overload.generate_raw_pacing_dataframe(df_route)

        # Excessive carb intake (115 g/h) over an 8h marathon must accumulate gut_excess_g
        assert df_raw['gut_excess_g'].max() > 50.0

        # Must trigger ELECTROLYTE_SOUP reset alerts in the second half of the race
        notifs = [n for n in df_raw['notification'] if isinstance(n, dict)]
        soup_notifs = [n for n in notifs if n.get("type") == "ELECTROLYTE_SOUP"]
        assert len(soup_notifs) >= 2

