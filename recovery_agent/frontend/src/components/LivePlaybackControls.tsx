import React, { useState } from 'react';
import { Play, Pause, SkipForward, FastForward, RotateCcw, Activity, Gauge, Zap, CheckCircle2, AlertTriangle } from 'lucide-react';
import { LiveAgentState, PlaybackSpeed, CustomerRecord } from '../types';

interface LivePlaybackControlsProps {
  state: LiveAgentState | null;
  onStart: (speed_ms?: number) => void;
  onPause: () => void;
  onStep: () => void;
  onReset: () => void;
  onFastForward: (count: number) => void;
  isProcessing?: boolean;
}

export const LivePlaybackControls: React.FC<LivePlaybackControlsProps> = ({
  state,
  onStart,
  onPause,
  onStep,
  onReset,
  onFastForward,
  isProcessing = false,
}) => {
  const [speed, setSpeed] = useState<PlaybackSpeed>(250);

  const isStreaming = state?.is_streaming || false;
  const current = state?.current_index || 0;
  const total = state?.total_records || 1000;
  const progressPct = state?.progress_pct || (total > 0 ? (current / total) * 100 : 0);
  const latest: CustomerRecord | null = state?.latest_record || null;

  const handleSpeedChange = (newSpeed: PlaybackSpeed) => {
    setSpeed(newSpeed);
    if (isStreaming) {
      onStart(newSpeed);
    }
  };

  const formatINR = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val);
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800/90 rounded-2xl p-5 backdrop-blur-xl shadow-2xl space-y-5">
      
      {/* Top Controller Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        
        {/* Left: Stream Status & Title */}
        <div className="flex items-center gap-3.5">
          <div className="relative flex items-center justify-center">
            {isStreaming ? (
              <>
                <span className="animate-ping absolute inline-flex h-4 w-4 rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500" />
              </>
            ) : current > 0 && current >= total ? (
              <span className="relative inline-flex rounded-full h-3 w-3 bg-sky-500" />
            ) : current > 0 ? (
              <span className="relative inline-flex rounded-full h-3 w-3 bg-amber-500" />
            ) : (
              <span className="relative inline-flex rounded-full h-3 w-3 bg-slate-500" />
            )}
          </div>

          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-white tracking-wide">Live Agent Playback & Sequential Engine</h3>
              <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${
                isStreaming
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                  : current >= total
                  ? 'bg-sky-500/10 text-sky-400 border-sky-500/30'
                  : current > 0
                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                  : 'bg-slate-800 text-slate-400 border-slate-700'
              }`}>
                {isStreaming ? 'Streaming Row-by-Row' : current >= total ? 'Dataset Finished' : current > 0 ? 'Playback Paused' : 'Ready (1,000 Records)'}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Processes dataset rows one by one, updating metrics, charts, bandit arms, and decision tables in real-time.
            </p>
          </div>
        </div>

        {/* Right: Primary Action Buttons */}
        <div className="flex flex-wrap items-center gap-2.5">
          
          {/* Play / Pause Toggle */}
          {isStreaming ? (
            <button
              onClick={onPause}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-xs font-bold transition-all shadow-md active:scale-95"
              title="Pause Live Stream"
            >
              <Pause className="w-4 h-4 fill-amber-300" />
              <span>Pause</span>
            </button>
          ) : (
            <button
              onClick={() => onStart(speed)}
              disabled={current >= total}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-bold transition-all shadow-lg shadow-emerald-900/30 active:scale-95 disabled:opacity-50"
              title="Stream Row-by-Row"
            >
              <Play className="w-4 h-4 fill-white" />
              <span>{current === 0 ? 'Start Live Stream' : 'Resume Stream'}</span>
            </button>
          )}

          {/* Step 1 Record */}
          <button
            onClick={onStep}
            disabled={isStreaming || current >= total || isProcessing}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold transition-all active:scale-95 disabled:opacity-40"
            title="Step next 1 row from dataset"
          >
            <SkipForward className="w-3.5 h-3.5 text-sky-400" />
            <span>Step Next Row</span>
          </button>

          {/* Fast-Forward +50 */}
          <button
            onClick={() => onFastForward(50)}
            disabled={isStreaming || current >= total || isProcessing}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 text-xs font-medium transition-all active:scale-95 disabled:opacity-40"
            title="Fast-forward next 50 rows instantly"
          >
            <FastForward className="w-3.5 h-3.5" />
            <span>+50 Rows</span>
          </button>

          {/* Reset */}
          <button
            onClick={onReset}
            disabled={isStreaming || current === 0}
            className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-slate-200 border border-slate-700/80 transition-all active:scale-95 disabled:opacity-30"
            title="Reset to Record 0"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>

          {/* Speed Pills */}
          <div className="flex items-center bg-slate-950/70 border border-slate-800 rounded-xl p-0.5 ml-1">
            <span className="text-[10px] text-slate-500 px-2 font-medium flex items-center gap-1">
              <Gauge className="w-3 h-3 text-slate-400" />
              Speed
            </span>
            {([
              { label: '0.5x', val: 1000 },
              { label: '1x', val: 500 },
              { label: '2x', val: 250 },
              { label: '5x', val: 100 },
              { label: 'Turbo', val: 30 },
            ] as const).map((s) => (
              <button
                key={s.val}
                onClick={() => handleSpeedChange(s.val)}
                className={`text-[11px] font-bold px-2 py-1 rounded-lg transition-all ${
                  speed === s.val
                    ? 'bg-sky-500 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>

        </div>

      </div>

      {/* Progress Bar & Counter */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-sky-400" />
            <span className="font-semibold text-slate-200">
              Dataset Ingestion Progress:
            </span>
            <span className="font-mono text-sky-400 font-bold">
              {current.toLocaleString()} / {total.toLocaleString()} rows
            </span>
          </div>
          <span className="font-mono font-bold text-slate-400">
            {progressPct.toFixed(1)}%
          </span>
        </div>

        <div className="w-full bg-slate-950 rounded-full h-2.5 overflow-hidden border border-slate-800">
          <div
            className="h-full bg-gradient-to-r from-sky-500 via-indigo-500 to-emerald-400 transition-all duration-300 rounded-full shadow-sm shadow-sky-500/50"
            style={{ width: `${Math.min(100, Math.max(0, progressPct))}%` }}
          />
        </div>
      </div>

      {/* Real-time Agent Decision HUD (Latest Record Ticker) */}
      {latest && (
        <div className="bg-slate-950/80 border border-sky-500/20 rounded-xl p-3.5 flex flex-col md:flex-row items-start md:items-center justify-between gap-3 animate-in fade-in slide-in-from-top-1 duration-200">
          
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <Zap className="w-4 h-4 text-amber-400" />
              <span className="text-xs font-mono font-bold text-white">{latest.record_id}</span>
              <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                {latest.customer_segment}
              </span>
            </div>

            <div className="h-3 w-px bg-slate-800 hidden md:block" />

            <div className="text-xs text-slate-300">
              Risk: <span className="font-semibold text-sky-300">{latest.detection_category.replace(/_/g, ' ')}</span>
            </div>

            <div className="h-3 w-px bg-slate-800 hidden md:block" />

            <div className="text-xs text-slate-300">
              Policy Action: <span className="font-mono text-indigo-300 font-semibold">{latest.actions_taken?.[0]?.action || 'analyze'}</span>
            </div>

            {latest.bandit_arm && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-300 border border-purple-500/30">
                LinUCB: {latest.bandit_arm}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3 self-end md:self-center">
            <div className="text-right">
              <p className="text-[10px] text-slate-400 font-medium">Value at Risk</p>
              <p className="text-xs font-bold text-slate-200">{formatINR(latest.amount)}</p>
            </div>

            <div className={`px-2.5 py-1 rounded-lg text-xs font-bold flex items-center gap-1.5 border ${
              latest.final_status === 'recovered'
                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                : latest.final_status === 'escalated'
                ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
                : latest.final_status === 'skipped'
                ? 'bg-slate-800 text-slate-400 border-slate-700'
                : 'bg-rose-500/20 text-rose-400 border-rose-500/30'
            }`}>
              {latest.final_status === 'recovered' ? (
                <>
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Recovered {formatINR(latest.total_recovered)}</span>
                </>
              ) : latest.final_status === 'escalated' ? (
                <>
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>Escalated to Human</span>
                </>
              ) : latest.final_status === 'skipped' ? (
                <span>Skipped (DNC)</span>
              ) : (
                <span>Unresolved</span>
              )}
            </div>
          </div>

        </div>
      )}

    </div>
  );
};
