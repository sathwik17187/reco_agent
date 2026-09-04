import React, { useState, useEffect } from 'react';
import { BookOpen, FileText, Search, RefreshCw } from 'lucide-react';
import { PolicyItem } from '../types';
import { fetchPolicies } from '../api';

export const PolicyViewer: React.FC = () => {
  const [policies, setPolicies] = useState<PolicyItem[]>([]);
  const [selectedPolicy, setSelectedPolicy] = useState<PolicyItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    fetchPolicies()
      .then((data) => {
        setPolicies(data.policies);
        if (data.policies.length > 0) {
          setSelectedPolicy(data.policies[0]);
        }
      })
      .catch((err) => console.error(err))
      .finally(() => setLoading(false));
  }, []);

  const filteredPolicies = policies.filter((p) =>
    p.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
    p.content.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6 animate-in fade-in duration-300 pb-12">
      
      <div className="bg-gradient-to-r from-sky-950/60 via-slate-900 to-slate-950 p-6 rounded-2xl border border-sky-500/20 glass-panel">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-sky-400" />
          <h2 className="text-xl font-bold text-white tracking-tight">RAG Policy Knowledge Base</h2>
        </div>
        <p className="text-xs text-slate-300 mt-1">
          Vectorized policy documentation embedded in ChromaDB for high-accuracy RAG retrieval
        </p>
      </div>

      {loading ? (
        <div className="p-16 text-center text-slate-400 flex items-center justify-center gap-2">
          <RefreshCw className="w-5 h-5 animate-spin text-sky-400" />
          Loading policy documents...
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
          
          {/* Policy File List */}
          <div className="md:col-span-4 glass-panel p-4 rounded-2xl border border-slate-800 space-y-4">
            <div className="relative">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Search policy docs..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full bg-slate-900 text-xs text-slate-200 placeholder-slate-500 pl-9 pr-3 py-2 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none"
              />
            </div>

            <div className="space-y-2">
              {filteredPolicies.map((p) => (
                <button
                  key={p.filename}
                  onClick={() => setSelectedPolicy(p)}
                  className={`w-full text-left p-3 rounded-xl border text-xs transition-all flex items-center gap-3 ${
                    selectedPolicy?.filename === p.filename
                      ? 'bg-sky-600/20 border-sky-500 text-sky-300 shadow-md shadow-sky-500/10'
                      : 'bg-slate-900/60 border-slate-800/80 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                  }`}
                >
                  <FileText className="w-4 h-4 text-sky-400 flex-shrink-0" />
                  <div>
                    <h4 className="font-bold">{p.title}</h4>
                    <span className="text-[10px] text-slate-500 font-mono">{p.filename}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Policy Document Content Viewer */}
          <div className="md:col-span-8 glass-panel p-6 rounded-2xl border border-slate-800 space-y-4">
            {selectedPolicy ? (
              <div>
                <div className="border-b border-slate-800 pb-3 mb-4 flex items-center justify-between">
                  <div>
                    <h3 className="text-base font-bold text-white">{selectedPolicy.title}</h3>
                    <span className="text-xs font-mono text-slate-400">{selectedPolicy.filename}</span>
                  </div>
                  <span className="bg-sky-500/20 text-sky-400 text-xs px-2.5 py-0.5 rounded-full font-mono border border-sky-500/30">
                    ChromaDB Vector Chunk
                  </span>
                </div>

                <div className="bg-slate-950 p-5 rounded-xl border border-slate-800 font-mono text-xs text-slate-200 leading-relaxed whitespace-pre-wrap overflow-x-auto">
                  {selectedPolicy.content}
                </div>
              </div>
            ) : (
              <p className="text-slate-400 text-xs italic">Select a policy document to view contents.</p>
            )}
          </div>

        </div>
      )}

    </div>
  );
};
