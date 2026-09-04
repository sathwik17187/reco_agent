import React from 'react';

interface StatusBadgeProps {
  status: string;
  type?: 'status' | 'risk' | 'event' | 'segment';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, type = 'status' }) => {
  const getStyles = () => {
    const s = status.toLowerCase();

    if (type === 'risk') {
      if (s === 'high') return 'bg-rose-950/60 text-rose-400 border-rose-800/50';
      if (s === 'medium') return 'bg-amber-950/60 text-amber-400 border-amber-800/50';
      return 'bg-emerald-950/60 text-emerald-400 border-emerald-800/50';
    }

    if (type === 'event') {
      if (s === 'failed_payment') return 'bg-sky-950/60 text-sky-400 border-sky-800/50';
      if (s === 'abandoned_checkout') return 'bg-purple-950/60 text-purple-400 border-purple-800/50';
      return 'bg-indigo-950/60 text-indigo-400 border-indigo-800/50';
    }

    if (type === 'segment') {
      if (s === 'enterprise') return 'bg-violet-950/60 text-violet-400 border-violet-800/50';
      if (s === 'sme' || s === 'smb') return 'bg-cyan-950/60 text-cyan-400 border-cyan-800/50';
      return 'bg-slate-800 text-slate-300 border-slate-700';
    }

    // Default: Final Status
    switch (s) {
      case 'recovered':
        return 'bg-emerald-950/80 text-emerald-300 border-emerald-700/60 shadow-[0_0_12px_rgba(16,185,129,0.15)]';
      case 'escalated':
        return 'bg-amber-950/80 text-amber-300 border-amber-700/60 shadow-[0_0_12px_rgba(245,158,11,0.15)]';
      case 'still_failed':
      case 'failed':
        return 'bg-rose-950/80 text-rose-300 border-rose-700/60';
      case 'written_off':
        return 'bg-red-950/90 text-red-400 border-red-800/80';
      case 'skipped':
        return 'bg-slate-800 text-slate-400 border-slate-700';
      default:
        return 'bg-slate-800 text-slate-300 border-slate-700';
    }
  };

  const formatText = (text: string) => {
    return text.replace(/_/g, ' ').toUpperCase();
  };

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${getStyles()}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse"></span>
      {formatText(status)}
    </span>
  );
};
