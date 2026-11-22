import React from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from 'lucide-react';

export interface ToastMessage {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  title?: string;
  message: string;
  duration?: number;
}

interface Props {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
}

export default function ToastContainer({ toasts, onDismiss }: Props) {
  if (toasts.length === 0) return null;

  return (
    <aside 
      aria-label="Notifications"
      className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm w-full pointer-events-none px-3"
    >
      {toasts.map(toast => {
        const isSuccess = toast.type === 'success';
        const isError = toast.type === 'error';
        const isWarning = toast.type === 'warning';

        const bg = isSuccess
          ? 'bg-emerald-50 border-emerald-200 text-emerald-950'
          : isError
            ? 'bg-rose-50 border-rose-200 text-rose-950'
            : isWarning
              ? 'bg-amber-50 border-amber-200 text-amber-950'
              : 'bg-sky-50 border-sky-200 text-sky-950';

        const iconColor = isSuccess
          ? 'text-emerald-600'
          : isError
            ? 'text-rose-600'
            : isWarning
              ? 'text-amber-600'
              : 'text-sky-600';

        const Icon = isSuccess
          ? CheckCircle2
          : isError
            ? XCircle
            : isWarning
              ? AlertTriangle
              : Info;

        return (
          <div
            key={toast.id}
            role="status"
            aria-live="polite"
            className={`pointer-events-auto flex items-start gap-3 p-3.5 rounded-2xl border shadow-lg backdrop-blur-md transition-all animate-slide-up ${bg}`}
          >
            <div className={`shrink-0 mt-0.5 ${iconColor}`}>
              <Icon size={18} />
            </div>
            <div className="flex-1 min-w-0">
              {toast.title && (
                <h4 className="text-xs font-bold font-mono uppercase tracking-wider mb-0.5">
                  {toast.title}
                </h4>
              )}
              <p className="text-xs leading-relaxed font-sans font-medium break-words">
                {toast.message}
              </p>
            </div>
            <button
              type="button"
              onClick={() => onDismiss(toast.id)}
              aria-label="Dismiss notification"
              className="shrink-0 p-1 rounded-lg text-slate-400 hover:text-slate-700 transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </aside>
  );
}
