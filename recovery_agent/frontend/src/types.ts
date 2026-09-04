export interface RecoveryStats {
  total_records: number;
  total_at_risk: number;
  total_recovered: number;
  recovery_rate_pct: number;
  by_final_status: Record<string, {
    count: number;
    amount: number;
    recovered: number;
    rate_pct: number;
  }>;
  by_detection_category: Record<string, {
    count: number;
    amount: number;
    recovered: number;
    rate_pct: number;
  }>;
}

export interface GroundTruthStats {
  detection_accuracy_pct: number;
  recovery_precision_pct: number;
  recovery_recall_pct: number;
  recovery_f1_pct: number;
  confusion_matrix: {
    TP: number;
    FN: number;
    TN: number;
    FP: number;
  };
}

export interface RecoveryReport {
  generated_at: string;
  recovery_stats: RecoveryStats;
  ground_truth_stats?: GroundTruthStats;
  top_exceptions?: Array<{
    record_id: string;
    event_type: string;
    amount: number;
    detection_category: string;
    final_status: string;
    reason: string;
  }>;
}

export interface ActionTaken {
  action: string;
  outcome: string;
  revenue_recovered: number;
  reason: string;
  logged_at: string;
}

export interface DiagnosisInfo {
  root_cause: string;
  confidence?: number | null;
  fallback?: boolean | null;
}

export interface CustomerRecord {
  record_id: string;
  event_type: 'failed_payment' | 'abandoned_checkout' | 'overdue_invoice';
  customer_segment: 'retail' | 'sme' | 'smb' | 'enterprise';
  amount: number;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  detection_category: string;
  final_status: 'recovered' | 'escalated' | 'still_failed' | 'skipped' | 'written_off' | 'unresolved';
  total_recovered: number;
  dnc_flag: boolean;
  actions_count: number;
  actions_taken: ActionTaken[];
  diagnosis?: DiagnosisInfo | null;
  rag_snippets?: string[];
  ground_truth?: {
    expected_status?: string;
    recovered?: boolean;
    reason?: string;
    gt_category?: string;
    gt_disposition?: string;
    resolvable?: boolean;
    needs_llm?: boolean;
    do_not_contact?: boolean;
  };
  rules_fired?: string[];
  detection_reason?: string;
  bandit_arm?: string | null;
}

export interface RecordDetailResponse {
  record: CustomerRecord;
  raw_steps: any[];
  previews: {
    whatsapp: string;
    sms: string;
  };
}

export interface PolicyItem {
  filename: string;
  title: string;
  content: string;
}

export interface SimulationRequest {
  event_type: string;
  customer_id: string;
  amount: number;
  failure_code?: string;
  customer_segment: string;
  dnc_flag: boolean;
  intent_score?: number;
  hours_overdue?: number;
}

export interface SimulationResponse {
  event: any;
  detection: {
    category: string;
    risk_level: string;
    needs_llm: boolean;
    rules_fired: string[];
    reason: string;
  };
  policy: {
    intervention_sequence: string[];
    max_retries: number;
  };
  previews: {
    whatsapp: string;
    sms: string;
  };
}

export type PlaybackSpeed = 1000 | 500 | 250 | 100 | 30;

export interface LiveAgentState {
  is_streaming: boolean;
  current_index: number;
  total_records: number;
  speed_ms: number;
  progress_pct: number;
  stats: RecoveryReport;
  latest_record: CustomerRecord | null;
  recent_records?: CustomerRecord[];
}

export interface LiveStepPayload {
  type?: string;
  record: CustomerRecord;
  stats: RecoveryReport;
  progress: {
    current: number;
    total: number;
    pct: number;
  };
}

