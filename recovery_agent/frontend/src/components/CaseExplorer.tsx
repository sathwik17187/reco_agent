import React, { useState } from 'react';
import { Search, Filter, ChevronRight, ArrowUpDown, RefreshCw, AlertCircle } from 'lucide-react';
import { CustomerRecord } from '../types';
import { StatusBadge } from './StatusBadge';

interface CaseExplorerProps {
  records: CustomerRecord[];
  onSelectRecord: (recordId: string) => void;
  isLoading: boolean;
  initialStatusFilter?: string;
}

export const CaseExplorer: React.FC<CaseExplorerProps> = ({
  records,
  onSelectRecord,
  isLoading,
  initialStatusFilter,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedEventType, setSelectedEventType] = useState<string>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>(initialStatusFilter || 'all');
  const [selectedRisk, setSelectedRisk] = useState<string>('all');

  React.useEffect(() => {
    if (initialStatusFilter) {
      setSelectedStatus(initialStatusFilter);
    }
  }, [initialStatusFilter]);

  // Format INR
  const formatINR = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2,
    }).format(val);
  };

  // Filter records
  const filteredRecords = records.filter((r) => {
    const matchesSearch =
      r.record_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      r.detection_category.toLowerCase().includes(searchTerm.toLowerCase()) ||
      r.customer_segment.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesEventType = selectedEventType === 'all' || r.event_type === selectedEventType;
    const matchesStatus = selectedStatus === 'all' || r.final_status === selectedStatus;
    const matchesRisk = selectedRisk === 'all' || r.risk_level === selectedRisk;

    return matchesSearch && matchesEventType && matchesStatus && matchesRisk;
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      
      {/* Header & Filter Controls */}
      <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight">Customer Case Explorer</h2>
            <p className="text-xs text-slate-400">
              Audit individual payment recovery attempts, RAG policy matches, and execution logs
            </p>
          </div>
          <div className="text-xs text-slate-400 font-mono bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800">
            Showing <span className="text-sky-400 font-bold">{filteredRecords.length}</span> of {records.length} records
          </div>
        </div>

        {/* Filters Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 pt-2 border-t border-slate-800">
          
          {/* Search Box */}
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search by ID, Category..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-slate-900 text-xs text-slate-200 placeholder-slate-500 pl-9 pr-3 py-2 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none transition-all"
            />
          </div>

          {/* Event Type */}
          <select
            value={selectedEventType}
            onChange={(e) => setSelectedEventType(e.target.value)}
            className="bg-slate-900 text-xs text-slate-200 px-3 py-2 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none"
          >
            <option value="all">All Event Types</option>
            <option value="failed_payment">Failed Payment</option>
            <option value="abandoned_checkout">Abandoned Checkout</option>
            <option value="overdue_invoice">Overdue Invoice</option>
          </select>

          {/* Status Filter */}
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="bg-slate-900 text-xs text-slate-200 px-3 py-2 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none"
          >
            <option value="all">All Final Statuses</option>
            <option value="recovered">Recovered</option>
            <option value="escalated">Escalated</option>
            <option value="still_failed">Still Failed</option>
            <option value="skipped">Skipped</option>
            <option value="written_off">Written Off</option>
          </select>

          {/* Risk Level */}
          <select
            value={selectedRisk}
            onChange={(e) => setSelectedRisk(e.target.value)}
            className="bg-slate-900 text-xs text-slate-200 px-3 py-2 rounded-xl border border-slate-800 focus:border-sky-500 focus:outline-none"
          >
            <option value="all">All Risk Levels</option>
            <option value="HIGH">High Risk</option>
            <option value="MEDIUM">Medium Risk</option>
            <option value="LOW">Low Risk</option>
          </select>

        </div>
      </div>

      {/* Data Table */}
      <div className="glass-panel rounded-2xl border border-slate-800 overflow-hidden shadow-xl">
        {isLoading ? (
          <div className="p-12 text-center text-slate-400 flex items-center justify-center gap-2">
            <RefreshCw className="w-5 h-5 animate-spin text-sky-400" />
            Loading customer cases...
          </div>
        ) : filteredRecords.length === 0 ? (
          <div className="p-12 text-center text-slate-400 space-y-2">
            <AlertCircle className="w-8 h-8 text-amber-400 mx-auto" />
            <p className="font-semibold text-slate-200">No matching records found</p>
            <p className="text-xs text-slate-500">Try adjusting your search query or clear filters.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="bg-slate-900/90 text-slate-400 border-b border-slate-800 font-semibold uppercase tracking-wider">
                  <th className="px-4 py-3.5">Record ID</th>
                  <th className="px-4 py-3.5">Event Type</th>
                  <th className="px-4 py-3.5">Segment</th>
                  <th className="px-4 py-3.5">Category</th>
                  <th className="px-4 py-3.5">Risk</th>
                  <th className="px-4 py-3.5 text-right">Amount</th>
                  <th className="px-4 py-3.5 text-center">Actions</th>
                  <th className="px-4 py-3.5">Final Status</th>
                  <th className="px-4 py-3.5 text-right">Recovered</th>
                  <th className="px-4 py-3.5 text-center">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredRecords.map((r) => (
                  <tr
                    key={r.record_id}
                    onClick={() => onSelectRecord(r.record_id)}
                    className="hover:bg-slate-800/50 cursor-pointer transition-colors group"
                  >
                    <td className="px-4 py-3 font-mono font-bold text-sky-400 group-hover:text-sky-300">
                      {r.record_id}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.event_type} type="event" />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.customer_segment} type="segment" />
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-200">
                      {r.detection_category.replace(/_/g, ' ')}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.risk_level} type="risk" />
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-white">
                      {formatINR(r.amount)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className="bg-slate-800 text-slate-300 text-[11px] px-2 py-0.5 rounded-full font-mono">
                        {r.actions_count} steps
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.final_status} type="status" />
                    </td>
                    <td className={`px-4 py-3 text-right font-bold ${r.total_recovered > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                      {formatINR(r.total_recovered)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-sky-400 inline-block transition-transform group-hover:translate-x-1" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
};
