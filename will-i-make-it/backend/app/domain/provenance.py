"""
Data Provenance and Quality Architecture
=========================================
Foundational models for provenance tracking, data quality assessment, and
typed values with strict source attribution.

Principles:
1. Every piece of data must have clear provenance (REAL, ESTIMATED, SIMULATED, UNKNOWN, STALE).
2. Data quality is explicitly separated from provenance.
3. No arbitrary numerical confidence scores.
4. Physical quantities have explicit units.
5. Missing or unknown data is never silently fabricated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Generic, Optional, TypeVar, Literal, Any, Union, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator


class DataStatus(str, Enum):
    """
    Semantic status of a data observation or parameter.

    REAL:
        Directly obtained from an actual measurement, official manufacturer
        specification, verified API, or real telemetry. Does not automatically
        mean accurate, but means it is not inferred or synthetic.

    ESTIMATED:
        Inferred, derived, calculated, interpolated, or predicted from other
        inputs (e.g. gradient derived from elevation points, physics prediction,
        Bayesian reliability posterior).

    SIMULATED:
        Intentionally generated for testing, scenario analysis, synthetic
        benchmarks, or demo operation. Must NEVER be represented as real data.

    UNKNOWN:
        Unavailable, not verified, or its provenance cannot be established.
        Must NOT be replaced by an arbitrary default without explicit labeling.

    STALE:
        Was once valid/available but has exceeded its context-specific freshness
        window (e.g. weather past forecast validity, live charger status past 48h).
    """
    REAL = "REAL"
    ESTIMATED = "ESTIMATED"
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"


class SourceType(str, Enum):
    """Broad categorization of data sources."""
    MANUFACTURER = "MANUFACTURER"
    OFFICIAL_REGISTRY = "OFFICIAL_REGISTRY"
    API_TELEMETRY = "API_TELEMETRY"
    SENSOR = "SENSOR"
    PHYSICS_MODEL = "PHYSICS_MODEL"
    STATISTICAL_INFERENCE = "STATISTICAL_INFERENCE"
    COMMUNITY_REPORT = "COMMUNITY_REPORT"
    SYNTHETIC_SIMULATION = "SYNTHETIC_SIMULATION"
    UNKNOWN = "UNKNOWN"


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class DataProvenance(BaseModel):
    """
    Metadata recording the origin, time, and transformation of a data element.
    """
    status: DataStatus = Field(
        ...,
        description="Semantic status: REAL, ESTIMATED, SIMULATED, UNKNOWN, STALE."
    )
    source_name: Optional[str] = Field(
        None,
        description="Name of the external source, API, dataset, or model."
    )
    source_type: Optional[SourceType] = Field(
        None,
        description="Categorical type of source."
    )
    source_reference: Optional[str] = Field(
        None,
        description="URL, citation, document reference, or API endpoint identifier."
    )
    observed_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the observation physically occurred."
    )
    fetched_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the system retrieved the data."
    )
    valid_until: Optional[datetime] = Field(
        None,
        description="Timestamp until which this data is considered fresh."
    )
    processing_method: Optional[str] = Field(
        None,
        description="Algorithm, formula, or tool used to derive or process this value."
    )
    notes: Optional[str] = Field(
        None,
        description="Additional technical or domain annotations."
    )

    @field_validator("observed_at", "fetched_at", "valid_until", mode="after")
    @classmethod
    def validate_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _ensure_utc(v)


T = TypeVar("T")


class DataValue(BaseModel, Generic[T]):
    """
    A typed value coupled with physical unit and provenance metadata.
    Enforces that values are never presented without provenance.
    """
    value: Optional[T] = Field(
        None,
        description="The actual data value. May be None if status is UNKNOWN."
    )
    unit: Optional[str] = Field(
        None,
        description="Standard physical unit (e.g. 'kWh', 'km', 'kg', 'km/h', 'kW', 'm', '%')."
    )
    provenance: DataProvenance = Field(
        ...,
        description="Provenance metadata describing origin, status, and timestamps."
    )

    @model_validator(mode="after")
    def validate_value_provenance_consistency(self) -> DataValue[T]:
        # If value is None and status is not UNKNOWN, flag an explicit warning note if not provided
        if self.value is None and self.provenance.status not in (DataStatus.UNKNOWN, DataStatus.STALE):
            if not self.provenance.notes:
                self.provenance.notes = "Null value recorded with non-UNKNOWN status"
        return self

    @property
    def is_known(self) -> bool:
        return self.provenance.status != DataStatus.UNKNOWN and self.value is not None

    @property
    def is_real(self) -> bool:
        return self.provenance.status == DataStatus.REAL

    @property
    def is_simulated(self) -> bool:
        return self.provenance.status == DataStatus.SIMULATED

    @property
    def is_stale(self) -> bool:
        return self.provenance.status == DataStatus.STALE

    @classmethod
    def real(
        cls,
        value: T,
        unit: Optional[str] = None,
        source_name: Optional[str] = None,
        source_type: SourceType = SourceType.OFFICIAL_REGISTRY,
        source_reference: Optional[str] = None,
        observed_at: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> DataValue[T]:
        """Convenience constructor for verified real-world data."""
        return cls(
            value=value,
            unit=unit,
            provenance=DataProvenance(
                status=DataStatus.REAL,
                source_name=source_name,
                source_type=source_type,
                source_reference=source_reference,
                observed_at=observed_at,
                notes=notes,
            ),
        )

    @classmethod
    def estimated(
        cls,
        value: T,
        unit: Optional[str] = None,
        processing_method: Optional[str] = None,
        source_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> DataValue[T]:
        """Convenience constructor for derived or estimated values."""
        return cls(
            value=value,
            unit=unit,
            provenance=DataProvenance(
                status=DataStatus.ESTIMATED,
                source_name=source_name,
                source_type=SourceType.PHYSICS_MODEL if "physics" in (processing_method or "").lower() else SourceType.STATISTICAL_INFERENCE,
                processing_method=processing_method,
                notes=notes,
            ),
        )

    @classmethod
    def simulated(
        cls,
        value: T,
        unit: Optional[str] = None,
        scenario: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> DataValue[T]:
        """Convenience constructor for synthetic simulation data."""
        return cls(
            value=value,
            unit=unit,
            provenance=DataProvenance(
                status=DataStatus.SIMULATED,
                source_name=scenario or "Synthetic Simulation Engine",
                source_type=SourceType.SYNTHETIC_SIMULATION,
                notes=notes or "Synthetic data generated for demonstration/testing.",
            ),
        )

    @classmethod
    def unknown(cls, unit: Optional[str] = None, notes: Optional[str] = None) -> DataValue[T]:
        """Convenience constructor for unavailable or unverified values."""
        return cls(
            value=None,
            unit=unit,
            provenance=DataProvenance(
                status=DataStatus.UNKNOWN,
                source_name="Unknown",
                source_type=SourceType.UNKNOWN,
                notes=notes or "Value is unverified or unavailable.",
            ),
        )

    @classmethod
    def stale(
        cls,
        value: T,
        unit: Optional[str] = None,
        last_observed: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> DataValue[T]:
        """Convenience constructor for outdated observations."""
        return cls(
            value=value,
            unit=unit,
            provenance=DataProvenance(
                status=DataStatus.STALE,
                observed_at=last_observed,
                notes=notes or "Data freshness threshold exceeded.",
            ),
        )


class CompletenessLevel(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class FreshnessLevel(str, Enum):
    FRESH = "FRESH"
    ACCEPTABLE = "ACCEPTABLE"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ResolutionLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    COARSE = "COARSE"
    UNKNOWN = "UNKNOWN"


class SourceReliability(str, Enum):
    VERIFIED = "VERIFIED"
    RELIABLE = "RELIABLE"
    UNVERIFIED = "UNVERIFIED"
    SUSPECT = "SUSPECT"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(str, Enum):
    VALIDATED = "VALIDATED"
    PROVISIONALLY_CHECKED = "PROVISIONALLY_CHECKED"
    UNVALIDATED = "UNVALIDATED"
    REJECTED = "REJECTED"


class DataQuality(BaseModel):
    """
    Multi-dimensional data quality assessment.
    Explicitly decoupled from provenance and avoids arbitrary 0-100 percentages.
    """
    completeness: CompletenessLevel = CompletenessLevel.UNKNOWN
    freshness: FreshnessLevel = FreshnessLevel.UNKNOWN
    spatial_resolution: ResolutionLevel = ResolutionLevel.UNKNOWN
    temporal_resolution: ResolutionLevel = ResolutionLevel.UNKNOWN
    source_reliability: SourceReliability = SourceReliability.UNKNOWN
    validation_status: ValidationStatus = ValidationStatus.UNVALIDATED
    notes: Optional[str] = Field(
        None,
        description="Technical context explaining the categorical assessment."
    )


# Type aliases for flexible instantiation with both parameterized and unparameterized DataValue
DataFloat = Union[DataValue[float], DataValue[Any], DataValue]
DataStr = Union[DataValue[str], DataValue[Any], DataValue]
DataInt = Union[DataValue[int], DataValue[Any], DataValue]
DataBool = Union[DataValue[bool], DataValue[Any], DataValue]
DataCoords = Union[DataValue[Tuple[float, float]], DataValue[Any], DataValue]
