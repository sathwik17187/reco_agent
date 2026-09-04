import { RecoveryReport, CustomerRecord, RecordDetailResponse, PolicyItem, SimulationRequest, SimulationResponse } from './types';

const API_BASE = '/api';

export async function fetchStats(): Promise<RecoveryReport> {
  const res = await fetch(`${API_BASE}/stats`);
  if (!res.ok) {
    throw new Error(`Failed to fetch stats: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchRecords(params?: {
  search?: string;
  event_type?: string;
  status?: string;
  category?: string;
  risk?: string;
}): Promise<{ total: number; records: CustomerRecord[] }> {
  const query = new URLSearchParams();
  if (params?.search) query.append('search', params.search);
  if (params?.event_type) query.append('event_type', params.event_type);
  if (params?.status) query.append('status', params.status);
  if (params?.category) query.append('category', params.category);
  if (params?.risk) query.append('risk', params.risk);

  const res = await fetch(`${API_BASE}/records?${query.toString()}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch records: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchRecordDetail(recordId: string): Promise<RecordDetailResponse> {
  const res = await fetch(`${API_BASE}/records/${recordId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch record detail for ${recordId}`);
  }
  return res.json();
}

export async function fetchPolicies(): Promise<{ policies: PolicyItem[] }> {
  const res = await fetch(`${API_BASE}/policies`);
  if (!res.ok) {
    throw new Error('Failed to fetch policies');
  }
  return res.json();
}

export async function simulateEvent(req: SimulationRequest): Promise<SimulationResponse> {
  const res = await fetch(`${API_BASE}/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error('Failed to simulate event');
  }
  return res.json();
}

export async function triggerPipeline(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE}/run-agent`, { method: 'POST' });
  if (!res.ok) {
    throw new Error('Failed to trigger pipeline');
  }
  return res.json();
}

export async function fetchPipelineStatus(): Promise<{
  is_running: boolean;
  last_run: string | null;
  logs: string[];
  error: string | null;
}> {
  const res = await fetch(`${API_BASE}/pipeline-status`);
  if (!res.ok) {
    throw new Error('Failed to fetch pipeline status');
  }
  return res.json();
}
