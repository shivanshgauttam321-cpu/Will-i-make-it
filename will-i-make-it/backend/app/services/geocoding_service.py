"""
Geocoding Service for Indian Locations
=======================================
Combines an instant offline database of major Indian cities, transit hubs, and
expressway origins with live OpenStreetMap Nominatim geocoding.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List

PREINDEXED_INDIAN_PLACES: List[Dict[str, Any]] = [
    {"name": "New Delhi, Delhi", "lat": 28.6139, "lng": 77.2090, "type": "National Capital"},
    {"name": "Connaught Place, New Delhi", "lat": 28.6315, "lng": 77.2167, "type": "City Center"},
    {"name": "Gurugram / DLF Cyber Hub, Haryana", "lat": 28.4952, "lng": 77.0882, "type": "IT Corridor"},
    {"name": "Noida Sector 62, Uttar Pradesh", "lat": 28.6280, "lng": 77.3649, "type": "Tech Hub"},
    {"name": "Mumbai / Nariman Point, Maharashtra", "lat": 18.9256, "lng": 72.8242, "type": "Metro"},
    {"name": "Bandra Kurla Complex (BKC), Mumbai", "lat": 19.0657, "lng": 72.8687, "type": "Financial Hub"},
    {"name": "Navi Mumbai, Maharashtra", "lat": 19.0330, "lng": 73.0297, "type": "Satellite City"},
    {"name": "Lonavala / Khandala, Maharashtra", "lat": 18.7481, "lng": 73.4072, "type": "Expressway Hub"},
    {"name": "Pune / Shivajinagar, Maharashtra", "lat": 18.5314, "lng": 73.8446, "type": "Metro"},
    {"name": "Jaipur (Pink City), Rajasthan", "lat": 26.9124, "lng": 75.7873, "type": "Heritage / Highway"},
    {"name": "Agra / Taj Mahal, Uttar Pradesh", "lat": 27.1767, "lng": 78.0081, "type": "Tourist Hub"},
    {"name": "Bengaluru / Indiranagar, Karnataka", "lat": 12.9784, "lng": 77.6408, "type": "Tech Capital"},
    {"name": "Electronic City, Bengaluru", "lat": 12.8399, "lng": 77.6770, "type": "IT Corridor"},
    {"name": "Mysuru / Palace, Karnataka", "lat": 12.3052, "lng": 76.6551, "type": "Expressway End"},
    {"name": "Chennai / OMR Tidel Park, Tamil Nadu", "lat": 12.9940, "lng": 80.2490, "type": "Coastal Metro"},
    {"name": "Hyderabad / HITEC City, Telangana", "lat": 17.4435, "lng": 78.3772, "type": "Cyber Hub"},
    {"name": "Ahmedabad / Vastrapur, Gujarat", "lat": 23.0395, "lng": 72.5270, "type": "Industrial Hub"},
    {"name": "Surat, Gujarat", "lat": 21.1702, "lng": 72.8311, "type": "Commercial Hub"},
    {"name": "Vadodara, Gujarat", "lat": 22.3072, "lng": 73.1812, "type": "Highway Hub"},
    {"name": "Panaji, Goa", "lat": 15.4909, "lng": 73.8278, "type": "Coastal Destination"},
    {"name": "Chandigarh, Punjab/Haryana", "lat": 30.7333, "lng": 76.7794, "type": "Union Territory"},
    {"name": "Dehradun, Uttarakhand", "lat": 30.3165, "lng": 78.0322, "type": "Foothills"},
    {"name": "Shimla / Mall Road, Himachal Pradesh", "lat": 31.1048, "lng": 77.1734, "type": "Hill Station"},
    {"name": "Kolkata / Park Street, West Bengal", "lat": 22.5535, "lng": 88.3518, "type": "East Metro"},
    {"name": "Lucknow / Hazratganj, Uttar Pradesh", "lat": 26.8467, "lng": 80.9462, "type": "State Capital"},
    {"name": "Kanpur, Uttar Pradesh", "lat": 26.4499, "lng": 80.3319, "type": "Industrial Hub"},
    {"name": "Indore, Madhya Pradesh", "lat": 22.7196, "lng": 75.8577, "type": "Commercial Hub"},
    {"name": "Bhopal, Madhya Pradesh", "lat": 23.2599, "lng": 77.4126, "type": "Central Hub"},
    {"name": "Kochi / Marine Drive, Kerala", "lat": 9.9816, "lng": 76.2763, "type": "Coastal Port"},
    {"name": "Thiruvananthapuram, Kerala", "lat": 8.5241, "lng": 76.9366, "type": "South Capital"},
    {"name": "Coimbatore, Tamil Nadu", "lat": 11.0168, "lng": 76.9558, "type": "Textile Hub"},
    {"name": "Visakhapatnam, Andhra Pradesh", "lat": 17.6868, "lng": 83.2185, "type": "Port City"},
    {"name": "Varanasi / Ghats, Uttar Pradesh", "lat": 25.3176, "lng": 82.9739, "type": "Heritage City"},
    {"name": "Amritsar / Golden Temple, Punjab", "lat": 31.6340, "lng": 74.8723, "type": "Highway Hub"},
    {"name": "Nagpur (Zero Mile), Maharashtra", "lat": 21.1458, "lng": 79.0882, "type": "Geographic Center"},
    {"name": "Nashik, Maharashtra", "lat": 19.9975, "lng": 73.7898, "type": "Highway Hub"},
    {"name": "Udaipur, Rajasthan", "lat": 24.5854, "lng": 73.7125, "type": "Lake City"},
]


def search_locations(query: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    Search for locations matching query.
    First matches preindexed Indian cities instantly, then queries Nominatim if needed.
    """
    q_norm = query.strip().lower()
    if not q_norm:
        return PREINDEXED_INDIAN_PLACES[:limit]

    results: List[Dict[str, Any]] = []

    # 1. Instant local matching
    for p in PREINDEXED_INDIAN_PLACES:
        if q_norm in p["name"].lower() or any(term in p["name"].lower() for term in q_norm.split()):
            results.append(p)
            if len(results) >= limit:
                return results

    # 2. Live OpenStreetMap Nominatim query for specific addresses / landmarks
    if len(results) < limit:
        try:
            url = (
                f"https://nominatim.openstreetmap.org/search?"
                f"q={urllib.parse.quote(query)}&format=json&countrycodes=in&limit={limit - len(results)}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "WillIMakeIt-EV/1.0"})
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode())
                for item in data:
                    lat = float(item["lat"])
                    lng = float(item["lon"])
                    # Prevent duplicates
                    if not any(abs(r["lat"] - lat) < 0.01 and abs(r["lng"] - lng) < 0.01 for r in results):
                        name_parts = item["display_name"].split(", ")
                        short_name = ", ".join(name_parts[:3])
                        results.append({
                            "name": short_name,
                            "lat": lat,
                            "lng": lng,
                            "type": item.get("type", "Location").replace("_", " ").title(),
                        })
        except Exception:
            pass

    return results[:limit]
