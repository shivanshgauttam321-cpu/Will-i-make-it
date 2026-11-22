"""
Graph Synchronization Engine
============================
Coordinates between the Transactional Outbox (SQLite) and Neo4j Aura.
Provides idempotent dispatch, retry mechanisms, and synchronization health monitoring.
"""
from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from app.services.outbox_service import (
    get_pending_events,
    mark_event_processing,
    mark_event_success,
    mark_event_failed,
    retry_event,
    get_outbox_stats,
    get_outbox_events,
)
from app.services.neo4j_service import (
    is_enabled as neo4j_enabled,
    is_connected as neo4j_connected,
    check_health as neo4j_health,
    sync_entity_to_graph,
    get_graph_statistics,
    get_graph_elements,
    get_node_by_id,
    purge_demo_graph,
)

logger = logging.getLogger(__name__)

_last_sync_timestamp: Optional[str] = None
_last_sync_error: Optional[str] = None


def get_last_sync_time() -> Optional[str]:
    return _last_sync_timestamp


def process_outbox_batch(limit: int = 25) -> Dict[str, Any]:
    """
    Process a batch of pending/retriable outbox synchronization events.
    Safe against offline or unreachable Neo4j clusters.
    """
    global _last_sync_timestamp, _last_sync_error

    events = get_pending_events(limit=limit)
    if not events:
        return {"processed": 0, "succeeded": 0, "failed": 0, "status": "IDLE"}

    # Check if Neo4j is enabled
    if not neo4j_enabled():
        _last_sync_error = "Neo4j is disabled (NEO4J_ENABLED=false)"
        for ev in events:
            # When disabled, mark as FAILED with friendly message so it doesn't burn out retries endlessly
            mark_event_failed(ev["event_id"], "Neo4j is disabled (NEO4J_ENABLED=false). Events held safely in primary outbox.", max_retries=999)
        return {
            "processed": len(events),
            "succeeded": 0,
            "failed": len(events),
            "status": "DISABLED",
            "message": "Neo4j disabled via configuration; events retained in SQLite outbox.",
        }

    succeeded = 0
    failed = 0

    for ev in events:
        eid = ev["event_id"]
        mark_event_processing(eid)
        try:
            sync_entity_to_graph(ev["payload"], ev["operation"])
            mark_event_success(eid)
            succeeded += 1
            _last_sync_timestamp = datetime.now(timezone.utc).isoformat()
            _last_sync_error = None
        except Exception as e:
            err_msg = str(e)
            mark_event_failed(eid, err_msg, max_retries=ev.get("max_retries", 5))
            failed += 1
            _last_sync_error = err_msg
            logger.warning(f"[GraphSync] Event {eid} failed: {err_msg}")

    return {
        "processed": len(events),
        "succeeded": succeeded,
        "failed": failed,
        "status": "COMPLETED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def retry_single_event(event_id: str) -> Dict[str, Any]:
    """Manually reset a failed outbox event and immediately trigger processing."""
    requeued = retry_event(event_id)
    if not requeued:
        return {"success": False, "message": f"Event '{event_id}' not found"}

    # Process immediately
    batch_res = process_outbox_batch(limit=5)
    return {
        "success": True,
        "event_id": event_id,
        "batch_result": batch_res,
        "message": f"Event '{event_id}' requeued and dispatched",
    }


def get_sync_health_overview() -> Dict[str, Any]:
    """Aggregate health and synchronization metrics for the Graph Monitor dashboard."""
    outbox_stats = get_outbox_stats()
    n_health = neo4j_health()

    status = "CONNECTED" if n_health.get("connected") else n_health.get("status", "DISCONNECTED")
    if status == "UP":
        status = "CONNECTED"

    return {
        "status": status,
        "database": n_health.get("database", "neo4j"),
        "neo4j_enabled": neo4j_enabled(),
        "neo4j_connected": n_health.get("connected", False),
        "neo4j_diagnostic": n_health.get("message", ""),
        "last_sync_time": _last_sync_timestamp,
        "last_sync_error": _last_sync_error,
        "outbox_statistics": outbox_stats,
        "worker_health": "RUNNING",
    }
