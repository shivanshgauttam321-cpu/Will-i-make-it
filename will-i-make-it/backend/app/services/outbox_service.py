"""
Transactional Outbox Service
============================
Provides reliable, atomic transactional outbox persistence in SQLite for all
application entities (ChargingStation, City, Operator, RoadSegment, etc.).
Guarantees:
- Primary DB is the single source of truth.
- Zero outbox event creation if the primary DB transaction fails.
- Idempotent event processing and retry mechanisms.
- Clean separation of DEMO vs PROD records and honest provenance classification.
"""
from __future__ import annotations

import sqlite3
import json
import uuid
import os
import re
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

from app.services.charger_service import get_db_path

logger = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_outbox_db() -> None:
    """Initialize SQLite tables for entities, relationships, and transactional outbox."""
    conn = _get_conn()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_entities (
                entity_id       TEXT PRIMARY KEY,
                entity_type     TEXT NOT NULL,
                name            TEXT NOT NULL,
                properties_json TEXT NOT NULL,
                provenance      TEXT NOT NULL DEFAULT 'SIMULATED',
                environment     TEXT NOT NULL DEFAULT 'DEMO',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_relationships (
                rel_id          TEXT PRIMARY KEY,
                from_entity_id  TEXT NOT NULL,
                to_entity_id    TEXT NOT NULL,
                rel_type        TEXT NOT NULL,
                properties_json TEXT NOT NULL DEFAULT '{}',
                created_at      TEXT NOT NULL,
                FOREIGN KEY (from_entity_id) REFERENCES app_entities(entity_id) ON DELETE CASCADE,
                FOREIGN KEY (to_entity_id) REFERENCES app_entities(entity_id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outbox_events (
                event_id        TEXT PRIMARY KEY,
                entity_id       TEXT NOT NULL,
                entity_type     TEXT NOT NULL,
                operation       TEXT NOT NULL,  -- CREATE, UPDATE, DELETE
                payload_json    TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, SUCCESS, FAILED, DEAD_LETTER
                retry_count     INTEGER NOT NULL DEFAULT 0,
                max_retries     INTEGER NOT NULL DEFAULT 5,
                last_attempt_at TEXT,
                last_error      TEXT,
                created_at      TEXT NOT NULL,
                processed_at    TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events(status, retry_count)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON app_entities(entity_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_env ON app_entities(environment)")
    conn.close()
    logger.info("[Outbox] SQLite entity and outbox tables verified.")


def save_entity(
    entity_type: str,
    entity_id: str,
    name: str,
    properties: Dict[str, Any],
    relationships: Optional[List[Dict[str, Any]]] = None,
    provenance: str = "SIMULATED",
    environment: str = "DEMO",
) -> Tuple[Dict[str, Any], str]:
    """
    Atomically save or update an entity in the primary SQLite DB and record
    a synchronization event in the outbox.
    Returns (entity_dict, event_id).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    with conn:
        # Check if entity already exists
        existing = conn.execute(
            "SELECT entity_id, properties_json, created_at FROM app_entities WHERE entity_id = ?",
            (entity_id,)
        ).fetchone()

        operation = "UPDATE" if existing else "CREATE"
        created_at = existing["created_at"] if existing else now_iso

        # Merge existing properties on update if needed
        merged_props = dict(properties)
        merged_props["name"] = name
        merged_props["provenance"] = provenance
        merged_props["environment"] = environment

        conn.execute("""
            INSERT INTO app_entities (entity_id, entity_type, name, properties_json, provenance, environment, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                entity_type = excluded.entity_type,
                name = excluded.name,
                properties_json = excluded.properties_json,
                provenance = excluded.provenance,
                environment = excluded.environment,
                updated_at = excluded.updated_at
        """, (entity_id, entity_type, name, json.dumps(merged_props), provenance, environment, created_at, now_iso))

        # Handle relationships if supplied
        if relationships is not None:
            # Reconcile: delete existing outbound relationships for this entity and recreate
            conn.execute("DELETE FROM app_relationships WHERE from_entity_id = ?", (entity_id,))
            for rel in relationships:
                to_id = rel.get("to_id")
                rel_type = rel.get("type")
                if to_id and rel_type:
                    rel_id = f"rel_{entity_id}_{rel_type}_{to_id}"
                    rprops = json.dumps(rel.get("properties", {}))
                    conn.execute("""
                        INSERT OR REPLACE INTO app_relationships (rel_id, from_entity_id, to_entity_id, rel_type, properties_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (rel_id, entity_id, to_id, rel_type, rprops, now_iso))

        # Create transactional outbox event
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        event_payload = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "name": name,
            "properties": merged_props,
            "relationships": relationships or [],
            "provenance": provenance,
            "environment": environment,
        }

        conn.execute("""
            INSERT INTO outbox_events (event_id, entity_id, entity_type, operation, payload_json, status, retry_count, max_retries, created_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING', 0, 5, ?)
        """, (event_id, entity_id, entity_type, operation, json.dumps(event_payload), now_iso))

    conn.close()
    logger.info(f"[Outbox] Atomically committed {operation} entity '{entity_id}' with outbox event '{event_id}'")
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "name": name,
        "properties": merged_props,
        "provenance": provenance,
        "environment": environment,
        "created_at": created_at,
        "updated_at": now_iso,
    }, event_id


def delete_entity(entity_type: str, entity_id: str) -> Optional[str]:
    """
    Atomically delete an entity from the primary DB and record a DELETE event in the outbox.
    Returns event_id, or None if entity did not exist.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    event_id = None
    try:
        with conn:
            existing = conn.execute("SELECT entity_id, name FROM app_entities WHERE entity_id = ?", (entity_id,)).fetchone()
            if not existing:
                return None

            conn.execute("DELETE FROM app_relationships WHERE from_entity_id = ? OR to_entity_id = ?", (entity_id, entity_id))
            conn.execute("DELETE FROM app_entities WHERE entity_id = ?", (entity_id,))

            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            payload = {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "name": existing["name"]
            }
            conn.execute("""
                INSERT INTO outbox_events (event_id, entity_id, entity_type, operation, payload_json, status, retry_count, max_retries, created_at)
                VALUES (?, ?, ?, 'DELETE', ?, 'PENDING', 0, 5, ?)
            """, (event_id, entity_id, entity_type, json.dumps(payload), now_iso))
    finally:
        conn.close()

    logger.info(f"[Outbox] Atomically deleted entity '{entity_id}' with outbox event '{event_id}'")
    return event_id


def get_pending_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve pending or failed events eligible for retry."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT event_id, entity_id, entity_type, operation, payload_json, status,
               retry_count, max_retries, last_attempt_at, last_error, created_at, processed_at
        FROM outbox_events
        WHERE status IN ('PENDING', 'FAILED') AND retry_count < max_retries
        ORDER BY created_at ASC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    events = []
    for r in rows:
        events.append({
            "event_id": r["event_id"],
            "entity_id": r["entity_id"],
            "entity_type": r["entity_type"],
            "operation": r["operation"],
            "payload": json.loads(r["payload_json"]),
            "status": r["status"],
            "retry_count": r["retry_count"],
            "max_retries": r["max_retries"],
            "last_attempt_at": r["last_attempt_at"],
            "last_error": r["last_error"],
            "created_at": r["created_at"],
            "processed_at": r["processed_at"],
        })
    return events


def mark_event_processing(event_id: str) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    with conn:
        conn.execute("""
            UPDATE outbox_events
            SET status = 'PROCESSING', last_attempt_at = ?
            WHERE event_id = ?
        """, (now_iso, event_id))
    conn.close()


def mark_event_success(event_id: str) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    with conn:
        conn.execute("""
            UPDATE outbox_events
            SET status = 'SUCCESS', processed_at = ?, last_error = NULL
            WHERE event_id = ?
        """, (now_iso, event_id))
    conn.close()


def mark_event_failed(event_id: str, error_message: str, max_retries: int = 5) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    with conn:
        curr = conn.execute("SELECT retry_count FROM outbox_events WHERE event_id = ?", (event_id,)).fetchone()
        count = (curr["retry_count"] if curr else 0) + 1
        new_status = "DEAD_LETTER" if count >= max_retries else "FAILED"

        # Sanitize error message to ensure no credentials or raw tokens leak
        clean_error = re.sub(r'(?i)(password|token|secret|key|authorization)\s*[:=]\s*(?:Bearer\s+)?\S+', r'\1=****', error_message)
        clean_error = re.sub(r'(?i)Bearer\s+\S+', 'Bearer ****', clean_error)
        clean_error = clean_error.replace("password", "****").replace("token", "****")
        if len(clean_error) > 400:
            clean_error = clean_error[:397] + "..."

        conn.execute("""
            UPDATE outbox_events
            SET status = ?, retry_count = ?, last_attempt_at = ?, last_error = ?
            WHERE event_id = ?
        """, (new_status, count, now_iso, clean_error, event_id))
    conn.close()


def retry_event(event_id: str) -> bool:
    """Reset an event to PENDING for manual administrative retry."""
    conn = _get_conn()
    with conn:
        res = conn.execute("""
            UPDATE outbox_events
            SET status = 'PENDING', last_error = 'Queued for manual retry'
            WHERE event_id = ?
        """, (event_id,))
        updated = res.rowcount > 0
    conn.close()
    return updated


def get_outbox_events(limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve outbox events with optional status filtering for dashboard."""
    conn = _get_conn()
    if status:
        rows = conn.execute("""
            SELECT event_id, entity_id, entity_type, operation, payload_json, status,
                   retry_count, max_retries, last_attempt_at, last_error, created_at, processed_at
            FROM outbox_events
            WHERE status = ?
            ORDER BY rowid DESC
            LIMIT ?
        """, (status.upper(), limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT event_id, entity_id, entity_type, operation, payload_json, status,
                   retry_count, max_retries, last_attempt_at, last_error, created_at, processed_at
            FROM outbox_events
            ORDER BY rowid DESC
            LIMIT ?
        """, (limit,)).fetchall()
    conn.close()

    events = []
    for r in rows:
        events.append({
            "event_id": r["event_id"],
            "entity_id": r["entity_id"],
            "entity_type": r["entity_type"],
            "operation": r["operation"],
            "payload": json.loads(r["payload_json"]),
            "status": r["status"],
            "retry_count": r["retry_count"],
            "max_retries": r["max_retries"],
            "last_attempt_at": r["last_attempt_at"],
            "last_error": r["last_error"],
            "created_at": r["created_at"],
            "processed_at": r["processed_at"],
        })
    return events


def get_outbox_stats() -> Dict[str, Any]:
    """Return count statistics for all outbox event statuses."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT status, COUNT(*) as cnt
        FROM outbox_events
        GROUP BY status
    """).fetchall()

    total = conn.execute("SELECT COUNT(*) as total FROM outbox_events").fetchone()["total"]
    entities_count = conn.execute("SELECT COUNT(*) as cnt FROM app_entities").fetchone()["cnt"]
    conn.close()

    counts = {r["status"]: r["cnt"] for r in rows}
    return {
        "total_events": total,
        "pending": counts.get("PENDING", 0),
        "processing": counts.get("PROCESSING", 0),
        "success": counts.get("SUCCESS", 0),
        "failed": counts.get("FAILED", 0),
        "dead_letter": counts.get("DEAD_LETTER", 0),
        "entities_in_primary_db": entities_count,
    }


def cleanup_demo_records() -> Dict[str, int]:
    """Clean up only records where environment = 'DEMO'."""
    conn = _get_conn()
    with conn:
        # Find demo entity IDs
        demo_ids = [r["entity_id"] for r in conn.execute("SELECT entity_id FROM app_entities WHERE environment = 'DEMO'").fetchall()]
        
        rel_deleted = 0
        if demo_ids:
            placeholders = ",".join("?" for _ in demo_ids)
            del_rels = conn.execute(f"DELETE FROM app_relationships WHERE from_entity_id IN ({placeholders}) OR to_entity_id IN ({placeholders})", demo_ids + demo_ids)
            rel_deleted = del_rels.rowcount

        del_entities = conn.execute("DELETE FROM app_entities WHERE environment = 'DEMO'")
        ent_deleted = del_entities.rowcount

        # Mark any remaining demo outbox events as PROCESSED / clean
        del_events = conn.execute("DELETE FROM outbox_events WHERE payload_json LIKE '%\"environment\": \"DEMO\"%' OR payload_json LIKE '%\"environment\":\"DEMO\"%'")
        events_deleted = del_events.rowcount

    conn.close()
    return {
        "entities_deleted": ent_deleted,
        "relationships_deleted": rel_deleted,
        "events_cleaned": events_deleted,
    }
