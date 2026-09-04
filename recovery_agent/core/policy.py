"""
policy.py — Layer 4: Decision table mapping detection/diagnosis → intervention sequence.

Pure lookup logic — not free-form LLM. Every possible diagnosis or detection
category maps to an ordered list of intervention action strings.

The orchestrator calls get_intervention_sequence() and receives an ordered list
of actions to execute. Stopping rules (max retries, DNC, etc.) are enforced
by the orchestrator, not here.

Action strings (valid values):
  retry_payment_immediate   — retry right now (gateway timeout only)
  retry_payment_1d          — retry after 1 day
  retry_payment_3d          — retry after 3 days
  send_card_update_link     — send link to update expired card
  send_correction_link      — send link to re-enter CVV / payment details
  send_reminder             — generic payment reminder
  send_invoice_reminder     — invoice-specific reminder with payment link
  send_abandon_reminder     — abandoned cart recovery email
  send_discount_offer       — discount/offer in recovery email
  offer_payment_plan        — offer structured installment plan
  escalate_human            — route to human agent
  mark_uncollectable        — write off, close recovery
  no_action                 — DNC / low-intent / already-resolved: do nothing
"""

from typing import List, Dict, Any, Optional
from core.detector import DetectionResult
from core.diagnoser import DiagnosisResult


# ---------------------------------------------------------------------------
# Policy table
# ---------------------------------------------------------------------------
# Keys are either:
#   - detection category (for rule-certain cases)
#   - LLM diagnosis string (for ambiguous cases)
# Values are ordered action sequences (first action = first to execute).

POLICY_TABLE: Dict[str, List[str]] = {

    # ── Failed payments — rule-certain ─────────────────────────────────
    "CARD_EXPIRED": [
        "send_card_update_link",
        "retry_payment_3d",
        "send_reminder",
        "escalate_human",
    ],
    "INSUFFICIENT_FUNDS": [
        "retry_payment_3d",
        "retry_payment_3d",        # second retry 3d later
        "offer_payment_plan",
        "escalate_human",
    ],
    "GATEWAY_TIMEOUT": [
        "retry_payment_immediate",
        "retry_payment_1d",        # fallback if immediate fails
    ],
    "CARD_LOST": [
        "escalate_human",
    ],
    "INVALID_CVV": [
        "send_correction_link",
        "retry_payment_1d",
        "send_reminder",
    ],

    # ── Failed payments — LLM-diagnosed ────────────────────────────────
    "retryable_soft_decline": [
        "retry_payment_1d",
        "send_reminder",
        "escalate_human",
    ],
    "probable_churn": [
        "escalate_human",
    ],
    "suspected_dispute": [
        "escalate_human",
    ],
    "unknown": [
        "escalate_human",
    ],

    # ── Abandoned checkout ──────────────────────────────────────────────
    "HIGH_INTENT_ABANDON": [
        "send_abandon_reminder",
        "send_discount_offer",
    ],
    "MEDIUM_INTENT_ABANDON": [
        "send_abandon_reminder",
    ],
    "LOW_INTENT_ABANDON": [
        "no_action",
    ],

    # ── Overdue invoices — rule-certain ────────────────────────────────
    "MILDLY_OVERDUE": [
        "send_invoice_reminder",
    ],
    "MODERATELY_OVERDUE": [
        "send_invoice_reminder",
        "offer_payment_plan",
        "escalate_human",
    ],
    "SEVERELY_OVERDUE": [
        "send_invoice_reminder",
        "offer_payment_plan",
        "escalate_human",
    ],

    # ── Overdue invoices — LLM-diagnosed ───────────────────────────────
    "confirm_write_off": [
        "mark_uncollectable",
    ],
    "escalate_before_write_off": [
        "escalate_human",
        "mark_uncollectable",    # orchestrator only executes after human response window
    ],

    # ── Global overrides ───────────────────────────────────────────────
    "DNC": [
        "no_action",
    ],
    "UNKNOWN": [
        "escalate_human",
    ],
}

# Actions that count as a "retry" for stopping-rule purposes
RETRY_ACTIONS = {
    "retry_payment_immediate",
    "retry_payment_1d",
    "retry_payment_3d",
}

# Actions that count as "customer contact" for compliance cap
CONTACT_ACTIONS = {
    "send_card_update_link",
    "send_correction_link",
    "send_reminder",
    "send_invoice_reminder",
    "send_abandon_reminder",
    "send_discount_offer",
    "offer_payment_plan",
}

# Actions that are terminal (no further actions after these)
TERMINAL_ACTIONS = {
    "mark_uncollectable",
    "no_action",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_intervention_sequence(
    detection: DetectionResult,
    diagnosis: Optional[DiagnosisResult] = None,
) -> List[str]:
    """
    Return the ordered list of intervention actions for this event.

    Logic:
      1. If do_not_contact → ["no_action"]
      2. If LLM diagnosis available and confident → use diagnosis key
      3. Else → use detection category key
      4. Fallback → ["escalate_human"]
    """
    # DNC hard override — highest priority
    if detection.do_not_contact:
        return POLICY_TABLE["DNC"]

    # LLM-diagnosed path
    if diagnosis is not None and not diagnosis.llm_fallback:
        key = diagnosis.diagnosis
        if key in POLICY_TABLE:
            return list(POLICY_TABLE[key])

    # Rule-based path
    key = detection.category
    if key in POLICY_TABLE:
        return list(POLICY_TABLE[key])

    # Final fallback
    return list(POLICY_TABLE["UNKNOWN"])


def describe_sequence(actions: List[str]) -> str:
    """Human-readable summary of an action sequence for reporting."""
    if not actions:
        return "(empty sequence)"
    return " -> ".join(actions)


def action_metadata(action: str) -> Dict[str, Any]:
    """Return metadata about an action (type, is_retry, is_contact, is_terminal)."""
    return {
        "action":      action,
        "is_retry":    action in RETRY_ACTIONS,
        "is_contact":  action in CONTACT_ACTIONS,
        "is_terminal": action in TERMINAL_ACTIONS,
    }


# ---------------------------------------------------------------------------
# Smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys, json
    sys.path.insert(0, ".")
    from core.ingestion import load_events
    from core.detector  import detect_batch

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    events   = load_events(data_dir)
    detections = detect_batch(events)

    print("=== Policy Sequences (no LLM diagnosis) ===")
    seen_cats = set()
    for d in detections:
        if d.category not in seen_cats:
            seq = get_intervention_sequence(d)
            print(f"  {d.category:30s} -> {describe_sequence(seq)}")
            seen_cats.add(d.category)

    print(f"\nAll {len(POLICY_TABLE)} policy keys defined.")
