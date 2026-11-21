"""
Unit and Mocked Integration Tests for Hardened Neo4j Graph Service.
Verifies safety defaults, strict TLS policies, provenance tracking,
and origin/destination boundary arbitration without live Neo4j dependencies.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

from app.services.neo4j_service import (
    is_enabled, close_driver, get_driver, seed_graph, plan_with_neo4j, is_connected
)
from app.models.schemas import RoutePlanRequest, VehicleProfile


def test_neo4j_disabled_by_default(monkeypatch):
    """Verify that Neo4j integration is disabled by default."""
    monkeypatch.delenv("NEO4J_ENABLED", raising=False)
    assert not is_enabled()
    driver = get_driver()
    assert driver is None
    assert not is_connected()


def test_neo4j_enabled_flag(monkeypatch):
    """Verify is_enabled truthy parsing."""
    monkeypatch.setenv("NEO4J_ENABLED", "true")
    assert is_enabled()
    monkeypatch.setenv("NEO4J_ENABLED", "1")
    assert is_enabled()
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    assert not is_enabled()


def test_close_driver_safety():
    """Verify close_driver is safe when called multiple times or when driver is None."""
    close_driver()
    assert not is_connected()
    close_driver()


def test_plan_with_neo4j_returns_none_when_disabled(monkeypatch):
    """When disabled, plan_with_neo4j must return None immediately."""
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    req = RoutePlanRequest(
        origin_lat=18.5204, origin_lng=73.8567,
        dest_lat=19.0760, dest_lng=72.8777,
        demo_route_id="MUMBAI_PUNE",
        vehicle=VehicleProfile(battery_capacity_kwh=40.0),
    )
    res = plan_with_neo4j(req)
    assert res is None


def test_plan_with_neo4j_does_not_silently_default_to_mumbai_pune(monkeypatch):
    """Arbitrary coordinates without matching graph nodes must return None, NOT silently default to Mumbai-Pune."""
    monkeypatch.setenv("NEO4J_ENABLED", "true")
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    # Mock query returning no match for origin/dest
    mock_session.run.return_value.single.return_value = None

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        req = RoutePlanRequest(
            origin_lat=28.6139, origin_lng=77.2090,  # Delhi
            dest_lat=26.9124, dest_lng=75.7873,  # Jaipur
            demo_route_id=None,
            vehicle=VehicleProfile(battery_capacity_kwh=40.0),
        )
        res = plan_with_neo4j(req)
        assert res is None, "Must not silently route Delhi-Jaipur as Mumbai-Pune"


def test_seed_graph_includes_charger_provenance(monkeypatch):
    """Verify that seed_graph sets provenance metadata properties on Charger nodes."""
    monkeypatch.setenv("NEO4J_ENABLED", "true")
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        success = seed_graph()
        assert success

        # Check that session.run was called with provenance parameters
        charger_runs = [
            call for call in mock_session.run.call_args_list
            if "MERGE (ch:Charger" in str(call)
        ]
        assert len(charger_runs) > 0
        first_call_kwargs = charger_runs[0].kwargs
        assert "status" in first_call_kwargs
        assert "data_source" in first_call_kwargs
        assert "verification_source" in first_call_kwargs


def test_neo4j_health_check_disabled(monkeypatch):
    """Verify health check reports DISABLED cleanly when disabled."""
    from app.services.neo4j_service import check_health
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    health = check_health()
    assert health["status"] == "DISABLED"
    assert not health["connected"]


def test_neo4j_health_check_connected(monkeypatch):
    """Verify health check reports UP when driver is connected and ping succeeds."""
    from app.services.neo4j_service import check_health
    monkeypatch.setenv("NEO4J_ENABLED", "true")
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://demo.databases.neo4j.io")
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_record = {"ping": 1}
    mock_session.run.return_value.single.return_value = mock_record

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        health = check_health()
        assert health["status"] == "UP"
        assert health["connected"]
        assert "demo.databases.neo4j.io" in health["uri"]


def test_init_schema_creates_constraints_and_indexes(monkeypatch):
    """Verify init_schema issues expected DDL statements."""
    from app.services.neo4j_service import init_schema
    monkeypatch.setenv("NEO4J_ENABLED", "true")
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        ok = init_schema()
        assert ok
        ddl_calls = [str(c) for c in mock_session.run.call_args_list]
        assert any("CONSTRAINT road_node_id" in c for c in ddl_calls)
        assert any("CONSTRAINT charger_station_id" in c for c in ddl_calls)
        assert any("INDEX road_node_coords" in c for c in ddl_calls)


def test_find_graph_route_extracts_segments(monkeypatch):
    """Verify find_graph_route queries and formats sequenced segments."""
    from app.services.neo4j_service import find_graph_route
    monkeypatch.setenv("NEO4J_ENABLED", "true")
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    # Mock segment records
    mock_seg_records = [
        {
            "segment_id": "MP_01",
            "distance_km": 45.0,
            "avg_speed_kmh": 40.0,
            "gradient_pct": 0.0,
            "road_type": "urban",
            "name": "Mumbai Urban",
        }
    ]
    mock_charger_records = [
        {
            "charger_id": "CHR_01",
            "name": "Station 1",
            "lat": 18.7,
            "lng": 73.4,
            "max_power_kw": 50.0,
            "connector_types": ["CCS2"],
            "operator": "Tata Power",
            "reliability_score": 0.85,
            "status": "DEMO_SEED",
            "data_source": "DEMO_DATABASE",
            "verification_source": "Demo seed data",
            "last_verified_at": None,
        }
    ]
    mock_session.run.side_effect = [mock_seg_records, mock_charger_records]

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        route = find_graph_route(19.076, 72.877, 18.520, 73.856, corridor_hint="MUMBAI_PUNE")
        assert route is not None
        assert route["route_id"] == "MUMBAI_PUNE"
        assert len(route["segments"]) == 1
        assert route["segments"][0].segment_id == "MP_01"
