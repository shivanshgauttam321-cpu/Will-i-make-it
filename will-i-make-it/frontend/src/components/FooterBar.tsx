import React from 'react';
import { ExternalLink, ShieldCheck, Heart, GitBranch, Compass, Zap, BarChart3, Radio } from 'lucide-react';
import type { ActiveView } from './NavigationRail';

interface Props {
  onViewChange: (view: ActiveView | '404') => void;
  onOpenSystemStatus: () => void;
  activeView: ActiveView | '404';
}

export default function FooterBar({ onViewChange, onOpenSystemStatus, activeView }: Props) {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="w-full bg-white border-t border-[#E2E8F0] px-4 sm:px-6 py-3 text-xs text-[#64748B] shrink-0 z-10 shadow-sm">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-3">
        {/* Left: Dynamic Copyright & Authority Notice */}
        <div className="flex items-center gap-2 flex-wrap justify-center md:justify-start text-center md:text-left">
          <span className="font-medium text-[#172033]">
            &copy; {currentYear} Will I Make It?
          </span>
          <span className="hidden sm:inline text-slate-300">&middot;</span>
          <span className="text-[#64748B]">
            EV Journey Feasibility &amp; Range Intelligence
          </span>
          <span className="hidden sm:inline text-slate-300">&middot;</span>
          <span className="inline-flex items-center gap-1 text-[11px] font-mono text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
            <ShieldCheck size={12} className="text-emerald-600" />
            C1.3 &amp; C2.1 Physics Verified
          </span>
        </div>

        {/* Center: Internal Working Navigation Links */}
        <nav aria-label="Footer Navigation" className="flex items-center gap-3 sm:gap-4 flex-wrap justify-center text-xs font-mono">
          <button
            type="button"
            onClick={() => onViewChange('planner')}
            className={`transition-colors hover:text-[#172033] ${activeView === 'planner' ? 'text-orange-600 font-bold' : ''}`}
          >
            Planner
          </button>
          <button
            type="button"
            onClick={() => onViewChange('results')}
            className={`transition-colors hover:text-[#172033] ${activeView === 'results' ? 'text-orange-600 font-bold' : ''}`}
          >
            Results
          </button>
          <button
            type="button"
            onClick={() => onViewChange('energy')}
            className={`transition-colors hover:text-[#172033] ${activeView === 'energy' ? 'text-orange-600 font-bold' : ''}`}
          >
            Energy
          </button>
          <button
            type="button"
            onClick={() => onViewChange('chargers')}
            className={`transition-colors hover:text-[#172033] ${activeView === 'chargers' ? 'text-orange-600 font-bold' : ''}`}
          >
            Stations
          </button>
          <button
            type="button"
            onClick={() => onViewChange('explain')}
            className={`transition-colors hover:text-[#172033] ${activeView === 'explain' ? 'text-orange-600 font-bold' : ''}`}
          >
            Explain
          </button>
          <button
            type="button"
            onClick={onOpenSystemStatus}
            className="transition-colors hover:text-[#172033] text-slate-500"
          >
            Status
          </button>
        </nav>

        {/* Right: Safe Verified External Link */}
        <div className="flex items-center gap-2">
          <a
            href="https://github.com/shivanshgauttam321-cpu/Will-i-make-it"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="View source repository on GitHub"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-[#F8FAFC] hover:bg-[#F1F4F8] text-[#172033] border border-[#E2E8F0] font-mono text-[11px] transition-all shadow-sm"
          >
            <GitBranch size={13} className="text-orange-500" />
            <span>GitHub Repository</span>
            <ExternalLink size={11} className="text-slate-400" />
          </a>
        </div>
      </div>
    </footer>
  );
}
