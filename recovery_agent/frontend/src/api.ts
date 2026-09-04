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

// ---------------------------------------------------------------------------
// Real-time Sequential Live Agent Streaming APIs
// ---------------------------------------------------------------------------

export async function fetchLiveState(): Promise<import('./types').LiveAgentState> {
  const res = await fetch(`${API_BASE}/live/state`);
  if (!res.ok) {
    throw new Error('Failed to fetch live state');
  }
  return res.json();
}

export async function stepLiveAgent(): Promise<import('./types').LiveStepPayload> {
  const res = await fetch(`${API_BASE}/live/step`, { method: 'POST' });
  if (!res.ok) {
    throw new Error('Failed to step live agent');
  }
  return res.json();
}

export async function startLiveAgent(speed_ms?: number): Promise<import('./types').LiveAgentState> {
  const res = await fetch(`${API_BASE}/live/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speed_ms: speed_ms ?? 250 }),
  });
  if (!res.ok) {
    throw new Error('Failed to start live stream');
  }
  return res.json();
}

export async function pauseLiveAgent(): Promise<import('./types').LiveAgentState> {
  const res = await fetch(`${API_BASE}/live/pause`, { method: 'POST' });
  if (!res.ok) {
    throw new Error('Failed to pause live stream');
  }
  return res.json();
}

export async function resetLiveAgent(): Promise<import('./types').LiveAgentState> {
  const res = await fetch(`${API_BASE}/live/reset`, { method: 'POST' });
  if (!res.ok) {
    throw new Error('Failed to reset live stream');
  }
  return res.json();
}

export async function fastForwardAgent(count: number = 50): Promise<import('./types').LiveAgentState> {
  const res = await fetch(`${API_BASE}/live/fast-forward`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ count }),
  });
  if (!res.ok) {
    throw new Error('Failed to fast forward');
  }
  return res.json();
}

export async function regenerateDataset(n_pay: number = 600, n_cart: number = 250, n_inv: number = 150): Promise<any> {
  const res = await fetch(`${API_BASE}/dataset/regenerate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ n_pay, n_cart, n_inv }),
  });
  if (!res.ok) {
    throw new Error('Failed to regenerate dataset');
  }
  return res.json();
}

export function subscribeLiveStream(onData: (data: any) => void): () => void {
  const eventSource = new EventSource(`${API_BASE}/live/stream`);

  eventSource.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data);
      onData(parsed);
    } catch (err) {
      console.error('Error parsing SSE event:', err);
    }
  };

  eventSource.onerror = (err) => {
    console.warn('Live stream SSE disconnected or reconnecting...', err);
  };

  return () => {
    eventSource.close();
  };
}

