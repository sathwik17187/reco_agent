"""
audit_log.py — Layer 7: Append-only, per-action audit trail.

Every action taken (or skipped) during the recovery pipeline is logged as a
JSON line to audit.jsonl. This gives reviewers a complete, timestamped
explanation of every decision without digging into source code.

Log fields per entry:
  record_id, event_type, customer_segment, amount,
  stage (detection|diagnosis|execution),
  action, action_number, outcome,
  detection_category, diagnosis, llm_confidence, llm_fallback,
  rag_snippets_used, policy_applied,
  stopping_rule_triggered, dnc_flag,
  revenue_recovered, reason, timestamp
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class AuditLog:
    """
    Append-only JSONL audit log.

    Usage:
        log = AuditLog("output/audit.jsonl")
        log.record_detection(event, detection)
        log.record_diagnosis(event, detection, diagnosis)
        log.record_action(event, detection, diagnosis, action, outcome, ...)
        log.close()
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")

    def _write(self, entry: Dict[str, Any]):
        entry["logged_at"] = datetime.now(timezone.utc).isoformat()
        self._fh.write(json.dumps(entry) + "\n")
        self._fh.flush()

    # ------------------------------------------------------------------
    # Structured log methods
    # ------------------------------------------------------------------

    def record_detection(self, event: Dict, detection) -> None:
        """Log the outcome of the detection layer for a record."""
        self._write({
            "record_id":          event["record_id"],
            "event_type":         event["event_type"],
            "customer_segment":   event.get("customer_segment", ""),
            "amount":             event.get("amount", 0.0),
            "stage":              "detection",
            "action":             "detect",
            "detection_category": detection.category,
            "risk_level":         detection.risk_level,
            "needs_llm":          detection.needs_llm,
            "dnc_flag":           detection.do_not_contact,
            "rules_fired":        detection.rules_fired,
            "reason":             detection.reason,
            "outcome":            "classified",
        })

    def record_diagnosis(self, event: Dict, detection, diagnosis) -> None:
        """Log the LLM diagnosis result for an ambiguous record."""
        self._write({
            "record_id":          event["record_id"],
            "event_type":         event["event_type"],
            "customer_segment":   event.get("customer_segment", ""),
            "amount":             event.get("amount", 0.0),
            "stage":              "diagnosis",
            "action":             "llm_diagnose",
            "detection_category": detection.category,
            "diagnosis":          diagnosis.diagnosis,
            "llm_confidence":     diagnosis.confidence,
            "llm_fallback":       diagnosis.llm_fallback,
            "llm_error":          diagnosis.llm_error,
            "rag_snippets_used":  diagnosis.rag_snippets_used,
            "policy_applied":     diagnosis.policy_applied,
            "reasoning":          diagnosis.reasoning,
            "recommended_hint":   diagnosis.recommended_hint,
            "dnc_flag":           detection.do_not_contact,
            "outcome":            "diagnosed",
        })

    def record_action(
        self,
        event:      Dict,
        detection,
        diagnosis:  Optional[Any],
        action:     str,
        action_num: int,
        outcome:    str,                      # recovered|still_failed|escalated|written_off|skipped|no_action
        revenue_recovered: float = 0.0,
        stopping_rule:     Optional[str] = None,
        reason:            str = "",
    ) -> None:
        """Log a single executed action and its simulated outcome."""
        self._write({
            "record_id":               event["record_id"],
            "event_type":              event["event_type"],
            "customer_segment":        event.get("customer_segment", ""),
            "amount":                  event.get("amount", 0.0),
            "stage":                   "execution",
            "action":                  action,
            "action_number":           action_num,
            "detection_category":      detection.category,
            "diagnosis":               diagnosis.diagnosis if diagnosis else None,
            "llm_confidence":          diagnosis.confidence if diagnosis else None,
            "llm_fallback":            diagnosis.llm_fallback if diagnosis else None,
            "rag_snippets_used":       diagnosis.rag_snippets_used if diagnosis else [],
            "policy_applied":          diagnosis.policy_applied if diagnosis else None,
            "dnc_flag":                detection.do_not_contact,
            "stopping_rule_triggered": stopping_rule,
            "outcome":                 outcome,
            "revenue_recovered":       round(revenue_recovered, 2),
            "reason":                  reason,
        })

    def record_skip(
        self,
        event:     Dict,
        detection,
        reason:    str,
    ) -> None:
        """Log a skipped record (DNC, low-intent, etc.)."""
        self._write({
            "record_id":          event["record_id"],
            "event_type":         event["event_type"],
            "customer_segment":   event.get("customer_segment", ""),
            "amount":             event.get("amount", 0.0),
            "stage":              "execution",
            "action":             "skip",
            "action_number":      0,
            "detection_category": detection.category,
            "diagnosis":          None,
            "dnc_flag":           detection.do_not_contact,
            "stopping_rule_triggered": None,
            "outcome":            "skipped",
            "revenue_recovered":  0.0,
            "reason":             reason,
        })

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# Reader helpers (for reporter)
# ---------------------------------------------------------------------------

def read_audit_log(path: str) -> List[Dict[str, Any]]:
    """Read all entries from an audit.jsonl file."""
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def summarize_audit(entries: List[Dict]) -> Dict[str, Any]:
    """Quick summary of audit entries for reporting."""
    by_stage:   Dict[str, int] = {}
    by_outcome: Dict[str, int] = {}
    llm_used   = 0
    dnc_skipped = 0

    for e in entries:
        stage   = e.get("stage", "unknown")
        outcome = e.get("outcome", "unknown")
        by_stage[stage]     = by_stage.get(stage, 0) + 1
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if e.get("stage") == "diagnosis":
            llm_used += 1
        if e.get("outcome") == "skipped" and e.get("dnc_flag"):
            dnc_skipped += 1

    return {
        "total_log_entries": len(entries),
        "by_stage":          by_stage,
        "by_outcome":        by_outcome,
        "llm_diagnoses":     llm_used,
        "dnc_skipped":       dnc_skipped,
    }
