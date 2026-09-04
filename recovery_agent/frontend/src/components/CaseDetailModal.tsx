import React, { useState, useEffect } from 'react';
import { X, ShieldAlert, FileText, Cpu, MessageSquare, CheckCircle, Clock, ExternalLink, RefreshCw } from 'lucide-react';
import { RecordDetailResponse } from '../types';
import { fetchRecordDetail } from '../api';
import { StatusBadge } from './StatusBadge';

interface CaseDetailModalProps {
  recordId: string | null;
  onClose: () => void;
}

export const CaseDetailModal: React.FC<CaseDetailModalProps> = ({ recordId, onClose }) => {
  const [detail, setDetail] = useState<RecordDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState<'timeline' | 'diagnosis' | 'comm'>('timeline');

  useEffect(() => {
    if (!recordId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    fetchRecordDetail(recordId)
      .then((data) => setDetail(data))
      .catch((err) => console.error(err))
      .finally(() => setLoading(false));
  }, [recordId]);

  if (!recordId) return null;

  const formatINR = (val: number) => {
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(val);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 sm:p-6 overflow-y-auto animate-in fade-in duration-200">
      <div className="bg-[#0F172A] border border-slate-700/80 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        
        {/* Modal Header */}
        <div className="p-6 border-b border-slate-800 bg-slate-900/80 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-bold text-white font-mono">{recordId}</h2>
              {detail && <StatusBadge status={detail.record.final_status} type="status" />}
            </div>
            {detail && (
              <div className="flex items-center gap-3 mt-2 text-xs text-slate-400">
                <span>Type: <strong className="text-slate-200 uppercase">{detail.record.event_type.replace('_', ' ')}</strong></span>
                <span>•</span>
                <span>Segment: <strong className="text-slate-200 uppercase">{detail.record.customer_segment}</strong></span>
                <span>•</span>
                <span>Amount: <strong className="text-emerald-400 font-mono text-sm">{formatINR(detail.record.amount)}</strong></span>
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-all"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Loading state */}
        {loading ? (
          <div className="p-16 text-center text-slate-400 flex flex-col items-center gap-3">
            <RefreshCw className="w-8 h-8 text-sky-400 animate-spin" />
            <p className="text-sm">Fetching complete audit history & diagnosis...</p>
          </div>
        ) : !detail ? (
          <div className="p-12 text-center text-slate-400">Failed to load record details.</div>
        ) : (
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            
            {/* Detection Summary Box */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-slate-900/60 p-4 rounded-xl border border-slate-800">
              <div>
                <span className="text-[11px] text-slate-400 uppercase font-semibold block">Risk Category</span>
                <span className="text-sm font-bold text-white mt-1 block">{detail.record.detection_category.replace(/_/g, ' ')}</span>
              </div>
              <div>
                <span className="text-[11px] text-slate-400 uppercase font-semibold block">Risk Level</span>
                <div className="mt-1">
                  <StatusBadge status={detail.record.risk_level} type="risk" />
                </div>
              </div>
              <div>
                <span className="text-[11px] text-slate-400 uppercase font-semibold block">Rules Fired</span>
                <span className="text-xs text-sky-300 font-mono mt-1 block truncate">
                  {detail.record.rules_fired?.join(', ') || 'Rule-based detection'}
                </span>
              </div>
            </div>

            {/* Sub-tab Navigation */}
            <div className="flex border-b border-slate-800 gap-6">
              <button
                onClick={() => setActiveSubTab('timeline')}
                className={`pb-3 text-xs font-bold flex items-center gap-2 border-b-2 transition-all ${
                  activeSubTab === 'timeline'
                    ? 'border-sky-400 text-sky-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Clock className="w-4 h-4" />
                Execution Timeline ({detail.record.actions_taken.length})
              </button>

              <button
                onClick={() => setActiveSubTab('diagnosis')}
                className={`pb-3 text-xs font-bold flex items-center gap-2 border-b-2 transition-all ${
                  activeSubTab === 'diagnosis'
                    ? 'border-sky-400 text-sky-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Cpu className="w-4 h-4" />
                RAG & LLM Diagnosis
              </button>

              <button
                onClick={() => setActiveSubTab('comm')}
                className={`pb-3 text-xs font-bold flex items-center gap-2 border-b-2 transition-all ${
                  activeSubTab === 'comm'
                    ? 'border-sky-400 text-sky-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <MessageSquare className="w-4 h-4" />
                Hinglish Nudge Preview
              </button>
            </div>

            {/* TAB 1: TIMELINE */}
            {activeSubTab === 'timeline' && (
              <div className="space-y-4">
                <p className="text-xs text-slate-400">Chronological sequence of intervention nodes executed by LangGraph:</p>
                <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
                  {detail.record.actions_taken.map((act, idx) => (
                    <div key={idx} className="relative group">
                      {/* Node Bullet */}
                      <span className={`absolute -left-6 top-1 w-4 h-4 rounded-full border-2 bg-slate-950 flex items-center justify-center ${
                        act.outcome === 'recovered' ? 'border-emerald-500 text-emerald-400' : 'border-sky-500 text-sky-400'
                      }`}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                      </span>

                      <div className="bg-slate-900/90 p-4 rounded-xl border border-slate-800 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs font-bold text-sky-300">
                            Action #{idx + 1}: <code className="text-white">{act.action}</code>
                          </span>
                          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                            act.outcome === 'recovered' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-slate-800 text-slate-300'
                          }`}>
                            Outcome: {act.outcome}
                          </span>
                        </div>

                        <p className="text-xs text-slate-300">{act.reason}</p>

                        <div className="flex items-center justify-between text-[11px] text-slate-500 pt-2 border-t border-slate-800/60">
                          <span>Logged at: {new Date(act.logged_at).toLocaleTimeString()}</span>
                          {act.revenue_recovered > 0 && (
                            <span className="text-emerald-400 font-bold font-mono">
                              + {formatINR(act.revenue_recovered)} Recovered
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* TAB 2: DIAGNOSIS & RAG */}
            {activeSubTab === 'diagnosis' && (
              <div className="space-y-6">
                
                {/* LLM Diagnosis */}
                <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 space-y-3">
                  <div className="flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-purple-400" />
                    <h3 className="text-xs font-bold text-white uppercase">LLM Root Cause Diagnosis (Ollama)</h3>
                  </div>
                  {detail.record.diagnosis ? (
                    <div className="space-y-2 text-xs">
                      <p className="text-slate-200 bg-slate-950 p-3 rounded-lg border border-slate-800/80">
                        {detail.record.diagnosis.root_cause}
                      </p>
                      <div className="flex items-center gap-4 text-slate-400">
                        <span>Confidence: <strong className="text-white">{((detail.record.diagnosis.confidence || 0.85) * 100).toFixed(0)}%</strong></span>
                        <span>Fallback Mode: <strong className="text-sky-400">{detail.record.diagnosis.fallback ? 'Yes' : 'No'}</strong></span>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 italic">No ambiguous LLM diagnosis required for this rule-classified event.</p>
                  )}
                </div>

                {/* RAG Policy Snippets */}
                <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 space-y-3">
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-sky-400" />
                    <h3 className="text-xs font-bold text-white uppercase">Retrieved Policy Documentation Snippets (ChromaDB RAG)</h3>
                  </div>
                  {detail.record.rag_snippets && detail.record.rag_snippets.length > 0 ? (
                    <div className="space-y-2">
                      {detail.record.rag_snippets.map((snip, idx) => (
                        <div key={idx} className="bg-slate-950 p-3 rounded-lg border border-slate-800 font-mono text-[11px] text-slate-300">
                          {snip}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 italic">Deterministic policy table applied directly for category rule.</p>
                  )}
                </div>

              </div>
            )}

            {/* TAB 3: HINGLISH NUDGE PREVIEW */}
            {activeSubTab === 'comm' && (
              <div className="space-y-6">
                
                {/* Mock Phone WhatsApp Chat Box */}
                <div className="max-w-md mx-auto bg-[#0B141A] rounded-2xl border border-slate-800 overflow-hidden shadow-2xl">
                  <div className="bg-[#202C33] px-4 py-3 flex items-center gap-3 border-b border-slate-800">
                    <div className="w-8 h-8 rounded-full bg-emerald-600 text-white flex items-center justify-center font-bold text-xs">
                      RZP
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-white">Razorpay Recovery Assistant</h4>
                      <span className="text-[10px] text-emerald-400">Official Merchant Account</span>
                    </div>
                  </div>

                  <div className="p-4 space-y-3 bg-[radial-gradient(#1f2937_1px,transparent_1px)] [background-size:16px_16px]">
                    <div className="bg-[#005C4B] text-slate-100 p-3.5 rounded-2xl rounded-tl-none max-w-[85%] text-xs space-y-2 shadow-md">
                      <p className="whitespace-pre-wrap leading-relaxed">{detail.previews.whatsapp}</p>
                      <span className="text-[10px] text-emerald-200/70 block text-right">Just now • Read</span>
                    </div>
                  </div>
                </div>

                {/* SMS Preview Box */}
                <div className="max-w-md mx-auto bg-slate-900 p-4 rounded-xl border border-slate-800 space-y-2">
                  <span className="text-[11px] font-bold text-slate-400 uppercase block">SMS Nudge Format</span>
                  <div className="bg-slate-950 p-3 rounded-lg text-xs font-mono text-slate-200 border border-slate-800">
                    {detail.previews.sms}
                  </div>
                </div>

              </div>
            )}

          </div>
        )}

        {/* Modal Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/80 flex items-center justify-between text-xs text-slate-400">
          <span>Razorpay Recovery Agent v1.0</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-white font-semibold transition-all"
          >
            Close Detail
          </button>
        </div>

      </div>
    </div>
  );
};
