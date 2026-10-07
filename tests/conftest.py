import os
import pytest

@pytest.fixture(autouse=True)
def isolate_power_planner_settings(tmp_path, monkeypatch):
    """Ensure every test runs with an isolated, clean settings environment."""
    test_settings_file = str(tmp_path / "test_power_planner_settings.json")
    monkeypatch.setenv("POWER_PLANNER_SETTINGS_FILE", test_settings_file)
    yield test_settings_file
