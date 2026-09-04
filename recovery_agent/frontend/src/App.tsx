import React, { useState, useEffect } from 'react';
import { RecoveryReport, CustomerRecord } from './types';
import { fetchStats, fetchRecords, fetchPipelineStatus } from './api';
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
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [initialStatusFilter, setInitialStatusFilter] = useState<string | undefined>(undefined);
  const [pipelineRunning, setPipelineRunning] = useState<boolean>(false);

  const loadAllData = async () => {
    try {
      const [statsResult, recordsResult, pipelineResult] = await Promise.allSettled([
        fetchStats(),
        fetchRecords(),
        fetchPipelineStatus(),
      ]);
      if (statsResult.status === 'fulfilled') {
        setStats(statsResult.value);
      } else {
        console.error('Failed fetching stats:', statsResult.reason);
      }
      if (recordsResult.status === 'fulfilled') {
        setRecords(recordsResult.value.records);
      } else {
        console.error('Failed fetching records:', recordsResult.reason);
      }
      if (pipelineResult.status === 'fulfilled') {
        setPipelineRunning(pipelineResult.value.is_running);
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

    // Auto-sync polling: detects when a background pipeline run finishes
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
    }, 3000);

    return () => clearInterval(interval);
  }, []);

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
              <Dashboard data={stats} onNavigateToCases={handleNavigateToCases} />
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
