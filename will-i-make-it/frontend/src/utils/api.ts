import axios from 'axios';
import type {
  VehicleProfile, RouteSegment, EnergyPredictResponse,
  RoutePlanResponse, Charger, TripRecord, DemoRoute
} from '../types/api';

const BASE = '/api';

const api = axios.create({ baseURL: BASE, timeout: 30000 });

export const healthCheck = () => api.get('/health').then(r => r.data);

export const getDemoRoutes = (): Promise<{ routes: DemoRoute[]; count: number; disclaimer: string }> =>
  api.get('/routes/demo').then(r => r.data);

export const getDemoRoute = (routeId: string) =>
  api.get(`/routes/demo/${routeId}`).then(r => r.data);

export const getRouteGeometry = (routeId: string): Promise<{ route_id: string; coordinates: [number, number][]; point_count: number }> =>
  api.get(`/routes/geometry/${routeId}`).then(r => r.data);

export const geocodePlaces = (query: string): Promise<{ query: string; results: { name: string; lat: number; lng: number; type?: string }[] }> =>
  api.get('/routes/geocode', { params: { q: query } }).then(r => r.data);

export const planRoute = (payload: {
  origin_lat: number;
  origin_lng: number;
  dest_lat: number;
  dest_lng: number;
  origin_name?: string;
  dest_name?: string;
  vehicle: VehicleProfile;
  ambient_temp_c?: number;
  confidence_target?: number;
  demo_route_id?: string;
  disabled_charger_ids?: string[];
}): Promise<RoutePlanResponse> =>
  api.post('/routes/plan', payload).then(r => r.data);

export const predictEnergy = (payload: {
  vehicle: VehicleProfile;
  segments: RouteSegment[];
  ambient_temp_c?: number;
  confidence_target?: number;
}): Promise<EnergyPredictResponse> =>
  api.post('/energy/predict', payload).then(r => r.data);

export const getNearbyChargers = (
  lat: number, lng: number, radius_km?: number
): Promise<{ chargers: Charger[]; count: number }> =>
  api.get('/chargers/nearby', { params: { lat, lng, radius_km: radius_km ?? 100 } }).then(r => r.data);

export const getAllChargers = (): Promise<{ chargers: Charger[] }> =>
  api.get('/chargers/all').then(r => r.data);

export const reportCharger = (payload: {
  charger_id: string;
  success: boolean;
  connector_type: string;
  notes?: string;
}) => api.post('/chargers/report', payload).then(r => r.data);

export const simulateTrip = (payload: {
  route_id: string;
  vehicle: VehicleProfile;
  ambient_temp_c?: number;
  noise_seed?: number;
}): Promise<TripRecord> =>
  api.post('/trips/simulate', payload).then(r => r.data);

export const getSarvamStatus = () =>
  api.get('/sarvam/status').then(r => r.data);

export const explainRoute = (routeResult: unknown, languageCode?: string) =>
  api.post('/sarvam/explain', { route_result: routeResult, language_code: languageCode ?? 'hi-IN' })
    .then(r => r.data);
