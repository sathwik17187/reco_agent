import React, { useState, useEffect } from 'react';
import { PlayCircle, Cpu, Zap, Terminal, RefreshCw, CheckCircle2, AlertCircle, MessageSquare } from 'lucide-react';
import { SimulationRequest, SimulationResponse } from '../types';
import { simulateEvent, triggerPipeline, fetchPipelineStatus } from '../api';
import { StatusBadge } from './StatusBadge';

export const LiveSimulator: React.FC = () => {
  // Simulator state
  const [formData, setFormData] = useState<SimulationRequest>({
    event_type: 'failed_payment',
    customer_id: 'cust_live_99',
    amount: 45000,
    failure_code: 'card_expired',
    customer_segment: 'sme',
    dnc_flag: false,
    intent_score: 0.85,
  });

  const [simResult, setSimResult] = useState<SimulationResponse | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);

  // Pipeline state
  const [pipelineState, setPipelineState] = useState<{
    is_running: boolean;
    logs: string[];
    error: string | null;
  }>({ is_running: false, logs: [], error: null });

  // Handle Simulation submit
  const handleSimulate = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSimulating(true);
    try {
      const res = await simulateEvent(formData);
      setSimResult(res);
    } catch (err) {
      console.error(err);
    } finally {
      setIsSimulating(false);
    }
  };

  // Poll pipeline status
  useEffect(() => {
    const interval = setInterval(() => {
      fetchPipelineStatus()
        .then((st) => setPipelineState(st))
        .catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleRunPipeline = async () => {
    try {
      await triggerPipeline();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-300 pb-12">
      
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-purple-950/60 via-slate-900 to-slate-950 p-6 rounded-2xl border border-purple-500/20 glass-panel flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-purple-400" />
            <h2 className="text-xl font-bold text-white tracking-tight">Interactive Recovery Sandbox & Pipeline</h2>
          </div>
          <p className="text-xs text-slate-300 mt-1">
            Test agent decision rules on custom payment events or execute the full python pipeline end-to-end.
          </p>
        </div>

        <button
          onClick={handleRunPipeline}
          disabled={pipelineState.is_running}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white font-bold text-xs shadow-lg shadow-sky-600/30 transition-all disabled:opacity-50"
        >
          {pipelineState.is_running ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Pipeline Running...
            </>
          ) : (
            <>
              <PlayCircle className="w-4 h-4" />
              Run Full Agent Pipeline
            </>
          )}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Column: Form Simulator */}
        <div className="lg:col-span-5 glass-panel p-6 rounded-2xl border border-slate-800 space-y-6">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Cpu className="w-4 h-4 text-sky-400" />
              Single Event Test Sandbox
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">Input transaction details to view instant agent decisioning</p>
          </div>

          <form onSubmit={handleSimulate} className="space-y-4 text-xs">
            
            <div>
              <label className="text-slate-300 font-semibold block mb-1">Event Type</label>
              <select
                value={formData.event_type}
                onChange={(e) => setFormData({ ...formData, event_type: e.target.value })}
                className="w-full bg-slate-900 text-slate-200 p-2.5 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none"
              >
                <option value="failed_payment">Failed Payment</option>
                <option value="abandoned_checkout">Abandoned Checkout</option>
                <option value="overdue_invoice">Overdue Invoice</option>
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-slate-300 font-semibold block mb-1">Customer Segment</label>
                <select
                  value={formData.customer_segment}
                  onChange={(e) => setFormData({ ...formData, customer_segment: e.target.value })}
                  className="w-full bg-slate-900 text-slate-200 p-2.5 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none"
                >
                  <option value="retail">Retail</option>
                  <option value="sme">SME</option>
                  <option value="enterprise">Enterprise</option>
                </select>
              </div>

              <div>
                <label className="text-slate-300 font-semibold block mb-1">Amount (INR ₹)</label>
                <input
                  type="number"
                  value={formData.amount}
                  onChange={(e) => setFormData({ ...formData, amount: parseFloat(e.target.value) || 0 })}
                  className="w-full bg-slate-900 text-slate-200 p-2.5 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none font-mono"
                />
              </div>
            </div>

            <div>
              <label className="text-slate-300 font-semibold block mb-1">Failure Code / Reason</label>
              <select
                value={formData.failure_code}
                onChange={(e) => setFormData({ ...formData, failure_code: e.target.value })}
                className="w-full bg-slate-900 text-slate-200 p-2.5 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none"
              >
                <option value="card_expired">Card Expired (card_expired)</option>
                <option value="invalid_cvv">Invalid CVV (invalid_cvv)</option>
                <option value="gateway_timeout">Gateway Timeout (gateway_timeout)</option>
                <option value="insufficient_funds">Insufficient Funds (insufficient_funds)</option>
                <option value="soft_decline">Soft Decline (soft_decline)</option>
              </select>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-900 border border-slate-800">
              <span className="text-slate-300 font-medium">Do-Not-Contact (DNC) Flag</span>
              <input
                type="checkbox"
                checked={formData.dnc_flag}
                onChange={(e) => setFormData({ ...formData, dnc_flag: e.target.checked })}
                className="w-4 h-4 accent-sky-500 rounded cursor-pointer"
              />
            </div>

            <button
              type="submit"
              disabled={isSimulating}
              className="w-full py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-bold transition-all shadow-md shadow-sky-600/30 flex items-center justify-center gap-2"
            >
              {isSimulating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              Simulate Intervention Path
            </button>
          </form>
        </div>

        {/* Right Column: Simulation Output or Pipeline Terminal Logs */}
        <div className="lg:col-span-7 space-y-6">
          
          {/* Simulation Output Card */}
          {simResult && (
            <div className="glass-panel p-6 rounded-2xl border border-slate-800 space-y-4 animate-in fade-in">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  Agent Decision Path & Sequence Result
                </h4>
                <StatusBadge status={simResult.detection.risk_level} type="risk" />
              </div>

              <div className="grid grid-cols-2 gap-4 text-xs">
                <div className="bg-slate-900 p-3.5 rounded-xl border border-slate-800">
                  <span className="text-slate-400 block font-semibold">Detection Category</span>
                  <span className="text-sm font-bold text-sky-400 mt-1 block">{simResult.detection.category}</span>
                </div>
                <div className="bg-slate-900 p-3.5 rounded-xl border border-slate-800">
                  <span className="text-slate-400 block font-semibold">Max Retry Schedule</span>
                  <span className="text-sm font-bold text-amber-400 mt-1 block">{simResult.policy.max_retries} attempts allowed</span>
                </div>
              </div>

              <div className="space-y-2">
                <span className="text-xs font-bold text-slate-300 block uppercase">Policy Intervention Sequence</span>
                <div className="flex flex-wrap gap-2">
                  {simResult.policy.intervention_sequence.map((step, i) => (
                    <span key={i} className="bg-sky-950 text-sky-300 border border-sky-800/60 px-3 py-1 rounded-lg text-xs font-mono">
                      {i + 1}. {step}
                    </span>
                  ))}
                </div>
              </div>

              <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 space-y-2">
                <span className="text-xs font-bold text-emerald-400 flex items-center gap-1.5">
                  <MessageSquare className="w-3.5 h-3.5" />
                  Generated WhatsApp Hinglish Nudge
                </span>
                <p className="text-xs text-slate-200 bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono whitespace-pre-wrap">
                  {simResult.previews.whatsapp}
                </p>
              </div>
            </div>
          )}

          {/* Terminal / Logs Box */}
          <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
                <Terminal className="w-4 h-4 text-slate-400" />
                Live Agent Execution Logs
              </h4>
              {pipelineState.is_running && (
                <span className="text-[10px] bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded-md font-mono animate-pulse">
                  Streaming logs...
                </span>
              )}
            </div>

            <div className="bg-[#050811] p-4 rounded-xl border border-slate-800 font-mono text-xs text-slate-300 h-64 overflow-y-auto space-y-1">
              {pipelineState.logs.length === 0 ? (
                <p className="text-slate-600 italic">No active logs. Click "Run Full Agent Pipeline" above to execute.</p>
              ) : (
                pipelineState.logs.map((line, idx) => (
                  <div key={idx} className="hover:bg-slate-900/60 py-0.5 px-1 rounded">
                    {line}
                  </div>
                ))
              )}
            </div>
          </div>

        </div>

      </div>

    </div>
  );
};
