// API Types matching backend schemas

export interface VehicleProfile {
  battery_capacity_kwh: number;
  soc_start_pct: number;
  soc_reserve_pct: number;
  vehicle_mass_kg: number;
  drag_coefficient: number;
  frontal_area_m2: number;
  rolling_resistance: number;
  drivetrain_efficiency: number;
  regen_efficiency: number;
  connector_types: string[];
  ac_load_kw: number;
  payload_kg: number;
}

export interface RouteSegment {
  segment_id: string;
  distance_km: number;
  avg_speed_kmh: number;
  gradient_pct: number;
  road_type: 'highway' | 'urban' | 'rural';
  name?: string;
}

export interface SegmentEnergyResult {
  segment_id: string;
  name?: string;
  distance_km: number;
  rolling_kj: number;
  aero_kj: number;
  gradient_kj: number;
  aux_kj: number;
  regen_kj: number;
  net_kwh: number;
  net_kwh_p90: number;
  soc_after_pct?: number;
}

export interface EnergyPredictResponse {
  total_kwh_p50: number;
  total_kwh_p90: number;
  soc_final_p50_pct: number;
  soc_final_p90_pct: number;
  feasible: boolean;
  segments: SegmentEnergyResult[];
  assumptions: string[];
  uncertainty_method: string;
  data_disclaimer: string;
}

export interface Charger {
  charger_id: string;
  name: string;
  lat: number;
  lng: number;
  connector_types: string[];
  max_power_kw: number;
  operator: string;
  reliability_score: number;
  reliability_freshness_hours?: number;
  is_operational?: boolean | null;
  address?: string;
  total_reports?: number;
  _distance_km?: number;
}

export interface ChargingStop {
  charger: Charger;
  arrive_soc_pct: number;
  depart_soc_pct: number;
  charge_duration_min: number;
  charge_energy_kwh: number;
}

export interface RouteOption {
  route_id: string;
  label: string;
  description: string;
  distance_km: number;
  duration_min: number;
  segments: RouteSegment[];
  charging_stops: ChargingStop[];
  energy_result: EnergyPredictResponse;
  risk_score: number;
  feasible: boolean;
  feasibility_margin_kwh: number;
  explanation: string;
  road_geometry?: [number, number][];
}

export interface RoutePlanResponse {
  fastest_route: RouteOption;
  risk_aware_route?: RouteOption;
  recommended: string;
  neo4j_used: boolean;
  data_source: string;
  charger_failure_scenario?: string;
}

export interface PlaceLocation {
  name: string;
  lat: number;
  lng: number;
  type?: string;
}

export interface DemoRoute {
  route_id: string;
  label: string;
  description: string;
  origin: { lat: number; lng: number; name: string };
  destination: { lat: number; lng: number; name: string };
  distance_km: number;
  duration_min: number;
  charger_ids: string[];
  waypoints: { lat: number; lng: number }[];
  road_geometry?: [number, number][];
}

export interface TripRecord {
  trip_id: string;
  route_id: string;
  created_at: string;
  actual_kwh: number;
  predicted_kwh_p50: number;
  predicted_kwh_p90: number;
  within_p90: boolean;
  soc_final_pct: number;
  notes: string;
}
