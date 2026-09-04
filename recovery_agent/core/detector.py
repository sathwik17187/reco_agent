"""
detector.py — Layer 2: Rule-based risk detection and classification.

Takes a normalized Event dict (from ingestion.py) and returns a DetectionResult
describing the risk level, category, whether it needs LLM diagnosis, and the
exact rule that fired. Pure code, no LLM.

Detection categories:
  Failed payments   → CARD_EXPIRED | INSUFFICIENT_FUNDS | GATEWAY_TIMEOUT |
                       SOFT_DECLINE | CARD_LOST | INVALID_CVV
  Abandoned checkout→ HIGH_INTENT_ABANDON | MEDIUM_INTENT_ABANDON | LOW_INTENT_ABANDON
  Overdue invoices  → MILDLY_OVERDUE | MODERATELY_OVERDUE | SEVERELY_OVERDUE |
                       LIKELY_UNCOLLECTABLE

Risk levels:
  HIGH   → immediate intervention required
  MEDIUM → intervention needed but not urgent
  LOW    → light-touch or skip
  SKIP   → do-not-contact or no-action case

LLM flag:
  needs_llm=True for SOFT_DECLINE and LIKELY_UNCOLLECTABLE only.
  Everything else is rule-certain.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DetectionResult:
    record_id:       str
    event_type:      str
    category:        str          # e.g. "CARD_EXPIRED"
    risk_level:      str          # HIGH | MEDIUM | LOW | SKIP
    needs_llm:       bool
    reason:          str          # human-readable rule that fired
    do_not_contact:  bool
    amount:          float
    customer_segment: str
    rules_fired:     List[str] = field(default_factory=list)  # audit trail

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id":        self.record_id,
            "event_type":       self.event_type,
            "category":         self.category,
            "risk_level":       self.risk_level,
            "needs_llm":        self.needs_llm,
            "reason":           self.reason,
            "do_not_contact":   self.do_not_contact,
            "amount":           self.amount,
            "customer_segment": self.customer_segment,
            "rules_fired":      self.rules_fired,
        }


# ---------------------------------------------------------------------------
# Failure code → detection mapping
# ---------------------------------------------------------------------------

_FAILURE_CODE_MAP = {
    "card_expired": {
        "category":   "CARD_EXPIRED",
        "risk_level": "HIGH",
        "needs_llm":  False,
        "reason":     "card_expired failure code: card must be updated before retry",
    },
    "insufficient_funds": {
        "category":   "INSUFFICIENT_FUNDS",
        "risk_level": "HIGH",
        "needs_llm":  False,
        "reason":     "insufficient_funds failure code: soft decline, retry after 3 days",
    },
    "gateway_timeout": {
        "category":   "GATEWAY_TIMEOUT",
        "risk_level": "HIGH",
        "needs_llm":  False,
        "reason":     "gateway_timeout failure code: transient infra issue, immediate retry eligible",
    },
    "do_not_honor": {
        "category":   "SOFT_DECLINE",
        "risk_level": "HIGH",
        "needs_llm":  True,
        "reason":     "do_not_honor failure code: ambiguous soft decline — LLM diagnosis required",
    },
    "card_lost_stolen": {
        "category":   "CARD_LOST",
        "risk_level": "HIGH",
        "needs_llm":  False,
        "reason":     "card_lost_stolen failure code: hard decline, must escalate to human",
    },
    "invalid_cvv": {
        "category":   "INVALID_CVV",
        "risk_level": "MEDIUM",
        "needs_llm":  False,
        "reason":     "invalid_cvv failure code: data entry error, send correction link",
    },
}

# Catch-all for unknown failure codes
_UNKNOWN_FAILURE = {
    "category":   "SOFT_DECLINE",
    "risk_level": "MEDIUM",
    "needs_llm":  True,
    "reason":     "unknown failure code — routed to LLM for diagnosis",
}

# ---------------------------------------------------------------------------
# Abandonment step → detection mapping
# ---------------------------------------------------------------------------

_ABANDON_STEP_MAP = {
    "confirm": {
        "category":   "HIGH_INTENT_ABANDON",
        "risk_level": "HIGH",
        "needs_llm":  False,
        "reason":     "abandoned at confirm step: highest purchase intent, strong recovery candidate",
    },
    "review": {
        "category":   "HIGH_INTENT_ABANDON",
        "risk_level": "HIGH",
        "needs_llm":  False,
        "reason":     "abandoned at review step: high purchase intent, good recovery candidate",
    },
    "payment_info": {
        "category":   "MEDIUM_INTENT_ABANDON",
        "risk_level": "MEDIUM",
        "needs_llm":  False,
        "reason":     "abandoned at payment_info step: medium intent, send one reminder",
    },
    "address": {
        "category":   "LOW_INTENT_ABANDON",
        "risk_level": "LOW",
        "needs_llm":  False,
        "reason":     "abandoned at address step: low intent, not worth automated recovery",
    },
}

_UNKNOWN_ABANDON = {
    "category":   "MEDIUM_INTENT_ABANDON",
    "risk_level": "MEDIUM",
    "needs_llm":  False,
    "reason":     "unknown abandonment step — defaulting to medium intent",
}

# ---------------------------------------------------------------------------
# Overdue invoice brackets
# ---------------------------------------------------------------------------

def _overdue_detection(days: int) -> Dict[str, Any]:
    if days <= 7:
        return {
            "category":   "MILDLY_OVERDUE",
            "risk_level": "MEDIUM",
            "needs_llm":  False,
            "reason":     f"invoice {days}d overdue (≤7d): send friendly reminder",
        }
    elif days <= 30:
        return {
            "category":   "MODERATELY_OVERDUE",
            "risk_level": "HIGH",
            "needs_llm":  False,
            "reason":     f"invoice {days}d overdue (8-30d): escalating reminder + payment plan offer",
        }
    elif days <= 90:
        return {
            "category":   "SEVERELY_OVERDUE",
            "risk_level": "HIGH",
            "needs_llm":  False,
            "reason":     f"invoice {days}d overdue (31-90d): structured payment plan + human escalation",
        }
    else:
        return {
            "category":   "LIKELY_UNCOLLECTABLE",
            "risk_level": "HIGH",
            "needs_llm":  True,
            "reason":     f"invoice {days}d overdue (>90d): LLM review before write-off decision",
        }


# ---------------------------------------------------------------------------
# DNC check — applied after category detection
# ---------------------------------------------------------------------------

def _apply_dnc(result_meta: Dict, event: Dict) -> tuple:
    """
    If do_not_contact=True, override risk_level to SKIP and note it.
    Returns (risk_level, rules_fired_entry).
    """
    if event.get("do_not_contact"):
        return "SKIP", "DNC flag set: all outreach suppressed, no intervention"
    return result_meta["risk_level"], None


# ---------------------------------------------------------------------------
# Public detector
# ---------------------------------------------------------------------------

def detect(event: Dict[str, Any]) -> DetectionResult:
    """
    Classify an event and return a DetectionResult.

    The logic never touches ground truth — it only looks at observable
    fields on the event (failure_code, abandoned_at_step, days_overdue).
    """
    etype    = event["event_type"]
    rules_fired = []

    # ── Failed payment ───────────────────────────────────────────────────
    if etype == "failed_payment":
        code = event.get("failure_code", "").strip().lower()
        meta = _FAILURE_CODE_MAP.get(code, _UNKNOWN_FAILURE)
        rules_fired.append(f"rule:failure_code={code} → {meta['category']}")

    # ── Abandoned checkout ───────────────────────────────────────────────
    elif etype == "abandoned_checkout":
        step = event.get("abandoned_at_step", "").strip().lower()
        meta = _ABANDON_STEP_MAP.get(step, _UNKNOWN_ABANDON)
        rules_fired.append(f"rule:abandoned_at_step={step} → {meta['category']}")

    # ── Overdue invoice ──────────────────────────────────────────────────
    elif etype == "overdue_invoice":
        days = int(event.get("days_overdue", 0))
        meta = _overdue_detection(days)
        rules_fired.append(f"rule:days_overdue={days} → {meta['category']}")

    else:
        meta = {
            "category":   "UNKNOWN",
            "risk_level": "MEDIUM",
            "needs_llm":  True,
            "reason":     f"unknown event_type '{etype}': routed to LLM",
        }
        rules_fired.append(f"rule:unknown_event_type → SOFT_DECLINE")

    # ── DNC override ─────────────────────────────────────────────────────
    risk_level, dnc_note = _apply_dnc(meta, event)
    if dnc_note:
        rules_fired.append(f"rule:do_not_contact → SKIP")

    return DetectionResult(
        record_id=        event["record_id"],
        event_type=       etype,
        category=         meta["category"],
        risk_level=       risk_level,
        needs_llm=        meta["needs_llm"] and not event.get("do_not_contact"),
        reason=           meta["reason"],
        do_not_contact=   bool(event.get("do_not_contact")),
        amount=           float(event.get("amount", 0.0)),
        customer_segment= event.get("customer_segment", "unknown"),
        rules_fired=      rules_fired,
    )


def detect_batch(events: List[Dict[str, Any]]) -> List[DetectionResult]:
    """Run detect() on a list of events."""
    return [detect(e) for e in events]


def summarize_detections(results: List[DetectionResult]) -> Dict[str, Any]:
    """Aggregate detection results for logging/reporting."""
    by_category:   Dict[str, int]   = {}
    by_risk:       Dict[str, int]   = {}
    llm_count      = 0
    skip_count     = 0
    total_amount   = 0.0

    for r in results:
        by_category[r.category] = by_category.get(r.category, 0) + 1
        by_risk[r.risk_level]   = by_risk.get(r.risk_level, 0) + 1
        if r.needs_llm:
            llm_count += 1
        if r.risk_level == "SKIP":
            skip_count += 1
        total_amount += r.amount

    return {
        "total":              len(results),
        "by_category":        by_category,
        "by_risk_level":      by_risk,
        "needs_llm":          llm_count,
        "skip_dnc":           skip_count,
        "total_amount_at_risk": round(total_amount, 2),
    }


# ---------------------------------------------------------------------------
# Smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys, json
    sys.path.insert(0, ".")
    from core.ingestion import load_events

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    events  = load_events(data_dir)
    results = detect_batch(events)
    summary = summarize_detections(results)

    print("=== Detection Summary ===")
    print(json.dumps(summary, indent=2))
    print("\n=== Sample DetectionResult ===")
    print(json.dumps(results[0].to_dict(), indent=2))

    llm_cases = [r for r in results if r.needs_llm]
    print(f"\nLLM cases ({len(llm_cases)}):")
    for r in llm_cases:
        print(f"  {r.record_id:30s}  {r.category:25s}  INR {r.amount:>10,.2f}  [{r.customer_segment}]")
