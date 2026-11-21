import React, { useState, useEffect } from 'react';
import { Database, AlertTriangle, RotateCcw, Activity, X, ShieldCheck, CheckCircle2, Globe, Cpu, Radio, ExternalLink } from 'lucide-react';
import { getProvidersStatus } from '../utils/api';

interface Props {
  routeLabel?: string;
  distanceKm?: number;
  durationMin?: number;
  backendOk: boolean | null;
  neo4jOk: boolean;
  neo4jDiagnostic?: string;
  onReplayIntro: () => void;
}

interface ProviderItem {
  name: string;
  type: string;
  enabled?: boolean;
  status: string;
  details?: Record<string, any>;
  description?: string;
  license?: string;
  source_url?: string;
}

export default function HeaderBar({
  routeLabel,
  distanceKm,
  durationMin,
  backendOk,
  neo4jOk,
  neo4jDiagnostic,
  onReplayIntro,
}: Props) {
  const [showProvidersModal, setShowProvidersModal] = useState(false);
  const [providersData, setProvidersData] = useState<any | null>(null);
  const [loadingProviders, setLoadingProviders] = useState(false);

  useEffect(() => {
    if (showProvidersModal && !providersData) {
      loadProviders();
    }
  }, [showProvidersModal]);

  const loadProviders = () => {
    setLoadingProviders(true);
    getProvidersStatus()
      .then(res => setProvidersData(res))
      .catch(() => setProvidersData(null))
      .finally(() => setLoadingProviders(false));
  };

  return (
    <>
      <header className="border-b border-[#1e2535] bg-[#0c1017]/90 backdrop-blur-xl px-4 sm:px-6 py-2.5 flex items-center justify-between gap-4 shrink-0 z-20">
        {/* Brand Title & Active Corridor Subtitle */}
        <div className="flex items-center gap-3 min-w-0">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm sm:text-base font-black tracking-tight text-white font-sans flex items-center gap-2">
                WILL I MAKE IT?
                <span className="text-[10px] bg-orange-500/15 text-orange-400 font-mono font-bold px-2 py-0.5 rounded-full border border-orange-500/30">
                  EV INTELLIGENCE
                </span>
              </h1>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-slate-400 truncate">
              {routeLabel ? (
                <span className="truncate">
                  Corridor: <span className="text-slate-200 font-medium">{routeLabel}</span>
                  {distanceKm !== undefined && (
                    <span className="text-orange-400 font-mono font-semibold ml-1.5">
                      ({distanceKm} km · ~{Math.round(durationMin ?? 0)} min)
                    </span>
                  )}
                </span>
              ) : (
                <span>Explainable, Risk-Aware EV Route Planner for Indian Conditions</span>
              )}
            </div>
          </div>
        </div>

        {/* Right-Side Status Badges (Clean Muted Charcoal & Orange Style) */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Replay 3D Intro Button */}
          <button
            type="button"
            onClick={onReplayIntro}
            className="badge-pill bg-[#121620] hover:bg-[#181e2b] text-slate-300 hover:text-white border-[#222938] hover:border-slate-600 text-[10px] font-mono transition-all hidden sm:inline-flex items-center gap-1.5"
            title="Replay EV 3D Boot Scene"
          >
            <RotateCcw size={10} className="text-orange-400" />
            <span>INTRO</span>
          </button>

          {/* Providers & Provenance Status Modal Trigger */}
          <button
            type="button"
            onClick={() => setShowProvidersModal(true)}
            className="badge-pill bg-[#121620] hover:bg-[#181e2b] text-cyan-400 hover:text-cyan-300 border-[#222938] hover:border-cyan-500/40 text-[10px] font-mono transition-all inline-flex items-center gap-1.5"
            title="View Data Providers, API Keys & Graph Status"
          >
            <Activity size={10} className="text-cyan-400" />
            <span>PROVIDERS</span>
          </button>

          {/* Simulated Telemetry Badge */}
          <span className="badge-pill bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px] font-mono hidden md:inline-flex items-center gap-1">
            <AlertTriangle size={10} className="text-amber-400" />
            SIMULATED DATA
          </span>

          {/* Neo4j Status */}
          <button 
            type="button"
            onClick={() => setShowProvidersModal(true)}
            className={`badge-pill text-[10px] font-mono hidden lg:inline-flex items-center gap-1.5 cursor-pointer ${
              neo4jOk 
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                : 'bg-[#121620] text-slate-400 border-[#222938]'
            }`}
            title={neo4jDiagnostic || 'Graph database integration status (click for details)'}
          >
            <Database size={10} className={neo4jOk ? 'text-emerald-400' : 'text-slate-500'} />
            {neo4jOk ? 'Neo4j Active' : 'Deterministic Fallback'}
          </button>

          {/* Backend Online Pill */}
          <div className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border font-mono ${
            backendOk === null 
              ? 'bg-[#121620] text-slate-400 border-[#222938]'
              : backendOk 
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
          }`}>
            <div className={`w-2 h-2 rounded-full ${
              backendOk === null 
                ? 'bg-slate-500' 
                : backendOk 
                  ? 'bg-emerald-400 animate-pulse' 
                  : 'bg-rose-500'
            }`} />
            <span className="font-semibold text-[10px]">
              {backendOk === null ? 'CONNECTING...' : backendOk ? 'FASTAPI ONLINE' : 'API OFFLINE'}
            </span>
          </div>
        </div>
      </header>

      {/* Providers & Provenance Details Modal */}
      {showProvidersModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in">
          <div className="bg-[#0f141f] border border-[#222938] rounded-xl max-w-2xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="px-5 py-4 border-b border-[#1e2535] flex items-center justify-between bg-[#131926]">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
                  <Activity size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white tracking-wide">
                    External Data Providers & System Health
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Active integrations, knowledge graphs, AI voice models & provenance
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowProvidersModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/60 transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-5 overflow-y-auto space-y-4 text-xs font-sans text-slate-300">
              {/* Physics Authority Notice */}
              <div className="p-3.5 bg-orange-500/10 border border-orange-500/30 rounded-lg flex items-start gap-3">
                <ShieldCheck size={18} className="text-orange-400 shrink-0 mt-0.5" />
                <div>
                  <div className="text-[11px] font-bold text-orange-300 font-mono tracking-wide uppercase">
                    Physical Simulation Authority
                  </div>
                  <div className="text-[11px] text-slate-300 mt-0.5 leading-relaxed">
                    The core Python EV powertrain and battery physics simulator is the sole authority for physical feasibility, state of charge dynamics, and thermal limits. Neo4j, Sarvam AI, and external APIs supply contextual enrichment without altering physical laws.
                  </div>
                </div>
              </div>

              {loadingProviders ? (
                <div className="py-8 text-center text-slate-400 font-mono">
                  Loading provider status and registry...
                </div>
              ) : providersData ? (
                <div className="space-y-3">
                  {/* Provider Cards */}
                  <div className="grid grid-cols-1 gap-2.5">
                    {/* Neo4j Graph Card */}
                    {providersData.providers?.neo4j && (
                      <div className="p-3 bg-[#141a27] border border-[#222938] rounded-lg">
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <Database size={14} className="text-indigo-400" />
                            <span className="font-semibold text-white">
                              {providersData.providers.neo4j.name}
                            </span>
                          </div>
                          <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                            providersData.providers.neo4j.status === 'UP' || providersData.providers.neo4j.status === 'CONNECTED'
                              ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                              : providersData.providers.neo4j.status === 'DISABLED'
                                ? 'bg-slate-700/40 text-slate-400 border-slate-600/30'
                                : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                          }`}>
                            {providersData.providers.neo4j.status}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400">
                          {providersData.providers.neo4j.details?.message || 
                            (providersData.providers.neo4j.enabled ? 'Connected to graph instance.' : 'Disabled in .env (Deterministic fallback active).')}
                        </div>
                        {providersData.providers.neo4j.details?.uri && (
                          <div className="mt-1 text-[10px] font-mono text-slate-500">
                            URI: {providersData.providers.neo4j.details.uri}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Sarvam AI Card */}
                    {providersData.providers?.sarvam_ai && (
                      <div className="p-3 bg-[#141a27] border border-[#222938] rounded-lg">
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <Radio size={14} className="text-violet-400" />
                            <span className="font-semibold text-white">
                              {providersData.providers.sarvam_ai.name}
                            </span>
                          </div>
                          <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                            providersData.providers.sarvam_ai.enabled
                              ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                              : 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                          }`}>
                            {providersData.providers.sarvam_ai.enabled ? 'ACTIVE API' : 'MOCK / FALLBACK MODE'}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400">
                          Provides Hindi/English multilingual voice synthesis (TTS), speech-to-text (STT), and grounded conversational trip advice.
                        </div>
                        <div className="mt-1.5 flex flex-wrap gap-2 text-[10px] font-mono text-slate-400">
                          <span className="bg-[#0b0e14] px-2 py-0.5 rounded border border-[#1e2535]">
                            STT: {providersData.providers.sarvam_ai.details?.stt_model || 'saaras:v1'}
                          </span>
                          <span className="bg-[#0b0e14] px-2 py-0.5 rounded border border-[#1e2535]">
                            TTS: {providersData.providers.sarvam_ai.details?.tts_model || 'bulbul:v1'}
                          </span>
                        </div>
                      </div>
                    )}

                    {/* Charging Infrastructure Providers */}
                    {providersData.providers?.charging_infrastructure && (
                      <div className="p-3 bg-[#141a27] border border-[#222938] rounded-lg">
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <Cpu size={14} className="text-emerald-400" />
                            <span className="font-semibold text-white">
                              Charging Infrastructure Data Aggregator
                            </span>
                          </div>
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full border bg-emerald-500/15 text-emerald-400 border-emerald-500/30">
                            COMPOSITE ACTIVE
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400 mb-2">
                          Aggregates real-time & corridor feeds with automated 50m proximity deduplication.
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[10px] font-mono">
                          <div className="p-2 bg-[#0d121c] rounded border border-[#1e2535]">
                            <div className="font-bold text-slate-300">Demo Corridor Feed</div>
                            <div className="text-emerald-400 mt-0.5">Seeded (3 Corridors)</div>
                          </div>
                          <div className="p-2 bg-[#0d121c] rounded border border-[#1e2535]">
                            <div className="font-bold text-slate-300">Open Charge Map</div>
                            <div className="text-slate-400 mt-0.5">
                              {providersData.providers.charging_infrastructure.details?.open_charge_map?.available ? 'Connected' : 'Fallback / Unconfigured'}
                            </div>
                          </div>
                          <div className="p-2 bg-[#0d121c] rounded border border-[#1e2535]">
                            <div className="font-bold text-slate-300">BEE EV Yatra</div>
                            <div className="text-slate-400 mt-0.5">Government Schema Ready</div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Routing & Weather Providers */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                      {providersData.providers?.osrm && (
                        <div className="p-3 bg-[#141a27] border border-[#222938] rounded-lg">
                          <div className="flex items-center gap-2 mb-1">
                            <Globe size={13} className="text-blue-400" />
                            <span className="font-semibold text-white">OSRM Routing</span>
                          </div>
                          <div className="text-[11px] text-slate-400">
                            Road geometry & segment elevations.
                          </div>
                          <div className="text-[10px] font-mono text-slate-500 mt-1">
                            Attribution: OpenStreetMap Contributors
                          </div>
                        </div>
                      )}

                      {providersData.providers?.open_meteo && (
                        <div className="p-3 bg-[#141a27] border border-[#222938] rounded-lg">
                          <div className="flex items-center gap-2 mb-1">
                            <Globe size={13} className="text-amber-400" />
                            <span className="font-semibold text-white">Open-Meteo Weather</span>
                          </div>
                          <div className="text-[11px] text-slate-400">
                            Live ambient temperature & headwind telemetry.
                          </div>
                          <div className="text-[10px] font-mono text-slate-500 mt-1">
                            License: CC-BY 4.0
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Provenance and Data Notice */}
                  <div className="p-3 bg-[#0d121c] border border-[#1e2535] rounded-lg text-[10px] font-mono text-slate-400 leading-relaxed">
                    <span className="text-slate-200 font-bold block mb-1">DATA PROVENANCE & KEYS:</span>
                    To connect external live APIs, copy <code className="text-orange-300">backend/.env.example</code> to <code className="text-orange-300">backend/.env</code> and supply your Neo4j credentials, Sarvam API key, or Open Charge Map key. When keys are omitted, the application runs entirely offline using validated deterministic fallbacks.
                  </div>
                </div>
              ) : (
                <div className="p-4 bg-rose-500/10 border border-rose-500/30 rounded-lg text-rose-300">
                  Failed to fetch provider status from FastAPI server. Verify the backend is running.
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-5 py-3 border-t border-[#1e2535] bg-[#131926] flex items-center justify-between">
              <button
                type="button"
                onClick={loadProviders}
                className="text-xs font-mono text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1"
              >
                <Activity size={12} /> Refresh Status
              </button>
              <button
                type="button"
                onClick={() => setShowProvidersModal(false)}
                className="px-4 py-1.5 rounded-lg bg-[#1e2535] hover:bg-[#283248] text-white text-xs font-medium transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
