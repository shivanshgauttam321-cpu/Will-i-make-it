import React, { useEffect, useRef } from 'react';
import { 
  X, Navigation, CheckCircle2, BarChart3, Zap, Mic, Radio, Database,
  Volume2, VolumeX, RotateCcw, Activity, ShieldCheck, ChevronRight
} from 'lucide-react';
import type { ActiveView } from './NavigationRail';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  activeView: ActiveView | '404';
  onViewChange: (view: ActiveView) => void;
  disabledChargersCount: number;
  soundOn: boolean;
  onToggleSound: () => void;
  backendOk: boolean | null;
  neo4jOk: boolean;
  onReplayIntro: () => void;
  onOpenSystemStatus: () => void;
}

export default function MobileDrawer({
  isOpen,
  onClose,
  activeView,
  onViewChange,
  disabledChargersCount,
  soundOn,
  onToggleSound,
  backendOk,
  neo4jOk,
  onReplayIntro,
  onOpenSystemStatus,
}: Props) {
  const drawerRef = useRef<HTMLDivElement | null>(null);

  // Close on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Prevent background scrolling when drawer is open
  useEffect(() => {
    if (isOpen) {
      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = originalOverflow;
      };
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const navItems: { id: ActiveView; label: string; desc: string; icon: React.ReactNode; badge?: number }[] = [
    {
      id: 'planner',
      label: 'Trip Planner',
      desc: 'Origin, destination, EV profile & ambient conditions',
      icon: <Navigation size={20} />,
    },
    {
      id: 'results',
      label: 'Journey Results',
      desc: 'Feasibility verdict, battery gauge & planned charging stops',
      icon: <CheckCircle2 size={20} />,
    },
    {
      id: 'energy',
      label: 'Battery Analytics',
      desc: 'Discharge trajectory curves, aerodynamic & rolling forces',
      icon: <BarChart3 size={20} />,
    },
    {
      id: 'chargers',
      label: 'Charging Stations',
      desc: 'Bayesian reliability engine & interactive outage simulation',
      icon: <Zap size={20} />,
      badge: disabledChargersCount > 0 ? disabledChargersCount : undefined,
    },
    {
      id: 'voice',
      label: 'Voice AI Cockpit',
      desc: 'Multilingual voice assistant powered by Sarvam AI',
      icon: <Mic size={20} />,
    },
    {
      id: 'explain',
      label: 'Simulation Explained',
      desc: 'First-principles physics breakdown & bilingual speech',
      icon: <Radio size={20} />,
    },
    {
      id: 'graph',
      label: 'Graph Intelligence',
      desc: 'Neo4j Aura live topology, corridor sync & event log',
      icon: <Database size={20} />,
    },
  ];

  const handleItemClick = (id: ActiveView) => {
    onViewChange(id);
    onClose();
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex lg:hidden bg-slate-900/40 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Mobile Navigation Menu"
    >
      <div 
        ref={drawerRef}
        onClick={e => e.stopPropagation()}
        className="w-[85%] max-w-sm h-full bg-white border-r border-[#E2E8F0] shadow-2xl flex flex-col justify-between overflow-y-auto animate-slide-right"
      >
        {/* Drawer Header */}
        <div className="p-4 border-b border-[#E2E8F0] flex items-center justify-between bg-[#F8FAFC]">
          <div 
            onClick={() => { handleItemClick('planner'); }}
            className="flex items-center gap-2.5 cursor-pointer"
            role="button"
            tabIndex={0}
            aria-label="Navigate to Trip Planner home"
            onKeyDown={e => e.key === 'Enter' && handleItemClick('planner')}
          >
            <div className="w-8 h-8 rounded-xl bg-white border border-[#E2E8F0] flex items-center justify-center shadow-sm">
              <img 
                src="/assets/logo/will-i-make-it.svg" 
                alt="Logo" 
                width="22" 
                height="22" 
                className="w-5 h-5" 
              />
            </div>
            <div>
              <h2 className="text-sm font-bold tracking-tight text-[#172033] font-sans">
                WILL I MAKE IT?
              </h2>
              <span className="text-[10px] text-orange-600 font-mono font-semibold block leading-tight">
                EV INTELLIGENCE
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close mobile navigation menu"
            className="p-1.5 rounded-xl text-[#64748B] hover:text-[#172033] hover:bg-[#E2E8F0] transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Primary Navigation List */}
        <nav aria-label="Mobile Main Navigation" className="p-3 space-y-1.5 flex-1">
          {navItems.map(item => {
            const isActive = activeView === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => handleItemClick(item.id)}
                className={`w-full flex items-center justify-between p-3 rounded-2xl text-left transition-all ${
                  isActive
                    ? 'bg-[#F97316] text-white shadow-md shadow-orange-500/20'
                    : 'text-[#172033] hover:bg-[#F8FAFC]'
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className={`shrink-0 ${isActive ? 'text-white' : 'text-[#F97316]'}`}>
                    {item.icon}
                  </div>
                  <div className="min-w-0">
                    <span className="text-xs font-bold font-sans block truncate">
                      {item.label}
                    </span>
                    <span className={`text-[10px] block truncate mt-0.5 ${isActive ? 'text-white/80' : 'text-[#64748B]'}`}>
                      {item.desc}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0 ml-2">
                  {item.badge !== undefined && item.badge > 0 && (
                    <span className="w-4 h-4 rounded-full bg-rose-500 text-white text-[9px] font-mono font-bold flex items-center justify-center">
                      {item.badge}
                    </span>
                  )}
                  <ChevronRight size={14} className={isActive ? 'text-white' : 'text-slate-300'} />
                </div>
              </button>
            );
          })}
        </nav>

        {/* Bottom Drawer Actions & Diagnostics */}
        <div className="p-4 border-t border-[#E2E8F0] bg-[#F8FAFC] space-y-3">
          {/* Quick controls row */}
          <div className="grid grid-cols-2 gap-2">
            {/* Audio Toggle */}
            <button
              type="button"
              onClick={onToggleSound}
              className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-xl border text-xs font-mono font-medium transition-all ${
                soundOn
                  ? 'bg-orange-50 border-orange-200 text-orange-700 font-bold'
                  : 'bg-white border-[#E2E8F0] text-[#64748B]'
              }`}
            >
              {soundOn ? <Volume2 size={14} /> : <VolumeX size={14} />}
              <span>{soundOn ? 'Sound ON' : 'Muted'}</span>
            </button>

            {/* Intro Replay */}
            <button
              type="button"
              onClick={() => {
                onClose();
                onReplayIntro();
              }}
              className="flex items-center justify-center gap-1.5 py-2 px-3 rounded-xl bg-white border border-[#E2E8F0] text-xs font-mono font-medium text-[#172033] hover:bg-[#F1F4F8] transition-all"
            >
              <RotateCcw size={14} className="text-orange-500" />
              <span>3D Intro</span>
            </button>
          </div>

          {/* System Status button */}
          <button
            type="button"
            onClick={() => {
              onClose();
              onOpenSystemStatus();
            }}
            className="w-full flex items-center justify-between p-2.5 rounded-xl bg-white border border-[#E2E8F0] text-xs font-medium text-[#172033] hover:bg-[#F1F4F8] transition-all"
          >
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${backendOk ? 'bg-emerald-500' : 'bg-rose-500'}`} />
              <span>System Health &amp; Providers</span>
            </div>
            <Activity size={14} className="text-slate-400" />
          </button>
        </div>
      </div>
    </div>
  );
}
