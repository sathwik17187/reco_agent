"""
orchestrator.py — Layer 5: Agent brain. Sequences the full pipeline end-to-end.

Drives every record through:
  1. Detection  (rule-based, always)
  2. RAG retrieval + LLM diagnosis  (only for needs_llm cases)
  3. Policy lookup  → intervention sequence
  4. Execution  (simulated outcomes)
  5. Audit logging  (every decision)

Returns a list of PipelineResult objects consumed by the scorer/reporter.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.ingestion    import load_events, summarize as ingest_summary
from core.detector     import detect, detect_batch, DetectionResult, summarize_detections
from core.rag_retriever import RAGRetriever, build_query
from core.diagnoser    import diagnose, DiagnosisResult
from core.policy       import get_intervention_sequence, describe_sequence
from core.executor     import execute_sequence, ExecutionResult
from core.audit_log    import AuditLog


# ---------------------------------------------------------------------------
# Pipeline result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    event:      Dict[str, Any]
    detection:  DetectionResult
    diagnosis:  Optional[DiagnosisResult]
    sequence:   List[str]
    execution:  ExecutionResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type":       self.event["event_type"],
            "record_id":        self.event["record_id"],
            "customer_segment": self.event.get("customer_segment", ""),
            "amount":           self.event.get("amount", 0.0),
            "detection":        self.detection.to_dict(),
            "diagnosis":        self.diagnosis.to_dict() if self.diagnosis else None,
            "sequence":         self.sequence,
            "execution":        self.execution.to_dict(),
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(
    data_dir:    str,
    output_dir:  str,
    policy_dir:  str = None,
    verbose:     bool = True,
) -> List[PipelineResult]:
    """
    Run the full recovery agent pipeline on all events in data_dir.

    Args:
        data_dir   : directory containing failed_payments.csv, etc.
        output_dir : directory for audit.jsonl and reports
        policy_dir : directory containing policy .txt chunks (for RAG index)
        verbose    : print progress to stdout

    Returns:
        List of PipelineResult — one per event, consumed by scorer.
    """
    if policy_dir is None:
        policy_dir = os.path.join(data_dir, "policy_docs")

    os.makedirs(output_dir, exist_ok=True)
    audit_path = os.path.join(output_dir, "audit.jsonl")

    # ── 1. Ingest ─────────────────────────────────────────────────────────
    if verbose:
        print("[1/5] Ingesting events...")
    events  = load_events(data_dir)
    summary = ingest_summary(events)
    if verbose:
        print(f"      {summary['total_events']} events loaded | "
              f"INR {summary['total_revenue_at_risk']:,.0f} at risk | "
              f"{summary['dnc_flagged']} DNC")

    # ── 2. Detection ──────────────────────────────────────────────────────
    if verbose:
        print("[2/5] Running detection (rule-based)...")
    detections  = detect_batch(events)
    det_summary = summarize_detections(detections)
    event_map   = {e["record_id"]: e for e in events}
    det_map     = {d.record_id: d for d in detections}
    if verbose:
        print(f"      {det_summary['needs_llm']} cases need LLM | "
              f"{det_summary['skip_dnc']} DNC skips")

    # ── 3. RAG index ─────────────────────────────────────────────────────
    if verbose:
        print("[3/5] Loading RAG index...")
    retriever = RAGRetriever(persist_dir=os.path.join(os.path.dirname(__file__) or ".", "..", "chroma_db"))
    retriever.ensure_index(policy_dir)

    # ── 4. LLM diagnosis for ambiguous cases ─────────────────────────────
    if verbose:
        print("[4/5] Running LLM diagnosis on ambiguous cases...")
    diag_map: Dict[str, DiagnosisResult] = {}
    llm_cases = [(event_map[d.record_id], d) for d in detections if d.needs_llm]

    for i, (event, detection) in enumerate(llm_cases, 1):
        if verbose:
            print(f"      [{i}/{len(llm_cases)}] {detection.record_id} ({detection.category})")
        query       = build_query(event, detection.category)
        snippets    = retriever.retrieve(query, top_k=3)
        raw_snippets = retriever.retrieve_raw(query, top_k=3)
        diag = diagnose(event, detection, snippets, raw_snippets)
        diag_map[detection.record_id] = diag
        if verbose:
            fallback_note = " [FALLBACK]" if diag.llm_fallback else ""
            print(f"             -> {diag.diagnosis} (conf={diag.confidence:.2f}){fallback_note}")

    # ── 5. Policy + execution + audit ────────────────────────────────────
    if verbose:
        print("[5/5] Executing intervention sequences...")

    results: List[PipelineResult] = []

    with AuditLog(audit_path) as audit:
        for detection in detections:
            event    = event_map[detection.record_id]
            diagnosis = diag_map.get(detection.record_id)

            # Log detection
            audit.record_detection(event, detection)

            # Log diagnosis (if LLM was used)
            if diagnosis:
                audit.record_diagnosis(event, detection, diagnosis)

            # Get intervention sequence
            sequence = get_intervention_sequence(detection, diagnosis)

            # Execute sequence
            exec_result = execute_sequence(event, sequence, detection)

            # Log each action
            for action_result in exec_result.actions_taken:
                audit.record_action(
                    event=event,
                    detection=detection,
                    diagnosis=diagnosis,
                    action=action_result.action,
                    action_num=action_result.action_number,
                    outcome=action_result.outcome,
                    revenue_recovered=action_result.revenue_recovered,
                    stopping_rule=action_result.stopping_rule,
                    reason=action_result.reason,
                )

            results.append(PipelineResult(
                event=event,
                detection=detection,
                diagnosis=diagnosis,
                sequence=sequence,
                execution=exec_result,
            ))

    if verbose:
        recovered = sum(1 for r in results if r.execution.final_status == "recovered")
        total_rec = sum(r.execution.revenue_recovered for r in results)
        total_risk = sum(r.execution.amount for r in results)
        print(f"\n=== Pipeline complete ===")
        print(f"  {len(results)} records processed")
        print(f"  {recovered} recovered ({recovered/len(results)*100:.1f}%)")
        print(f"  Revenue recovered: INR {total_rec:,.2f} / INR {total_risk:,.2f} "
              f"({total_rec/total_risk*100:.1f}%)")
        print(f"  Audit log: {audit_path}")

    return results
