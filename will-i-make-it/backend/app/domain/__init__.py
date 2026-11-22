# Will I Make It — Domain Package
from app.domain.provenance import (
    DataStatus,
    SourceType,
    DataProvenance,
    DataValue,
    DataQuality,
)
from app.domain.vehicle import (
    VehicleDomain,
    VehicleParameter,
)
from app.domain.route import (
    ElevationDomain,
    RouteSegmentDomain,
    RouteDomain,
)
from app.domain.environment import (
    WeatherDomain,
    TrafficDomain,
)
from app.domain.charging import (
    ConnectorDomain,
    ChargingStationDomain,
)
from app.domain.adapters import (
    vehicle_profile_to_domain,
    vehicle_domain_to_profile,
    segment_schema_to_domain,
    segment_domain_to_schema,
    charger_schema_to_domain,
    charger_domain_to_schema,
)

__all__ = [
    "DataStatus",
    "SourceType",
    "DataProvenance",
    "DataValue",
    "DataQuality",
    "VehicleDomain",
    "VehicleParameter",
    "ElevationDomain",
    "RouteSegmentDomain",
    "RouteDomain",
    "WeatherDomain",
    "TrafficDomain",
    "ConnectorDomain",
    "ChargingStationDomain",
    "vehicle_profile_to_domain",
    "vehicle_domain_to_profile",
    "segment_schema_to_domain",
    "segment_domain_to_schema",
    "charger_schema_to_domain",
    "charger_domain_to_schema",
]
