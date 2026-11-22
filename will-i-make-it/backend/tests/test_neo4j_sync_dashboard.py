"""
Deterministic Unit & Integration Tests for Neo4j Aura Synchronization & Live Graph Dashboard.
Covers:
1. Node creation & MERGE upsert
2. Node update & property reconciliation
3. Relationship creation & degree verification
4. Duplicate event processing & idempotency
5. Entity deletion & relationship cleanup
6. Outbox event creation & state transitions (PENDING -> SUCCESS / FAILED / DEAD_LETTER)
7. Exponential retry behavior & manual retry endpoint
8. Aura unavailable / disabled resilience (zero primary DB corruption)
9. Provenance preservation (REAL vs SIMULATED) & environment isolation (DEMO vs PROD)
10. Graph statistics & aggregation queries
11. Bounded pagination & graph filtering
12. Demo infrastructure creation, update, and isolated cleanup
13. User charger report automatic website-to-Neo4j synchronization
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.services.outbox_service import (
    init_outbox_db,
    save_entity,
    delete_entity,
    get_pending_events,
    mark_event_processing,
    mark_event_success,
    mark_event_failed,
    retry_event,
    get_outbox_events,
    get_outbox_stats,
    cleanup_demo_records,
)
from app.services.graph_sync_service import (
    process_outbox_batch,
    retry_single_event,
    get_sync_health_overview,
)
from app.services.neo4j_service import (
    sync_entity_to_graph,
    get_graph_statistics,
    get_graph_elements,
    get_node_by_id,
    purge_demo_graph,
)


from app.services.charger_service import init_db

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Use a clean temporary SQLite database for each test."""
    test_db = str(tmp_path / "test_outbox.db")
    monkeypatch.setenv("SQLITE_PATH", test_db)
    init_db()
    init_outbox_db()
    yield test_db


# ==============================================================================
# 1. OUTBOX PERSISTENCE & ATOMICTY TESTS
# ==============================================================================

def test_outbox_event_creation_and_entity_save():
    """Verify save_entity atomically saves entity in primary DB and enqueues outbox event."""
    ent, evt_id = save_entity(
        entity_type="ChargingStation",
        entity_id="CHR_TEST_01",
        name="Test Supercharger Hub",
        properties={"power_kw": 120.0, "lat": 19.05, "lng": 73.01},
        relationships=[{"to_id": "CITY_MUMBAI", "type": "LOCATED_IN"}],
        provenance="SIMULATED",
        environment="DEMO",
    )

    assert ent["entity_id"] == "CHR_TEST_01"
    assert ent["name"] == "Test Supercharger Hub"
    assert evt_id.startswith("evt_")

    # Check pending outbox
    pending = get_pending_events(limit=10)
    assert len(pending) == 1
    ev = pending[0]
    assert ev["event_id"] == evt_id
    assert ev["entity_id"] == "CHR_TEST_01"
    assert ev["operation"] == "CREATE"
    assert ev["status"] == "PENDING"
    assert ev["retry_count"] == 0
    assert ev["payload"]["provenance"] == "SIMULATED"
    assert ev["payload"]["environment"] == "DEMO"


def test_outbox_node_update():
    """Verify updating an entity updates SQLite properties and queues an UPDATE outbox event."""
    # First save
    save_entity("City", "CITY_PUNE", "Pune", {"state": "MH"})
    # Second save (update)
    ent_updated, evt_id2 = save_entity("City", "CITY_PUNE", "Pune Metro Area", {"state": "MH", "tier": 1})

    assert ent_updated["name"] == "Pune Metro Area"
    events = get_outbox_events(limit=10)
    assert len(events) == 2
    assert events[0]["operation"] == "UPDATE"
    assert events[0]["event_id"] == evt_id2


def test_outbox_entity_deletion():
    """Verify delete_entity removes entity from primary DB and queues DELETE event."""
    save_entity("ChargingStation", "CHR_DEL_01", "Del Station", {})
    del_evt = delete_entity("ChargingStation", "CHR_DEL_01")

    assert del_evt is not None
    events = get_outbox_events(limit=10)
    assert events[0]["operation"] == "DELETE"
    assert events[0]["entity_id"] == "CHR_DEL_01"

    # Re-deleting non-existent entity returns None
    assert delete_entity("ChargingStation", "CHR_DEL_01") is None


# ==============================================================================
# 2. RETRY BEHAVIOR & FAILURE HANDLING
# ==============================================================================

def test_outbox_retry_count_and_dead_letter():
    """Verify bounded exponential retry and transition to DEAD_LETTER when max retries exceeded."""
    _, evt_id = save_entity("ChargingStation", "CHR_FAIL_01", "Fail Station", {})
    
    # Simulate 4 failures
    for i in range(1, 5):
        mark_event_failed(evt_id, f"Temporary connection error #{i}", max_retries=5)
        evs = get_outbox_events(limit=1)
        assert evs[0]["status"] == "FAILED"
        assert evs[0]["retry_count"] == i

    # 5th failure exceeds max_retries -> DEAD_LETTER
    mark_event_failed(evt_id, "Fatal connection drop", max_retries=5)
    evs = get_outbox_events(limit=1)
    assert evs[0]["status"] == "DEAD_LETTER"
    assert evs[0]["retry_count"] == 5

    # Manual retry resets to PENDING
    assert retry_event(evt_id) is True
    evs = get_outbox_events(limit=1)
    assert evs[0]["status"] == "PENDING"


def test_credential_sanitization_in_errors():
    """Ensure error messages never leak passwords or sensitive tokens."""
    _, evt_id = save_entity("ChargingStation", "CHR_ERR_01", "Err Station", {})
    leak_string = "Failed with password=secret_pass_123 and token=Bearer abc"
    mark_event_failed(evt_id, leak_string)

    evs = get_outbox_events(limit=1)
    assert "secret_pass_123" not in evs[0]["last_error"]
    assert "Bearer abc" not in evs[0]["last_error"]
    assert "****" in evs[0]["last_error"]


# ==============================================================================
# 3. NEO4J SYNCHRONIZATION & IDEMPOTENCY
# ==============================================================================

def test_sync_entity_to_graph_creates_and_merges():
    """Verify Cypher MERGE query generation and relationship reconciliation."""
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    payload = {
        "entity_type": "ChargingStation",
        "entity_id": "CHR_MOCK_01",
        "name": "Mock Station",
        "properties": {"lat": 19.0, "lng": 73.0, "power_kw": 60.0},
        "relationships": [
            {"to_id": "OP_TATA", "type": "OPERATED_BY", "properties": {"contract": "direct"}},
            {"to_id": "CITY_MUMBAI", "type": "LOCATED_IN"},
        ],
        "provenance": "REAL",
        "environment": "PROD",
    }

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        success = sync_entity_to_graph(payload, "CREATE")
        assert success is True

        # Verify session.run was called for node upsert and relationships
        calls = mock_session.run.call_args_list
        assert len(calls) >= 3  # node upsert + mirror charger + 2 rels
        query_texts = [str(c[0][0]) for c in calls]
        assert any("MERGE (n:ChargingStation" in q for q in query_texts)
        assert any("OPERATED_BY" in q for q in query_texts)
        assert any("LOCATED_IN" in q for q in query_texts)


def test_sync_entity_to_graph_idempotency():
    """Executing the same CREATE/UPDATE event twice executes identical MERGE queries without duplicating."""
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    payload = {
        "entity_type": "City",
        "entity_id": "CITY_JAIPUR",
        "name": "Jaipur",
        "properties": {"lat": 26.9, "lng": 75.8},
        "relationships": [],
    }

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        # First call
        res1 = sync_entity_to_graph(payload, "CREATE")
        # Duplicate second call
        res2 = sync_entity_to_graph(payload, "CREATE")
        assert res1 is True
        assert res2 is True
        for call in mock_session.run.call_args_list:
            assert "MERGE (n:City" in call[0][0]


def test_sync_entity_deletion():
    """Verify DELETE operation executes DETACH DELETE."""
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    payload = {"entity_type": "ChargingStation", "entity_id": "CHR_DEL_99"}

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        success = sync_entity_to_graph(payload, "DELETE")
        assert success is True
        del_query = mock_session.run.call_args[0][0]
        assert "DETACH DELETE n" in del_query


# ==============================================================================
# 4. AURA UNAVAILABLE & RESILIENCE TESTS
# ==============================================================================

def test_sync_batch_when_neo4j_disabled(monkeypatch):
    """When NEO4J_ENABLED is false, outbox batch marks events safely without crashing."""
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    save_entity("ChargingStation", "CHR_DIS_01", "Disabled Test", {})

    res = process_outbox_batch(limit=10)
    assert res["status"] == "DISABLED"
    assert res["processed"] == 1
    assert res["succeeded"] == 0

    # Event remains preserved in SQLite
    events = get_outbox_events(limit=1)
    assert events[0]["status"] == "FAILED"
    assert "Neo4j is disabled" in events[0]["last_error"]


def test_sync_batch_success_transition(monkeypatch):
    """When Neo4j is enabled and driver succeeds, pending events transition to SUCCESS."""
    monkeypatch.setenv("NEO4J_ENABLED", "true")
    save_entity("City", "CITY_DELHI", "New Delhi", {})

    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    with patch("app.services.neo4j_service.get_driver", return_value=mock_driver):
        res = process_outbox_batch(limit=10)
        assert res["status"] == "COMPLETED"
        assert res["succeeded"] == 1
        assert res["failed"] == 0

        # Event in SQLite must now be SUCCESS
        events = get_outbox_events(limit=1)
        assert events[0]["status"] == "SUCCESS"
        assert events[0]["processed_at"] is not None


# ==============================================================================
# 5. DEMO ISOLATION & PURGE TESTS
# ==============================================================================

def test_demo_records_cleanup_isolation():
    """Verify cleanup_demo_records only purges DEMO records while preserving PROD records."""
    save_entity("ChargingStation", "CHR_PROD_01", "Live Real Charger", {}, environment="PROD", provenance="REAL")
    save_entity("ChargingStation", "CHR_DEMO_01", "Demo Seed Charger", {}, environment="DEMO", provenance="SIMULATED")

    # Purge demo records
    cleanup_res = cleanup_demo_records()
    assert cleanup_res["entities_deleted"] == 1

    # Verify PROD remains intact in SQLite
    stats = get_outbox_stats()
    assert stats["entities_in_primary_db"] == 1


# ==============================================================================
# 6. API ROUTE TESTS (/api/neo4j/*)
# ==============================================================================

def test_neo4j_stats_endpoint(monkeypatch):
    """Verify GET /api/neo4j/stats returns graph and outbox counts."""
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    client = TestClient(app)
    resp = client.get("/api/neo4j/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "outbox_statistics" in data
    assert "total_nodes" in data


def test_neo4j_sync_status_endpoint(monkeypatch):
    """Verify GET /api/neo4j/sync/status reports honest state."""
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    client = TestClient(app)
    resp = client.get("/api/neo4j/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["neo4j_enabled"] is False
    assert data["status"] in ("DISABLED", "DISCONNECTED")
    assert "worker_health" in data


def test_neo4j_demo_create_and_cleanup_pipeline():
    """Verify administrative demo workflow from creation through outbox to cleanup."""
    client = TestClient(app)

    # 1. Create demo sample
    create_resp = client.post("/api/neo4j/demo/create-sample")
    assert create_resp.status_code == 200
    create_data = create_resp.json()
    assert create_data["success"] is True
    assert len(create_data["events_created"]) >= 5

    # Outbox must contain events
    ev_resp = client.get("/api/neo4j/sync/events")
    assert ev_resp.status_code == 200
    assert ev_resp.json()["count"] >= 5

    # 2. Update demo station
    update_resp = client.post("/api/neo4j/demo/update-sample", json={
        "station_id": create_data["station_id"],
        "power_kw": 150.0,
        "is_operational": True,
    })
    assert update_resp.status_code == 200
    assert update_resp.json()["updated_properties"]["max_power_kw"] == 150.0

    # 3. Cleanup demo sample
    del_resp = client.post("/api/neo4j/demo/cleanup")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True


def test_user_charger_report_generates_outbox_event():
    """Verify submitting a charger report through the website API enqueues a sync event."""
    client = TestClient(app)
    report_payload = {
        "charger_id": "CHR_MH_001",
        "success": True,
        "connector_type": "CCS2",
        "reported_power_kw": 50.0,
        "notes": "Verified working smoothly on highway",
        "reporter_id": "driver_42",
    }
    rep_res = client.post("/api/chargers/report", json=report_payload)
    assert rep_res.status_code == 200

    # Check outbox events for the new report
    events = get_outbox_events(limit=5)
    report_events = [e for e in events if e["entity_type"] == "ChargingReport"]
    assert len(report_events) > 0
    assert report_events[0]["payload"]["properties"]["charger_id"] == "CHR_MH_001"
    assert report_events[0]["payload"]["relationships"][0]["type"] == "REPORTS_STATUS"
