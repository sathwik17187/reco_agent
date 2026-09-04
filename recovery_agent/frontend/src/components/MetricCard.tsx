import React from 'react';
import { LucideIcon } from 'lucide-react';

interface MetricCardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon: LucideIcon;
  color: 'sky' | 'emerald' | 'amber' | 'rose' | 'purple';
  trend?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  color,
  trend,
}) => {
  const colorMap = {
    sky: 'border-sky-500/30 text-sky-400 bg-sky-500/10 shadow-sky-500/5',
    emerald: 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10 shadow-emerald-500/5',
    amber: 'border-amber-500/30 text-amber-400 bg-amber-500/10 shadow-amber-500/5',
    rose: 'border-rose-500/30 text-rose-400 bg-rose-500/10 shadow-rose-500/5',
    purple: 'border-purple-500/30 text-purple-400 bg-purple-500/10 shadow-purple-500/5',
  };

  const iconBgMap = {
    sky: 'bg-sky-500/20 text-sky-400 border-sky-500/30',
    emerald: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    amber: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    rose: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
    purple: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  };

  return (
    <div className={`p-5 rounded-2xl border glass-panel relative overflow-hidden transition-all duration-300 hover:-translate-y-1 hover:shadow-xl ${colorMap[color]}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</p>
          <h3 className="text-2xl font-extrabold text-white mt-1 tracking-tight">{value}</h3>
          {subtitle && <p className="text-xs text-slate-400 mt-1 font-medium">{subtitle}</p>}
        </div>
        <div className={`p-3 rounded-xl border ${iconBgMap[color]}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
      {trend && (
        <div className="mt-3 pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
          <span className="text-slate-400">Target / Benchmark</span>
          <span className="font-semibold text-emerald-400">{trend}</span>
        </div>
      )}
    </div>
  );
};
