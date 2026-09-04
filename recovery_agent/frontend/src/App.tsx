import React, { useState, useEffect, useCallback } from 'react';
import { RecoveryReport, CustomerRecord, LiveAgentState } from './types';
import {
  fetchStats,
  fetchRecords,
  fetchPipelineStatus,
  fetchLiveState,
  startLiveAgent,
  pauseLiveAgent,
  stepLiveAgent,
  resetLiveAgent,
  fastForwardAgent,
  subscribeLiveStream,
} from './api';
import { Header } from './components/Header';
import { Dashboard } from './components/Dashboard';
import { CaseExplorer } from './components/CaseExplorer';
import { CaseDetailModal } from './components/CaseDetailModal';
import { LiveSimulator } from './components/LiveSimulator';
import { PolicyViewer } from './components/PolicyViewer';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'cases' | 'simulator' | 'policies'>('dashboard');
  const [stats, setStats] = useState<RecoveryReport | null>(null);
  const [records, setRecords] = useState<CustomerRecord[]>([]);
  const [liveState, setLiveState] = useState<LiveAgentState | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [isProcessingStep, setIsProcessingStep] = useState<boolean>(false);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [initialStatusFilter, setInitialStatusFilter] = useState<string | undefined>(undefined);
  const [pipelineRunning, setPipelineRunning] = useState<boolean>(false);

  const loadAllData = async () => {
    try {
      const [statsResult, recordsResult, pipelineResult, liveResult] = await Promise.allSettled([
        fetchStats(),
        fetchRecords(),
        fetchPipelineStatus(),
        fetchLiveState(),
      ]);
      if (statsResult.status === 'fulfilled') {
        setStats(statsResult.value);
      }
      if (recordsResult.status === 'fulfilled') {
        setRecords(recordsResult.value.records);
      }
      if (pipelineResult.status === 'fulfilled') {
        setPipelineRunning(pipelineResult.value.is_running);
      }
      if (liveResult.status === 'fulfilled') {
        setLiveState(liveResult.value);
        if (liveResult.value.current_index > 0 && liveResult.value.stats) {
          setStats(liveResult.value.stats);
        }
      }
    } catch (err) {
      console.error('Failed loading data:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadAllData();

    // Subscribe to SSE live agent row stream
    const unsubscribe = subscribeLiveStream((data) => {
      if (data.type === 'init' || data.type === 'pause') {
        if (data.state) {
          setLiveState(data.state);
          if (data.state.stats) setStats(data.state.stats);
        }
      } else if (data.type === 'reset') {
        if (data.state) {
          setLiveState(data.state);
          if (data.state.stats) setStats(data.state.stats);
        }
        setRecords([]);
      } else if (data.type === 'step') {
        if (data.stats) {
          setStats(data.stats);
        }
        if (data.record) {
          setRecords((prev) => {
            const exists = prev.some((r) => r.record_id === data.record.record_id);
            if (exists) {
              return prev.map((r) => (r.record_id === data.record.record_id ? data.record : r));
            }
            return [data.record, ...prev];
          });
        }
        setLiveState((prev) => ({
          ...(prev || { is_streaming: true, speed_ms: 250, total_records: data.progress?.total || 1000 }),
          is_streaming: true,
          current_index: data.progress?.current || (prev?.current_index ?? 0) + 1,
          total_records: data.progress?.total || prev?.total_records || 1000,
          progress_pct: data.progress?.pct ?? 0,
          stats: data.stats || prev?.stats || ({} as any),
          latest_record: data.record,
        }));
      } else if (data.type === 'complete') {
        if (data.state) {
          setLiveState(data.state);
          if (data.state.stats) setStats(data.state.stats);
        }
      }
    });

    // Auto-sync polling for background python subprocess
    const interval = setInterval(async () => {
      try {
        const pStatus = await fetchPipelineStatus();
        setPipelineRunning((prev) => {
          if (prev && !pStatus.is_running) {
            loadAllData();
          }
          return pStatus.is_running;
        });
      } catch {
        // Ignore background polling network glitches
      }
    }, 4000);

    return () => {
      unsubscribe();
      clearInterval(interval);
    };
  }, []);

  const handleStartLive = async (speed_ms?: number) => {
    try {
      const updated = await startLiveAgent(speed_ms);
      setLiveState(updated);
    } catch (err) {
      console.error('Failed to start live stream:', err);
    }
  };

  const handlePauseLive = async () => {
    try {
      const updated = await pauseLiveAgent();
      setLiveState(updated);
    } catch (err) {
      console.error('Failed to pause live stream:', err);
    }
  };

  const handleStepLive = async () => {
    setIsProcessingStep(true);
    try {
      const res = await stepLiveAgent();
      if (res.record && res.stats) {
        setStats(res.stats);
        setRecords((prev) => {
          const exists = prev.some((r) => r.record_id === res.record.record_id);
          if (exists) {
            return prev.map((r) => (r.record_id === res.record.record_id ? res.record : r));
          }
          return [res.record, ...prev];
        });
        setLiveState((prev) => ({
          ...(prev || { is_streaming: false, speed_ms: 250, total_records: res.progress?.total || 1000 }),
          is_streaming: false,
          current_index: res.progress?.current || (prev?.current_index ?? 0) + 1,
          total_records: res.progress?.total || prev?.total_records || 1000,
          progress_pct: res.progress?.pct ?? 0,
          stats: res.stats,
          latest_record: res.record,
        }));
      }
    } catch (err) {
      console.error('Failed to step live agent:', err);
    } finally {
      setIsProcessingStep(false);
    }
  };

  const handleResetLive = async () => {
    try {
      const res = await resetLiveAgent();
      setLiveState(res);
      setStats(res.stats);
      setRecords([]);
    } catch (err) {
      console.error('Failed to reset live stream:', err);
    }
  };

  const handleFastForwardLive = async (count: number) => {
    setIsProcessingStep(true);
    try {
      const res = await fastForwardAgent(count);
      setLiveState(res);
      setStats(res.stats);
      const recs = await fetchRecords();
      setRecords(recs.records);
    } catch (err) {
      console.error('Failed to fast-forward live stream:', err);
    } finally {
      setIsProcessingStep(false);
    }
  };


  const handleRefresh = () => {
    setRefreshing(true);
    loadAllData();
  };

  const handleNavigateToCases = (filter?: { status?: string }) => {
    if (filter?.status) {
      setInitialStatusFilter(filter.status);
    }
    setActiveTab('cases');
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] text-slate-100 flex flex-col font-sans">
      
      {/* Top Navbar */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onRefresh={handleRefresh}
        isRefreshing={refreshing}
        pipelineRunning={pipelineRunning}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 lg:px-8 py-8">
        {loading ? (
          <div className="p-24 text-center text-slate-400 space-y-3">
            <div className="w-10 h-10 border-4 border-sky-500 border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm font-semibold">Connecting to Razorpay Revenue Recovery Agent API...</p>
          </div>
        ) : (
          <>
            {activeTab === 'dashboard' && (
              <Dashboard
                data={stats}
                onNavigateToCases={handleNavigateToCases}
                liveState={liveState}
                onStartLive={handleStartLive}
                onPauseLive={handlePauseLive}
                onStepLive={handleStepLive}
                onResetLive={handleResetLive}
                onFastForwardLive={handleFastForwardLive}
                isProcessingStep={isProcessingStep}
              />
            )}

            {activeTab === 'cases' && (
              <CaseExplorer
                records={records}
                onSelectRecord={(rid) => setSelectedRecordId(rid)}
                isLoading={refreshing}
                initialStatusFilter={initialStatusFilter}
              />
            )}

            {activeTab === 'simulator' && <LiveSimulator />}

            {activeTab === 'policies' && <PolicyViewer />}
          </>
        )}
      </main>

      {/* Modal Drawer */}
      <CaseDetailModal
        recordId={selectedRecordId}
        onClose={() => setSelectedRecordId(null)}
      />

      {/* Footer */}
      <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-600">
        <p>Razorpay Autonomous Revenue Recovery Agent Dashboard • Built for Hackathon Excellence</p>
      </footer>

    </div>
  );
};

export default App;
