"""
Unit Tests for Domain Model & Data Provenance Architecture (Phase 1)
===================================================================
Tests verify:
1. DataStatus and DataProvenance (REAL, ESTIMATED, SIMULATED, UNKNOWN, STALE)
2. Generic DataValue with physical units and source attribution
3. No silent value fabrication for UNKNOWN values
4. Multi-dimensional DataQuality without arbitrary 0-100 scores
5. Vehicle, Route, Elevation, Weather, Traffic, Charging Station, and Connector domain models
6. Physical bounds validation constraints
7. Bidirectional adapters and backward compatibility with legacy API schemas
"""
from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

from app.domain.provenance import (
    DataStatus,
    SourceType,
    DataProvenance,
    DataValue,
    DataQuality,
    CompletenessLevel,
    FreshnessLevel,
    ResolutionLevel,
    SourceReliability,
    ValidationStatus,
)
from app.domain.vehicle import VehicleDomain
from app.domain.route import ElevationDomain, RouteSegmentDomain, RouteDomain
from app.domain.environment import WeatherDomain, TrafficDomain
from app.domain.charging import ConnectorDomain, ChargingStationDomain, StationProvenanceBreakdown
from app.domain.adapters import (
    vehicle_profile_to_domain,
    vehicle_domain_to_profile,
    segment_schema_to_domain,
    segment_domain_to_schema,
    charger_schema_to_domain,
    charger_domain_to_schema,
)
from app.models.schemas import VehicleProfile, RouteSegment, Charger, ConnectorType


class TestProvenanceAndDataValue:
    def test_datastatus_enum_complete(self):
        """Verify all 5 required provenance statuses exist with exact string representations."""
        assert DataStatus.REAL == "REAL"
        assert DataStatus.ESTIMATED == "ESTIMATED"
        assert DataStatus.SIMULATED == "SIMULATED"
        assert DataStatus.UNKNOWN == "UNKNOWN"
        assert DataStatus.STALE == "STALE"

    def test_datavalue_real_constructor(self):
        """REAL value carries source attribution and observation time."""
        now = datetime.now(timezone.utc)
        val = DataValue.real(
            value=60.0,
            unit="kWh",
            source_name="Tata Motors Official Spec Sheet",
            source_type=SourceType.MANUFACTURER,
            observed_at=now,
        )
        assert val.value == 60.0
        assert val.unit == "kWh"
        assert val.is_real is True
        assert val.is_known is True
        assert val.provenance.status == DataStatus.REAL
        assert val.provenance.source_name == "Tata Motors Official Spec Sheet"
        assert val.provenance.observed_at == now

    def test_datavalue_estimated_constructor(self):
        """ESTIMATED value preserves processing method."""
        val = DataValue.estimated(
            value=3.45,
            unit="kWh",
            processing_method="Physics forces integration (drag + rolling + gradient)",
            source_name="Energy Physics Engine",
        )
        assert val.value == 3.45
        assert val.provenance.status == DataStatus.ESTIMATED
        assert "Physics" in val.provenance.processing_method

    def test_datavalue_simulated_constructor(self):
        """SIMULATED value is explicitly marked and identified."""
        val = DataValue.simulated(
            value=52.0,
            unit="kW",
            scenario="Charger degradation stress test scenario A",
        )
        assert val.is_simulated is True
        assert val.provenance.status == DataStatus.SIMULATED
        assert val.provenance.source_type == SourceType.SYNTHETIC_SIMULATION

    def test_datavalue_unknown_no_fabricated_value(self):
        """UNKNOWN value has None value and does not fabricate a default number."""
        val = DataValue.unknown(unit="%", notes="Telemetry sensor offline")
        assert val.value is None
        assert val.unit == "%"
        assert val.is_known is False
        assert val.provenance.status == DataStatus.UNKNOWN

    def test_datavalue_stale_preserves_original(self):
        """STALE value preserves its value and previous observation timestamp."""
        ts = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
        val = DataValue.stale(value=18.5, unit="°C", last_observed=ts)
        assert val.is_stale is True
        assert val.value == 18.5
        assert val.provenance.observed_at == ts

    def test_timezone_aware_validation(self):
        """Naive datetimes in provenance must be converted to timezone-aware UTC."""
        naive = datetime(2026, 11, 19, 2, 0, 0)
        prov = DataProvenance(status=DataStatus.REAL, observed_at=naive)
        assert prov.observed_at.tzinfo is not None
        assert prov.observed_at.tzinfo == timezone.utc

    def test_datavalue_serialization_clean(self):
        """DataValue serializes to clean JSON-compatible dictionary."""
        val = DataValue.real(40.0, unit="kWh")
        dump = val.model_dump()
        assert dump["value"] == 40.0
        assert dump["unit"] == "kWh"
        assert dump["provenance"]["status"] == "REAL"


class TestDataQuality:
    def test_data_quality_categorical_dimensions(self):
        """DataQuality provides categorical dimensions without arbitrary percentage scores."""
        dq = DataQuality(
            completeness=CompletenessLevel.COMPLETE,
            freshness=FreshnessLevel.FRESH,
            spatial_resolution=ResolutionLevel.HIGH,
            temporal_resolution=ResolutionLevel.HIGH,
            source_reliability=SourceReliability.VERIFIED,
            validation_status=ValidationStatus.VALIDATED,
            notes="Copernicus DEM 30m high-resolution dataset",
        )
        dump = dq.model_dump()
        assert "score" not in dump  # No arbitrary numerical score
        assert dump["completeness"] == "COMPLETE"
        assert dump["source_reliability"] == "VERIFIED"


class TestVehicleDomain:
    def _sample_vehicle(self, **overrides):
        prov = DataProvenance(status=DataStatus.REAL, source_name="OEM Spec")
        params = dict(
            vehicle_id="tata_nexon_ev_40",
            make=DataValue(value="Tata", unit=None, provenance=prov),
            model=DataValue(value="Nexon.ev", unit=None, provenance=prov),
            battery_capacity_kwh=DataValue(value=40.5, unit="kWh", provenance=prov),
            usable_battery_capacity_kwh=DataValue(value=40.0, unit="kWh", provenance=prov),
            curb_mass_kg=DataValue(value=1450.0, unit="kg", provenance=prov),
            drag_coefficient=DataValue(value=0.32, unit=None, provenance=prov),
            frontal_area_m2=DataValue(value=2.35, unit="m2", provenance=prov),
            rolling_resistance_coeff=DataValue(value=0.012, unit=None, provenance=prov),
            drivetrain_efficiency=DataValue(value=0.88, unit=None, provenance=prov),
            regen_efficiency=DataValue(value=0.65, unit=None, provenance=prov),
            connector_types=[ConnectorType.CCS2, ConnectorType.Type2_AC],
        )
        params.update(overrides)
        return VehicleDomain(**params)

    def test_valid_vehicle_domain(self):
        veh = self._sample_vehicle()
        assert veh.vehicle_id == "tata_nexon_ev_40"
        assert veh.usable_battery_capacity_kwh.value == 40.0
        assert veh.usable_battery_capacity_kwh.unit == "kWh"

    def test_invalid_usable_greater_than_gross_battery(self):
        """Usable capacity cannot exceed gross capacity."""
        prov = DataProvenance(status=DataStatus.REAL)
        with pytest.raises(ValidationError):
            self._sample_vehicle(
                battery_capacity_kwh=DataValue(value=40.0, unit="kWh", provenance=prov),
                usable_battery_capacity_kwh=DataValue(value=45.0, unit="kWh", provenance=prov),
            )

    def test_negative_mass_rejected(self):
        """Curb mass must be strictly positive."""
        prov = DataProvenance(status=DataStatus.REAL)
        with pytest.raises(ValidationError):
            self._sample_vehicle(
                curb_mass_kg=DataValue(value=-500.0, unit="kg", provenance=prov)
            )

    def test_unrealistic_drag_coefficient_rejected(self):
        """Cd outside 0.10–0.85 must fail validation."""
        prov = DataProvenance(status=DataStatus.REAL)
        with pytest.raises(ValidationError):
            self._sample_vehicle(
                drag_coefficient=DataValue(value=1.50, unit=None, provenance=prov)
            )


class TestRouteAndEnvironmentDomain:
    def test_elevation_domain_validation(self):
        prov = DataProvenance(status=DataStatus.REAL, source_name="SRTM DEM")
        elev = ElevationDomain(
            latitude=19.076,
            longitude=72.8777,
            elevation=DataValue.real(14.0, unit="m"),
            elevation_source="SRTM",
            provenance=prov,
        )
        assert elev.elevation.value == 14.0

    def test_route_segment_gradient_bounds(self):
        prov = DataProvenance(status=DataStatus.REAL)
        # Gradient > 35% rejected as unrealistic for road vehicle
        with pytest.raises(ValidationError):
            RouteSegmentDomain(
                segment_id="SEG_IMPOSSIBLE",
                distance=DataValue.real(5.0, unit="km"),
                speed=DataValue.real(60.0, unit="km/h"),
                gradient=DataValue.real(45.0, unit="%"),
                road_type=DataValue.real("highway"),
                road_condition=DataValue.unknown(),
            )

    def test_weather_forecast_cannot_be_real(self):
        """Forecast cannot claim to be a REAL observation."""
        prov = DataProvenance(status=DataStatus.REAL)
        with pytest.raises(ValidationError):
            WeatherDomain(
                ambient_temperature=DataValue.real(32.0, unit="°C"),
                is_forecast=True,
                provenance=prov,
            )

    def test_traffic_live_requires_real_or_stale(self):
        """LIVE traffic cannot claim SIMULATED status without error."""
        prov = DataProvenance(status=DataStatus.SIMULATED)
        with pytest.raises(ValidationError):
            TrafficDomain(
                speed=DataValue.simulated(45.0, unit="km/h"),
                congestion_level=DataValue.simulated("MODERATE"),
                traffic_type="LIVE",
                provenance=prov,
            )


class TestChargingDomain:
    def test_charging_station_attribute_provenance(self):
        """Charging station supports separate provenance per attribute."""
        prov_real = DataProvenance(status=DataStatus.REAL, source_name="Registry API")
        prov_sim = DataProvenance(status=DataStatus.SIMULATED, source_name="Demo Script")
        prov_est = DataProvenance(status=DataStatus.ESTIMATED, processing_method="Beta posterior")

        conn = ConnectorDomain(
            connector_type=ConnectorType.CCS2,
            rated_power_kw=DataValue.real(60.0, unit="kW"),
            is_operational=DataValue.real(True),
            provenance=prov_real,
        )

        station = ChargingStationDomain(
            station_id="CHR_TEST_01",
            name=DataValue.real("Tata Fast Hub"),
            coordinates=DataValue.real((18.5204, 73.8567), unit="deg"),
            operator=DataValue.real("Tata Power"),
            connectors=[conn],
            max_power_kw=DataValue.real(60.0, unit="kW"),
            available_ports=DataValue.simulated(2, unit="ports"),
            is_operational=DataValue.real(True),
            reliability_score=DataValue.estimated(0.85, unit="fraction"),
            provenance_breakdown=StationProvenanceBreakdown(
                existence=prov_real,
                location=prov_real,
                connectors=prov_real,
                operational_status=prov_real,
                live_availability=prov_sim,
                reliability=prov_est,
            ),
            provenance=prov_real,
        )
        assert station.station_id == "CHR_TEST_01"
        assert station.provenance_breakdown.live_availability.status == DataStatus.SIMULATED
        assert station.provenance_breakdown.existence.status == DataStatus.REAL


class TestAdaptersBackwardCompatibility:
    def test_vehicle_profile_roundtrip(self):
        """Ensure legacy VehicleProfile adapts to VehicleDomain and back without loss."""
        orig = VehicleProfile(
            battery_capacity_kwh=40.0,
            soc_start_pct=75.0,
            soc_reserve_pct=15.0,
            vehicle_mass_kg=1600.0,
            drag_coefficient=0.29,
            frontal_area_m2=2.4,
            rolling_resistance=0.011,
            drivetrain_efficiency=0.90,
            regen_efficiency=0.70,
            connector_types=[ConnectorType.CCS2],
            ac_load_kw=1.8,
            payload_kg=120.0,
        )
        domain = vehicle_profile_to_domain(orig, status=DataStatus.SIMULATED)
        assert domain.usable_battery_capacity_kwh.value == 40.0
        assert domain.usable_battery_capacity_kwh.unit == "kWh"
        assert domain.curb_mass_kg.value == 1600.0

        recovered = vehicle_domain_to_profile(
            domain,
            soc_start_pct=orig.soc_start_pct,
            soc_reserve_pct=orig.soc_reserve_pct,
            ac_load_kw=orig.ac_load_kw,
            payload_kg=orig.payload_kg,
        )
        assert recovered.battery_capacity_kwh == orig.battery_capacity_kwh
        assert recovered.soc_start_pct == orig.soc_start_pct
        assert recovered.vehicle_mass_kg == orig.vehicle_mass_kg
        assert recovered.drag_coefficient == orig.drag_coefficient

    def test_segment_schema_roundtrip(self):
        """Ensure legacy RouteSegment adapts to RouteSegmentDomain and back."""
        schema_seg = RouteSegment(
            segment_id="SEG_TEST",
            distance_km=15.5,
            avg_speed_kmh=85.0,
            gradient_pct=1.2,
            road_type="highway",
            name="Expressway S1",
        )
        domain_seg = segment_schema_to_domain(schema_seg, sequence_order=1)
        assert domain_seg.distance.value == 15.5
        assert domain_seg.distance.unit == "km"
        assert domain_seg.speed.unit == "km/h"

        recovered = segment_domain_to_schema(domain_seg)
        assert recovered.segment_id == schema_seg.segment_id
        assert recovered.distance_km == schema_seg.distance_km
        assert recovered.avg_speed_kmh == schema_seg.avg_speed_kmh
        assert recovered.gradient_pct == schema_seg.gradient_pct
        assert recovered.road_type == schema_seg.road_type

    def test_charger_schema_roundtrip(self):
        """Ensure legacy Charger schema adapts to ChargingStationDomain and back."""
        schema_chr = Charger(
            charger_id="CHR_001",
            name="Fast Charge Lonavala",
            lat=18.75,
            lng=73.40,
            connector_types=[ConnectorType.CCS2, ConnectorType.Type2_AC],
            max_power_kw=60.0,
            operator="Tata Power",
            reliability_score=0.82,
            is_operational=True,
            address="Lonavala Plaza",
        )
        domain_chr = charger_schema_to_domain(schema_chr)
        assert domain_chr.station_id == "CHR_001"
        assert domain_chr.max_power_kw.value == 60.0
        assert domain_chr.max_power_kw.unit == "kW"

        recovered = charger_domain_to_schema(domain_chr)
        assert recovered.charger_id == schema_chr.charger_id
        assert recovered.name == schema_chr.name
        assert recovered.lat == schema_chr.lat
        assert recovered.lng == schema_chr.lng
        assert recovered.reliability_score == schema_chr.reliability_score
