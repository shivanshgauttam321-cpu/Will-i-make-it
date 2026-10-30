"""
Demo Route Data & Charger Database
====================================
Static seed data for the demo — clearly labelled as SIMULATED.
Covers 5 representative Indian EV routes with charging stops.
All coordinates, distances, and charger data are illustrative/approximate.
"""
from __future__ import annotations
from typing import Dict, List, Any
import math

# ─────────────────────────────────────────────────────────────────────────────
# CHARGER DATABASE (simulated)
# ─────────────────────────────────────────────────────────────────────────────
CHARGERS: Dict[str, Dict] = {
    "CHR_MH_001": {
        "charger_id": "CHR_MH_001",
        "name": "Tata Power EV – Pune Kharadi",
        "lat": 18.5512, "lng": 73.9478,
        "connector_types": ["CCS2", "Type2_AC"],
        "max_power_kw": 50.0,
        "operator": "Tata Power",
        "reliability_score": 0.88,
        "reliability_freshness_hours": 3.0,
        "is_operational": True,
        "address": "Kharadi, Pune, Maharashtra",
    },
    "CHR_MH_002": {
        "charger_id": "CHR_MH_002",
        "name": "EESL Fast Charger – Mumbai Worli",
        "lat": 19.0178, "lng": 72.8178,
        "connector_types": ["CCS2", "CHAdeMO"],
        "max_power_kw": 60.0,
        "operator": "EESL",
        "reliability_score": 0.75,
        "reliability_freshness_hours": 18.0,
        "is_operational": True,
        "address": "Worli, Mumbai, Maharashtra",
    },
    "CHR_MH_003": {
        "charger_id": "CHR_MH_003",
        "name": "ChargeZone – Lonavala Highway",
        "lat": 18.7481, "lng": 73.4072,
        "connector_types": ["CCS2", "Type2_AC"],
        "max_power_kw": 30.0,
        "operator": "ChargeZone",
        "reliability_score": 0.62,
        "reliability_freshness_hours": 36.0,
        "is_operational": None,  # Unknown status
        "address": "Khopoli-Khalapur, Lonavala Expressway",
    },
    "CHR_MH_004": {
        "charger_id": "CHR_MH_004",
        "name": "Jio-bp pulse Fast Charger – Urse Toll Plaza",
        "lat": 18.7200, "lng": 73.6100,
        "connector_types": ["CCS2", "Type2_AC"],
        "max_power_kw": 60.0,
        "operator": "Jio-bp",
        "reliability_score": 0.94,
        "reliability_freshness_hours": 1.5,
        "is_operational": True,
        "address": "Urse Expressway Toll Plaza, Talegaon-Urse, Maharashtra",
    },
    "CHR_DL_001": {
        "charger_id": "CHR_DL_001",
        "name": "Fortum Charge – Connaught Place",
        "lat": 28.6315, "lng": 77.2167,
        "connector_types": ["CCS2", "Type2_AC", "CHAdeMO"],
        "max_power_kw": 50.0,
        "operator": "Fortum",
        "reliability_score": 0.91,
        "reliability_freshness_hours": 1.5,
        "is_operational": True,
        "address": "Connaught Place, New Delhi",
    },
    "CHR_DL_002": {
        "charger_id": "CHR_DL_002",
        "name": "DMRC Charger – Dwarka Sector 21",
        "lat": 28.5524, "lng": 77.0688,
        "connector_types": ["Bharat_DC", "Type2_AC"],
        "max_power_kw": 15.0,
        "operator": "DMRC",
        "reliability_score": 0.70,
        "reliability_freshness_hours": 48.0,
        "is_operational": None,
        "address": "Dwarka Sector 21 Metro, Delhi",
    },
    "CHR_HR_001": {
        "charger_id": "CHR_HR_001",
        "name": "Magenta ChargeGrid – Gurugram Cyber Hub",
        "lat": 28.4952, "lng": 77.0882,
        "connector_types": ["CCS2", "Type2_AC"],
        "max_power_kw": 25.0,
        "operator": "Magenta",
        "reliability_score": 0.83,
        "reliability_freshness_hours": 8.0,
        "is_operational": True,
        "address": "DLF Cyber Hub, Gurugram, Haryana",
    },
    "CHR_KA_001": {
        "charger_id": "CHR_KA_001",
        "name": "BESCOM EV Pilot – Bengaluru Indiranagar",
        "lat": 12.9784, "lng": 77.6408,
        "connector_types": ["CCS2", "CHAdeMO", "Type2_AC"],
        "max_power_kw": 50.0,
        "operator": "BESCOM",
        "reliability_score": 0.79,
        "reliability_freshness_hours": 6.0,
        "is_operational": True,
        "address": "100 Feet Road, Indiranagar, Bengaluru",
    },
    "CHR_KA_002": {
        "charger_id": "CHR_KA_002",
        "name": "Zeon Charging – Mysuru Palace",
        "lat": 12.3052, "lng": 76.6551,
        "connector_types": ["CCS2", "Type2_AC"],
        "max_power_kw": 22.0,
        "operator": "Zeon",
        "reliability_score": 0.55,
        "reliability_freshness_hours": 72.0,
        "is_operational": None,
        "address": "Near Mysore Palace, Mysuru, Karnataka",
    },
    "CHR_TN_001": {
        "charger_id": "CHR_TN_001",
        "name": "TANGEDCO EV Hub – Chennai Tidel Park",
        "lat": 12.9940, "lng": 80.2490,
        "connector_types": ["CCS2", "Type2_AC", "Bharat_DC"],
        "max_power_kw": 50.0,
        "operator": "TANGEDCO",
        "reliability_score": 0.86,
        "reliability_freshness_hours": 4.0,
        "is_operational": True,
        "address": "TIDEL Park, OMR, Chennai, Tamil Nadu",
    },
    "CHR_GJ_001": {
        "charger_id": "CHR_GJ_001",
        "name": "TORRENT POWER – Ahmedabad Vastrapur",
        "lat": 23.0395, "lng": 72.5270,
        "connector_types": ["CCS2", "Type2_AC"],
        "max_power_kw": 60.0,
        "operator": "Torrent Power",
        "reliability_score": 0.92,
        "reliability_freshness_hours": 2.0,
        "is_operational": True,
        "address": "Vastrapur Lake, Ahmedabad, Gujarat",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# DEMO ROUTES (simulated)
# ─────────────────────────────────────────────────────────────────────────────
def _seg(sid, name, dist, speed, grad=0.0, rtype="urban"):
    return {
        "segment_id": sid, "name": name,
        "distance_km": dist, "avg_speed_kmh": speed,
        "gradient_pct": grad, "road_type": rtype
    }


DEMO_ROUTES: Dict[str, Dict] = {
    "MUMBAI_PUNE": {
        "route_id": "MUMBAI_PUNE",
        "label": "Mumbai → Pune (Expressway)",
        "description": "148 km via Mumbai-Pune Expressway. Ghats section has significant gradients. [SIMULATED]",
        "origin": {"lat": 19.0760, "lng": 72.8777, "name": "Mumbai"},
        "destination": {"lat": 18.5204, "lng": 73.8567, "name": "Pune"},
        "distance_km": 148.0,
        "duration_min": 130,
        "segments": [
            _seg("MP_01", "Mumbai Urban – Khopoli", 45, 40, 0.0, "urban"),
            _seg("MP_02", "Khopoli – Khandala Ghat (uphill)", 25, 35, 4.5, "rural"),
            _seg("MP_03", "Khandala – Lonavala (flat)", 8, 60, 0.2, "highway"),
            _seg("MP_04", "Lonavala – Pune Expressway", 55, 100, -1.5, "highway"),
            _seg("MP_05", "Pune Urban – Kharadi", 15, 35, 0.0, "urban"),
        ],
        "charger_ids": ["CHR_MH_003", "CHR_MH_004", "CHR_MH_001"],
        "waypoints": [
            {"lat": 19.0760, "lng": 72.8777},
            {"lat": 18.7481, "lng": 73.4072},
            {"lat": 18.7200, "lng": 73.6100},
            {"lat": 18.5512, "lng": 73.9478},
            {"lat": 18.5204, "lng": 73.8567},
        ]
    },
    "DELHI_GURUGRAM": {
        "route_id": "DELHI_GURUGRAM",
        "label": "Delhi → Gurugram (NH48)",
        "description": "32 km urban expressway trip. No charging stop needed. [SIMULATED]",
        "origin": {"lat": 28.6315, "lng": 77.2167, "name": "Connaught Place, Delhi"},
        "destination": {"lat": 28.4595, "lng": 77.0266, "name": "Gurugram"},
        "distance_km": 32.0,
        "duration_min": 55,
        "segments": [
            _seg("DG_01", "CP – AIIMS (Ring Road)", 10, 35, 0.0, "urban"),
            _seg("DG_02", "AIIMS – NH48 Mahipalpur", 8, 60, 0.0, "highway"),
            _seg("DG_03", "Mahipalpur – Gurugram DLF", 14, 70, 0.5, "highway"),
        ],
        "charger_ids": ["CHR_DL_001", "CHR_HR_001"],
        "waypoints": [
            {"lat": 28.6315, "lng": 77.2167},
            {"lat": 28.5355, "lng": 77.1200},
            {"lat": 28.4595, "lng": 77.0266},
        ]
    },
    "BENGALURU_MYSURU": {
        "route_id": "BENGALURU_MYSURU",
        "label": "Bengaluru → Mysuru (NH275)",
        "description": "143 km on NH275. Rolling terrain, moderate gradients. [SIMULATED]",
        "origin": {"lat": 12.9784, "lng": 77.6408, "name": "Indiranagar, Bengaluru"},
        "destination": {"lat": 12.2958, "lng": 76.6394, "name": "Mysuru"},
        "distance_km": 143.0,
        "duration_min": 160,
        "segments": [
            _seg("BM_01", "Bengaluru Urban – Electronic City", 18, 30, 0.0, "urban"),
            _seg("BM_02", "Electronic City – Channapatna", 55, 90, 1.2, "highway"),
            _seg("BM_03", "Channapatna – Maddur", 30, 85, -0.8, "highway"),
            _seg("BM_04", "Maddur – Mandya – Srirangapatna", 30, 80, 0.3, "highway"),
            _seg("BM_05", "Srirangapatna – Mysuru City", 10, 40, 0.0, "urban"),
        ],
        "charger_ids": ["CHR_KA_001", "CHR_KA_002"],
        "waypoints": [
            {"lat": 12.9784, "lng": 77.6408},
            {"lat": 12.6500, "lng": 77.2500},
            {"lat": 12.3052, "lng": 76.6551},
            {"lat": 12.2958, "lng": 76.6394},
        ]
    },
    "DELHI_AGRA": {
        "route_id": "DELHI_AGRA",
        "label": "Delhi → Agra (Yamuna Expressway)",
        "description": "210 km on Yamuna Expressway. Long flat highway – range anxiety test. [SIMULATED]",
        "origin": {"lat": 28.5355, "lng": 77.1200, "name": "Noida, Delhi NCR"},
        "destination": {"lat": 27.1767, "lng": 78.0081, "name": "Agra"},
        "distance_km": 210.0,
        "duration_min": 170,
        "segments": [
            _seg("DA_01", "Noida – Greater Noida", 28, 70, 0.0, "highway"),
            _seg("DA_02", "Greater Noida – Mathura (YE)", 105, 110, 0.0, "highway"),
            _seg("DA_03", "Mathura – Agra (NH19)", 55, 80, 0.0, "highway"),
            _seg("DA_04", "Agra Urban – Taj Mahal Area", 22, 30, 0.0, "urban"),
        ],
        "charger_ids": ["CHR_DL_001", "CHR_DL_002"],
        "waypoints": [
            {"lat": 28.5355, "lng": 77.1200},
            {"lat": 27.7500, "lng": 77.4800},
            {"lat": 27.1767, "lng": 78.0081},
        ]
    },
    "AHMEDABAD_SURAT": {
        "route_id": "AHMEDABAD_SURAT",
        "label": "Ahmedabad → Surat (NH48)",
        "description": "265 km industrial corridor. Flat terrain, good expressway. [SIMULATED]",
        "origin": {"lat": 23.0395, "lng": 72.5270, "name": "Vastrapur, Ahmedabad"},
        "destination": {"lat": 21.1702, "lng": 72.8311, "name": "Surat"},
        "distance_km": 265.0,
        "duration_min": 220,
        "segments": [
            _seg("AS_01", "Ahmedabad Urban", 20, 40, 0.0, "urban"),
            _seg("AS_02", "Ahmedabad – Vadodara (NH48)", 90, 110, 0.0, "highway"),
            _seg("AS_03", "Vadodara – Bharuch", 68, 100, 0.0, "highway"),
            _seg("AS_04", "Bharuch – Surat", 75, 100, 0.0, "highway"),
            _seg("AS_05", "Surat Urban", 12, 35, 0.0, "urban"),
        ],
        "charger_ids": ["CHR_GJ_001"],
        "waypoints": [
            {"lat": 23.0395, "lng": 72.5270},
            {"lat": 22.3072, "lng": 73.1812},
            {"lat": 21.7051, "lng": 72.9959},
            {"lat": 21.1702, "lng": 72.8311},
        ]
    },
}


def get_all_chargers() -> List[Dict]:
    return list(CHARGERS.values())


def get_charger(charger_id: str) -> Dict | None:
    return CHARGERS.get(charger_id)


def get_chargers_for_route(route_id: str) -> List[Dict]:
    route = DEMO_ROUTES.get(route_id, {})
    ids = route.get("charger_ids", [])
    return [CHARGERS[cid] for cid in ids if cid in CHARGERS]


import json
import os

_ROAD_GEOMETRY = {}
_geom_file = os.path.join(os.path.dirname(__file__), "road_geometry.json")
if os.path.exists(_geom_file):
    try:
        with open(_geom_file, "r", encoding="utf-8") as _f:
            _ROAD_GEOMETRY = json.load(_f)
    except Exception:
        pass


def get_route_geometry(route_id: str) -> List[List[float]]:
    """Return high-resolution turn-by-turn road coordinates [[lat, lng], ...] for route."""
    return _ROAD_GEOMETRY.get(route_id, [])


def get_demo_route(route_id: str) -> Dict | None:
    route = DEMO_ROUTES.get(route_id)
    if not route:
        return None
    r = dict(route)
    r["road_geometry"] = get_route_geometry(route_id)
    return r


def get_all_demo_routes() -> List[Dict]:
    routes = []
    for r in DEMO_ROUTES.values():
        item = {k: v for k, v in r.items() if k != "segments"}
        item["road_geometry"] = get_route_geometry(r["route_id"])
        routes.append(item)
    return routes


def chargers_near(lat: float, lng: float, radius_km: float,
                  connector_filter: list | None = None) -> List[Dict]:
    """Return chargers within radius_km of (lat, lng)."""
    def haversine(lat1, lng1, lat2, lng2):
        R = 6371.0
        d_lat = math.radians(lat2 - lat1)
        d_lng = math.radians(lng2 - lng1)
        a = (math.sin(d_lat/2)**2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(d_lng/2)**2)
        return 2 * R * math.asin(math.sqrt(a))

    result = []
    for c in CHARGERS.values():
        d = haversine(lat, lng, c["lat"], c["lng"])
        if d <= radius_km:
            if connector_filter:
                if not any(ct in c["connector_types"] for ct in connector_filter):
                    continue
            result.append({**c, "_distance_km": round(d, 2)})
    result.sort(key=lambda x: x["_distance_km"])
    return result
