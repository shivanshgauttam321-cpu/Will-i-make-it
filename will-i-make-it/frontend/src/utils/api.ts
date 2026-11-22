import axios from 'axios';
import type {
  VehicleProfile, RouteSegment, EnergyPredictResponse,
  RoutePlanResponse, Charger, TripRecord, DemoRoute
} from '../types/api';

const BASE = (
  import.meta.env.VITE_API_BASE_URL || '/api'
).replace(/\/+$/, '');

const api = axios.create({
  baseURL: BASE,
  timeout: 30000,
});

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

export const getProvidersStatus = () =>
  api.get('/providers/status').then(r => r.data);

export const converseWithSarvam = (payload: {
  text?: string;
  audio_b64?: string;
  language_code?: string;
  speak_response?: boolean;
  speaker?: string;
}) => api.post('/sarvam/converse', payload).then(r => r.data);

export const textToSpeech = (text: string, language_code = 'hi-IN', speaker = 'meera') =>
  api.post('/sarvam/tts', { text, language_code, speaker }).then(r => r.data);

export const speechToText = (audio_b64: string, language_code = 'hi-IN') =>
  api.post('/sarvam/stt', { audio_b64, language_code }).then(r => r.data);

// ─────────────────────────────────────────────────────────────────────────────
// NEO4J GRAPH INTELLIGENCE & TRANSACTIONAL OUTBOX APIS
// ─────────────────────────────────────────────────────────────────────────────

export const getNeo4jHealth = () =>
  api.get('/neo4j/health').then(r => r.data);

export const getNeo4jStats = () =>
  api.get('/neo4j/stats').then(r => r.data);

export const getNeo4jGraph = (params?: { limit?: number; entity_types?: string; environment?: string }) =>
  api.get('/neo4j/graph', { params }).then(r => r.data);

export const getNeo4jNode = (nodeId: string) =>
  api.get(`/neo4j/nodes/${encodeURIComponent(nodeId)}`).then(r => r.data);

export const getNeo4jSyncStatus = () =>
  api.get('/neo4j/sync/status').then(r => r.data);

export const getNeo4jSyncEvents = (params?: { limit?: number; status?: string }) =>
  api.get('/neo4j/sync/events', { params }).then(r => r.data);

export const retryNeo4jEvent = (eventId: string) =>
  api.post(`/neo4j/sync/retry/${encodeURIComponent(eventId)}`).then(r => r.data);

export const triggerNeo4jSync = () =>
  api.post('/neo4j/sync/trigger').then(r => r.data);

export const createDemoInfrastructure = (payload?: any) =>
  api.post('/neo4j/demo/create-sample', payload || {}).then(r => r.data);

export const updateDemoStation = (payload?: any) =>
  api.post('/neo4j/demo/update-sample', payload || {}).then(r => r.data);

export const cleanupDemoData = () =>
  api.post('/neo4j/demo/cleanup').then(r => r.data);

