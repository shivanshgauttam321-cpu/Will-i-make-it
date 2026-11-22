import React from 'react';
import { Compass, ArrowLeft, Navigation, Zap, Home } from 'lucide-react';
import type { ActiveView } from './NavigationRail';

interface Props {
  onReturnToPlanner: () => void;
  onExploreStations: () => void;
}

export default function NotFoundPage({ onReturnToPlanner, onExploreStations }: Props) {
  return (
    <main className="flex-1 w-full flex items-center justify-center p-4 sm:p-8 animate-fade-in">
      <div className="max-w-md w-full bg-white border border-[#E2E8F0] rounded-3xl p-6 sm:p-8 text-center shadow-lg flex flex-col items-center">
        {/* Visual 404 Beacon */}
        <div className="w-16 h-16 sm:w-20 sm:h-20 rounded-2xl bg-orange-50 border border-orange-200 flex items-center justify-center text-[#F97316] mb-5 shadow-sm">
          <Compass size={36} className="animate-spin-slow" />
        </div>

        {/* 404 Badge */}
        <span className="text-xs font-mono font-bold tracking-widest uppercase bg-orange-50 text-orange-700 px-3 py-1 rounded-full border border-orange-200 mb-2">
          ERROR 404 &middot; CORRIDOR UNCHARTED
        </span>

        {/* Title */}
        <h1 className="text-xl sm:text-2xl font-black text-[#172033] tracking-tight font-sans mb-2">
          Page Not Found
        </h1>

        {/* Description */}
        <p className="text-xs sm:text-sm text-[#64748B] leading-relaxed mb-6 font-sans">
          The requested journey coordinate or application route does not exist in the EV navigation network. 
          Let&apos;s redirect your telemetry back to the active journey planner.
        </p>

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 w-full">
          <button
            type="button"
            onClick={onReturnToPlanner}
            className="flex-1 flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-[#F97316] hover:bg-[#EA580C] active:scale-95 text-white text-xs font-mono font-bold transition-all shadow-md shadow-orange-500/20"
          >
            <Navigation size={15} />
            <span>RETURN TO PLANNER</span>
          </button>

          <button
            type="button"
            onClick={onExploreStations}
            className="flex-1 flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-[#F8FAFC] hover:bg-[#F1F4F8] text-[#172033] border border-[#CBD5E1] text-xs font-mono font-medium transition-all shadow-sm"
          >
            <Zap size={15} className="text-orange-500" />
            <span>EXPLORE CHARGERS</span>
          </button>
        </div>
      </div>
    </main>
  );
}
