import React, { useState, useEffect } from 'react';
import { Database, AlertTriangle, RotateCcw, Activity, X, ShieldCheck, CheckCircle2, Globe, Cpu, Radio, ExternalLink, Menu } from 'lucide-react';
import { getProvidersStatus } from '../utils/api';

interface Props {
  routeLabel?: string;
  distanceKm?: number;
  durationMin?: number;
  backendOk: boolean | null;
  neo4jOk: boolean;
  neo4jDiagnostic?: string;
  onReplayIntro: () => void;
  onOpenMobileMenu?: () => void;
  onLogoClick?: () => void;
  externalShowProvidersModal?: boolean;
  onCloseExternalProvidersModal?: () => void;
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
  onOpenMobileMenu,
  onLogoClick,
  externalShowProvidersModal,
  onCloseExternalProvidersModal,
}: Props) {
  const [showProvidersModal, setShowProvidersModal] = useState(false);
  const [providersData, setProvidersData] = useState<any | null>(null);
  const [loadingProviders, setLoadingProviders] = useState(false);

  const isModalOpen = showProvidersModal || !!externalShowProvidersModal;

  const handleCloseModal = () => {
    setShowProvidersModal(false);
    if (onCloseExternalProvidersModal) onCloseExternalProvidersModal();
  };

  useEffect(() => {
    if (isModalOpen && !providersData) {
      loadProviders();
    }
  }, [isModalOpen]);

  const loadProviders = () => {
    setLoadingProviders(true);
    getProvidersStatus()
      .then(res => setProvidersData(res))
      .catch(() => setProvidersData(null))
      .finally(() => setLoadingProviders(false));
  };

  return (
    <>
      <header className="border-b border-[#E2E8F0] bg-[#FFFFFF] px-3 sm:px-6 py-2.5 flex items-center justify-between gap-2 sm:gap-4 shrink-0 z-20 shadow-sm">
        {/* Mobile Hamburger + Brand Title & Active Corridor Subtitle */}
        <div className="flex items-center gap-2.5 sm:gap-3 min-w-0">
          {/* Hamburger Menu Button (visible on mobile / < lg) */}
          <button
            type="button"
            onClick={onOpenMobileMenu}
            aria-label="Open navigation menu"
            className="lg:hidden p-2 rounded-xl bg-[#F8FAFC] hover:bg-[#F1F4F8] text-[#172033] border border-[#E2E8F0] transition-colors shrink-0"
          >
            <Menu size={18} />
          </button>

          {/* Clickable Brand Logo & Title */}
          <div 
            onClick={onLogoClick}
            role="button"
            tabIndex={0}
            aria-label="Navigate to EV Journey Planner"
            onKeyDown={(e) => e.key === 'Enter' && onLogoClick && onLogoClick()}
            className="flex items-center gap-2.5 cursor-pointer group min-w-0"
          >
            <div className="w-8 h-8 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] flex items-center justify-center shrink-0 group-hover:border-orange-400 transition-colors shadow-sm">
              <img 
                src="/assets/logo/will-i-make-it.svg" 
                alt="Will I Make It? Logo" 
                width="22" 
                height="22" 
                className="w-5 h-5 transition-transform group-hover:scale-105" 
                loading="eager"
              />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 sm:gap-2">
                <h1 className="text-sm sm:text-base font-bold tracking-tight text-[#172033] font-sans flex items-center gap-1.5 sm:gap-2">
                  <span className="hidden xs:inline">WILL I MAKE IT?</span>
                  <span className="xs:hidden">WILL I MAKE IT?</span>
                  <span className="text-[10px] bg-orange-50 text-orange-600 font-mono font-semibold px-1.5 sm:px-2 py-0.5 rounded-full border border-orange-200">
                    EV
                  </span>
                </h1>
              </div>
              <div className="flex items-center gap-2 text-xs text-[#64748B] truncate">
                {routeLabel ? (
                  <span className="truncate">
                    Corridor: <span className="text-[#172033] font-medium">{routeLabel}</span>
                    {distanceKm !== undefined && (
                      <span className="text-orange-600 font-mono font-semibold ml-1.5">
                        ({distanceKm} km · ~{Math.round(durationMin ?? 0)} min)
                      </span>
                    )}
                  </span>
                ) : (
                  <span className="truncate">Explainable, Risk-Aware EV Route Planner</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Right-Side Status Badges (Clean, Compact Light SaaS Style) */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Replay 3D Intro Button */}
          <button
            type="button"
            onClick={onReplayIntro}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-[#F8FAFC] hover:bg-[#F1F4F8] text-[#64748B] hover:text-[#172033] border border-[#E2E8F0] text-xs font-medium transition-all hidden sm:inline-flex"
            title="Replay EV 3D Boot Scene"
          >
            <RotateCcw size={12} className="text-orange-500" />
            <span>Intro</span>
          </button>

          {/* Dedicated System Status & Diagnostics Trigger */}
          <button
            type="button"
            onClick={() => setShowProvidersModal(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-[#F8FAFC] hover:bg-[#F1F4F8] text-[#172033] border border-[#E2E8F0] text-xs font-medium transition-all"
            title="View Data Providers, API Keys & Graph Status"
          >
            <div className={`w-2 h-2 rounded-full ${
              backendOk ? 'bg-emerald-500' : 'bg-rose-500'
            }`} />
            <span>System Status</span>
          </button>
        </div>
      </header>

      {/* Providers & Provenance Details Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-[#FFFFFF] border border-[#E2E8F0] rounded-2xl max-w-2xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="px-5 py-4 border-b border-[#E2E8F0] flex items-center justify-between bg-[#F8FAFC]">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-orange-50 border border-orange-200 flex items-center justify-center text-orange-600">
                  <Activity size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-[#172033] tracking-tight">
                    External Data Providers & System Health
                  </h3>
                  <p className="text-xs text-[#64748B]">
                    Active integrations, knowledge graphs, AI voice models & provenance
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={handleCloseModal}
                className="p-1.5 rounded-lg text-[#64748B] hover:text-[#172033] hover:bg-[#E2E8F0] transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-5 overflow-y-auto space-y-4 text-xs font-sans text-[#172033]">
              {/* Physics Authority Notice */}
              <div className="p-3.5 bg-orange-50/80 border border-orange-200 rounded-xl flex items-start gap-3">
                <ShieldCheck size={18} className="text-orange-500 shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs font-bold text-orange-800 font-mono uppercase">
                    Physical Simulation Authority
                  </div>
                  <div className="text-xs text-orange-950/80 mt-0.5 leading-relaxed">
                    The core Python EV powertrain and battery physics simulator is the sole authority for physical feasibility, state of charge dynamics, and thermal limits. Neo4j, Sarvam AI, and external APIs supply contextual enrichment without altering physical laws.
                  </div>
                </div>
              </div>

              {loadingProviders ? (
                <div className="py-8 text-center text-[#64748B] font-mono">
                  Loading provider status and registry...
                </div>
              ) : providersData ? (
                <div className="space-y-3">
                  {/* Provider Cards */}
                  <div className="grid grid-cols-1 gap-2.5">
                    {/* Neo4j Graph Card */}
                    {providersData.providers?.neo4j && (
                      <div className="p-3.5 bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl">
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <Database size={15} className="text-indigo-600" />
                            <span className="font-semibold text-[#172033]">
                              {providersData.providers.neo4j.name}
                            </span>
                          </div>
                          <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                            providersData.providers.neo4j.status === 'UP' || providersData.providers.neo4j.status === 'CONNECTED'
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200 font-bold'
                              : providersData.providers.neo4j.status === 'DISABLED'
                                ? 'bg-slate-100 text-slate-600 border-slate-200'
                                : 'bg-rose-50 text-rose-700 border-rose-200'
                          }`}>
                            {providersData.providers.neo4j.status}
                          </span>
                        </div>
                        <div className="text-xs text-[#64748B]">
                          {providersData.providers.neo4j.details?.message || 
                            (providersData.providers.neo4j.enabled ? 'Connected to graph instance.' : 'Disabled in .env (Deterministic fallback active).')}
                        </div>
                        {providersData.providers.neo4j.details?.uri && (
                          <div className="mt-1 text-[11px] font-mono text-[#94A3B8]">
                            URI: {providersData.providers.neo4j.details.uri}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Sarvam AI Card */}
                    {providersData.providers?.sarvam_ai && (
                      <div className="p-3.5 bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl">
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <Radio size={15} className="text-violet-600" />
                            <span className="font-semibold text-[#172033]">
                              {providersData.providers.sarvam_ai.name}
                            </span>
                          </div>
                          <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                            providersData.providers.sarvam_ai.enabled
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200 font-bold'
                              : 'bg-amber-50 text-amber-700 border-amber-200'
                          }`}>
                            {providersData.providers.sarvam_ai.enabled ? 'ACTIVE API' : 'MOCK / FALLBACK MODE'}
                          </span>
                        </div>
                        <div className="text-xs text-[#64748B]">
                          {providersData.providers.sarvam_ai.details?.message || 'Bilingual Speech-to-Text & Text-to-Speech'}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : null}
            </div>

            {/* Modal Footer */}
            <div className="p-4 bg-[#F8FAFC] border-t border-[#E2E8F0] flex justify-end">
              <button
                type="button"
                onClick={handleCloseModal}
                className="px-4 py-2 rounded-xl bg-[#172033] hover:bg-[#0F172A] text-white text-xs font-semibold transition-all shadow-sm"
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
