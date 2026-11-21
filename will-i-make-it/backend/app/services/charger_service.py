"""
Charger Reliability Service
=============================
Tracks charger operational reports in SQLite and computes a smoothed
reliability score using a Beta-distribution posterior (Laplace smoothing).

RELIABILITY MODEL
-----------------
  posterior_mean = (successes + α) / (total + α + β)
  where α = β = 1.0 (uniform Dirichlet prior → Laplace smoothing)

This gives:
  - Unknown charger (no reports): score = 0.5 (not 1.0 — we are honest)
  - 1 success, 0 failures:         score ≈ 0.67
  - 10/10 successes:                score ≈ 0.92
  - 5/10 successes:                 score ≈ 0.50

FRESHNESS
---------
Reports older than STALE_HOURS are down-weighted by a decay factor:
  weight = exp(-age_hours / HALF_LIFE_HOURS)
No decay for very recent reports; severe staleness pulls score toward 0.5.

IMPORTANT: These scores are computed from demo seed data + user reports.
They do NOT reflect real-world operational status of any real charger.
"""
from __future__ import annotations

import sqlite3
import math
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict
import json

DB_PATH = os.environ.get("SQLITE_PATH", "willimake.db")

ALPHA_PRIOR = 1.0   # pseudo-successes (Laplace smoothing)
BETA_PRIOR = 1.0    # pseudo-failures
HALF_LIFE_HOURS = 48.0   # decay half-life for old reports (aligned with 48h freshness window)
STALE_THRESHOLD_HOURS = 72.0  # after this, freshness indicator is "stale"

_reference_time_override: Optional[datetime] = None


def set_reference_time(ref: Optional[datetime]) -> None:
    """Set global reference time for deterministic testing/simulation. None restores live datetime.now()."""
    global _reference_time_override
    if ref is not None and ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    _reference_time_override = ref


def get_reference_time() -> datetime:
    """Return current UTC time or active test/simulation reference time."""
    if _reference_time_override is not None:
        return _reference_time_override
    return datetime.now(timezone.utc)


def get_db_path() -> str:
    """Dynamically return the active SQLite database path."""
    return os.environ.get("SQLITE_PATH", DB_PATH)


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables and seed initial charger report data."""
    conn = _get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS charger_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            charger_id  TEXT NOT NULL,
            success     INTEGER NOT NULL,  -- 1 = operational, 0 = failed
            connector   TEXT,
            power_kw    REAL,
            notes       TEXT,
            reporter_id TEXT,
            reported_at TEXT NOT NULL  -- ISO8601
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            trip_id         TEXT PRIMARY KEY,
            route_id        TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            actual_kwh      REAL,
            predicted_p50   REAL,
            predicted_p90   REAL,
            within_p90      INTEGER,
            soc_final_pct   REAL,
            vehicle_json    TEXT,
            notes           TEXT
        )
    """)
    conn.commit()

    # Seed some historical reports (simulated — clearly labelled)
    seed_reports = [
        # Reliable chargers
        ("CHR_MH_001", 1, "CCS2", 50.0, "SEED:simulated", "2026-10-28T08:00:00Z"),
        ("CHR_MH_001", 1, "CCS2", 48.0, "SEED:simulated", "2026-10-27T14:00:00Z"),
        ("CHR_MH_001", 1, "Type2_AC", 7.0, "SEED:simulated", "2026-10-26T10:00:00Z"),
        ("CHR_MH_001", 0, "CCS2", None, "SEED:simulated – timeout error", "2026-10-25T16:00:00Z"),
        ("CHR_MH_004", 1, "CCS2", 60.0, "SEED:simulated – fast charge ok", "2026-10-29T11:00:00Z"),
        ("CHR_MH_004", 1, "CCS2", 58.0, "SEED:simulated – fast charge ok", "2026-10-28T16:00:00Z"),
        ("CHR_MH_004", 1, "Type2_AC", 22.0, "SEED:simulated – session ok", "2026-10-27T10:00:00Z"),
        ("CHR_MH_004", 1, "CCS2", 60.0, "SEED:simulated – peak rate ok", "2026-10-26T14:00:00Z"),
        ("CHR_MH_004", 1, "CCS2", 59.0, "SEED:simulated – normal operation", "2026-10-25T09:00:00Z"),
        ("CHR_DL_001", 1, "CCS2", 50.0, "SEED:simulated", "2026-10-29T09:00:00Z"),
        ("CHR_DL_001", 1, "CCS2", 47.0, "SEED:simulated", "2026-10-28T11:00:00Z"),
        ("CHR_DL_001", 1, "Type2_AC", 7.0, "SEED:simulated", "2026-10-27T16:00:00Z"),
        ("CHR_KA_001", 1, "CCS2", 50.0, "SEED:simulated", "2026-10-29T07:00:00Z"),
        ("CHR_KA_001", 0, "CHAdeMO", None, "SEED:simulated – plug jammed", "2026-10-28T15:00:00Z"),
        ("CHR_GJ_001", 1, "CCS2", 60.0, "SEED:simulated", "2026-10-29T10:00:00Z"),
        ("CHR_GJ_001", 1, "CCS2", 58.0, "SEED:simulated", "2026-10-28T12:00:00Z"),
        # Less reliable
        ("CHR_MH_002", 1, "CCS2", 55.0, "SEED:simulated", "2026-10-29T06:00:00Z"),
        ("CHR_MH_002", 0, "CHAdeMO", None, "SEED:simulated – network down", "2026-10-26T09:00:00Z"),
        ("CHR_MH_003", 1, "CCS2", 28.0, "SEED:simulated", "2026-10-27T10:00:00Z"),
        ("CHR_MH_003", 0, "CCS2", None, "SEED:simulated – payment failed", "2026-10-25T14:00:00Z"),
        ("CHR_MH_003", 0, "CCS2", None, "SEED:simulated – offline", "2026-10-22T08:00:00Z"),
        ("CHR_HR_001", 1, "CCS2", 25.0, "SEED:simulated", "2026-10-29T08:30:00Z"),
        ("CHR_HR_001", 1, "Type2_AC", 7.0, "SEED:simulated", "2026-10-28T19:00:00Z"),
        ("CHR_TN_001", 1, "CCS2", 50.0, "SEED:simulated", "2026-10-29T05:00:00Z"),
        ("CHR_TN_001", 1, "Bharat_DC", 14.0, "SEED:simulated", "2026-10-28T07:00:00Z"),
    ]
    # Insert seed reports if missing
    for r in seed_reports:
        c.execute("""
            INSERT INTO charger_reports (charger_id, success, connector, power_kw, notes, reported_at)
            SELECT ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM charger_reports WHERE charger_id = ? AND reported_at = ?
            )
        """, (r[0], r[1], r[2], r[3], r[4], r[5], r[0], r[5]))
    conn.commit()
    conn.close()


def compute_reliability(charger_id: str, as_of: Optional[datetime] = None) -> Dict:
    """
    Compute smoothed reliability score for a charger.
    Accepts an optional reference time `as_of` for deterministic evaluation.
    Returns {'score': float, 'freshness_hours': float|None, 'total_reports': int}
    """
    conn = _get_db()
    rows = conn.execute(
        "SELECT success, reported_at FROM charger_reports WHERE charger_id=? ORDER BY reported_at DESC",
        (charger_id,)
    ).fetchall()
    conn.close()

    if not rows:
        from app.services.demo_data import CHARGERS
        if charger_id in CHARGERS:
            c = CHARGERS[charger_id]
            return {
                "score": c.get("reliability_score", 0.5),
                "freshness_hours": c.get("reliability_freshness_hours"),
                "total_reports": 0,
                "note": "Seed database baseline"
            }
        return {"score": 0.5, "freshness_hours": None, "total_reports": 0,
                "note": "No reports — status unknown (prior = 0.5)"}

    if as_of is None:
        eval_time = get_reference_time()
    else:
        eval_time = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=timezone.utc)

    weighted_successes = ALPHA_PRIOR
    weighted_total = ALPHA_PRIOR + BETA_PRIOR

    freshness_hours = None
    for row in rows:
        reported_at = row["reported_at"]
        if not reported_at:
            age_h = STALE_THRESHOLD_HOURS
        else:
            try:
                clean_ts = reported_at.replace("Z", "+00:00")
                ts = datetime.fromisoformat(clean_ts)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_h = (eval_time - ts).total_seconds() / 3600.0
                if age_h < 0:
                    age_h = 0.0  # clamp future observation to 0 age (weight 1.0)
            except Exception:
                age_h = STALE_THRESHOLD_HOURS

        if freshness_hours is None:
            freshness_hours = age_h

        weight = math.exp(-age_h / (HALF_LIFE_HOURS / math.log(2)))
        weighted_total += weight
        if row["success"]:
            weighted_successes += weight

    score = weighted_successes / weighted_total
    return {
        "score": round(score, 3),
        "freshness_hours": round(freshness_hours, 1) if freshness_hours is not None else None,
        "total_reports": len(rows),
    }


def add_report(charger_id: str, success: bool, connector: str,
               power_kw: Optional[float], notes: Optional[str],
               reporter_id: Optional[str],
               reported_at: Optional[str] = None) -> int:
    """Insert a new charger report. Returns row ID."""
    conn = _get_db()
    if reported_at is None:
        now = datetime.now(timezone.utc).isoformat()
    else:
        now = reported_at
    cur = conn.execute(
        "INSERT INTO charger_reports (charger_id, success, connector, power_kw, notes, reporter_id, reported_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (charger_id, int(success), connector, power_kw, notes, reporter_id, now)
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def save_trip(trip_id: str, route_id: str, actual_kwh: float,
              p50: float, p90: float, soc_final: float,
              vehicle_json: str, notes: str) -> None:
    conn = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    within = int(actual_kwh <= p90)
    conn.execute(
        "INSERT OR REPLACE INTO trips VALUES (?,?,?,?,?,?,?,?,?,?)",
        (trip_id, route_id, now, actual_kwh, p50, p90, within, soc_final, vehicle_json, notes)
    )
    conn.commit()
    conn.close()


def get_trip(trip_id: str) -> Optional[Dict]:
    conn = _get_db()
    row = conn.execute("SELECT * FROM trips WHERE trip_id=?", (trip_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)
