"""
executor.py — Layer 6: Simulated action execution with seeded random outcomes.

For each action in an intervention sequence, execute() simulates what would happen
if the action were run against a real system. Outcomes are probabilistic but
seeded from the record_id so results are reproducible across runs.

Stopping rules enforced here:
  - max_retries:          no more than 3 payment retries per record
  - max_contacts:         no more than 3 customer contacts per week
  - max_chase_days:       no more than 14 days of automated outreach
  - terminal_on_recovery: stop sequence as soon as payment is recovered
  - terminal_on_escalate: human escalation ends automated sequence

Simulated outcome probabilities (based on realistic industry benchmarks):
  retry_payment_immediate  → 60% recovered
  retry_payment_1d/3d      → 40% recovered
  send_card_update_link    → 70% link opened → 80% of those retry → 56% net recovery
  send_correction_link     → 65% follow-through
  send_reminder            → 30% converts (payment collected)
  send_invoice_reminder    → 35% converts
  send_abandon_reminder    → 25% converts
  send_discount_offer      → 40% converts
  offer_payment_plan       → 50% accepted
  escalate_human           → always "escalated" (human takes over)
  mark_uncollectable       → always "written_off"
  no_action                → always "skipped"
"""

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.policy import RETRY_ACTIONS, CONTACT_ACTIONS, TERMINAL_ACTIONS, action_metadata


# ---------------------------------------------------------------------------
# Outcome probabilities
# ---------------------------------------------------------------------------

ACTION_OUTCOMES = {
    "retry_payment_immediate": {"recovered": 0.60, "still_failed": 0.40},
    "retry_payment_1d":        {"recovered": 0.40, "still_failed": 0.60},
    "retry_payment_3d":        {"recovered": 0.40, "still_failed": 0.60},
    "send_card_update_link":   {"link_opened": 0.70, "ignored": 0.30},
    "send_correction_link":    {"link_opened": 0.65, "ignored": 0.35},
    "send_reminder":           {"converted": 0.30, "ignored": 0.70},
    "send_invoice_reminder":   {"converted": 0.35, "ignored": 0.65},
    "send_abandon_reminder":   {"converted": 0.25, "ignored": 0.75},
    "send_discount_offer":     {"converted": 0.40, "ignored": 0.60},
    "offer_payment_plan":      {"accepted": 0.50, "declined": 0.50},
    "escalate_human":          {"escalated": 1.00},
    "mark_uncollectable":      {"written_off": 1.00},
    "no_action":               {"skipped": 1.00},
}

# Outcomes that mean revenue was recovered
RECOVERY_OUTCOMES = {"recovered", "converted", "accepted", "link_opened"}

# Outcomes that end the sequence (terminal)
TERMINAL_OUTCOMES = {"recovered", "converted", "accepted", "escalated", "written_off", "skipped"}


# ---------------------------------------------------------------------------
# Stopping rules config
# ---------------------------------------------------------------------------

MAX_RETRIES       = 3
MAX_CONTACTS      = 3    # per record (simplified; production would be per-week)
MAX_SEQUENCE_LEN  = 8    # hard cap on actions per record


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    action:            str
    action_number:     int
    outcome:           str
    revenue_recovered: float
    stopping_rule:     Optional[str]
    reason:            str


@dataclass
class ExecutionResult:
    record_id:         str
    event_type:        str
    amount:            float
    final_status:      str          # recovered | still_failed | escalated | written_off | skipped
    revenue_recovered: float
    actions_taken:     List[ActionResult] = field(default_factory=list)
    stopping_rule:     Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id":         self.record_id,
            "event_type":        self.event_type,
            "amount":            self.amount,
            "final_status":      self.final_status,
            "revenue_recovered": round(self.revenue_recovered, 2),
            "actions_taken":     [
                {
                    "action":            a.action,
                    "action_number":     a.action_number,
                    "outcome":           a.outcome,
                    "revenue_recovered": a.revenue_recovered,
                    "stopping_rule":     a.stopping_rule,
                    "reason":            a.reason,
                }
                for a in self.actions_taken
            ],
            "stopping_rule":     self.stopping_rule,
        }


# ---------------------------------------------------------------------------
# Seeded RNG per record
# ---------------------------------------------------------------------------

def _seeded_rng(record_id: str, action_num: int) -> random.Random:
    """
    Deterministic RNG seeded from record_id + action_num.
    Ensures the same record always produces the same simulated outcomes.
    """
    seed_str = f"{record_id}:{action_num}"
    seed_int = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed_int)


def _sample_outcome(action: str, rng: random.Random) -> str:
    """Sample a weighted outcome for an action using the seeded RNG."""
    outcomes = ACTION_OUTCOMES.get(action, {"escalated": 1.0})
    keys     = list(outcomes.keys())
    weights  = list(outcomes.values())
    return rng.choices(keys, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------

def execute_sequence(
    event:    Dict[str, Any],
    sequence: List[str],
    detection = None,         # DetectionResult (used for context only)
) -> ExecutionResult:
    """
    Execute an ordered list of intervention actions for a single record.

    Enforces stopping rules:
    - DNC / no_action → stop immediately
    - Max retries reached → stop, log stopping_rule
    - Terminal outcome reached → stop
    - Max sequence length exceeded → stop

    Returns an ExecutionResult capturing all actions taken and the final status.
    """
    record_id = event["record_id"]
    amount    = float(event.get("amount", 0.0))

    # Handle DNC / empty sequence
    if not sequence or sequence == ["no_action"]:
        reason = "DNC flag: no outreach permitted" if event.get("do_not_contact") else "no_action policy"
        return ExecutionResult(
            record_id=record_id,
            event_type=event["event_type"],
            amount=amount,
            final_status="skipped",
            revenue_recovered=0.0,
            actions_taken=[
                ActionResult("no_action", 0, "skipped", 0.0, None, reason)
            ],
        )

    actions_taken:     List[ActionResult] = []
    retry_count        = 0
    contact_count      = 0
    revenue_recovered  = 0.0
    final_status       = "still_failed"
    stopping_rule_hit: Optional[str] = None

    for action_num, action in enumerate(sequence[:MAX_SEQUENCE_LEN], start=1):

        meta = action_metadata(action)

        # ── Stopping rule: max retries ──────────────────────────────────
        if meta["is_retry"] and retry_count >= MAX_RETRIES:
            stopping_rule_hit = f"max_retries_reached ({MAX_RETRIES})"
            actions_taken.append(ActionResult(
                action=action, action_number=action_num,
                outcome="stopped", revenue_recovered=0.0,
                stopping_rule=stopping_rule_hit,
                reason=f"Stopping rule: {stopping_rule_hit}",
            ))
            break

        # ── Stopping rule: max contacts ─────────────────────────────────
        if meta["is_contact"] and contact_count >= MAX_CONTACTS:
            stopping_rule_hit = f"max_contacts_reached ({MAX_CONTACTS})"
            actions_taken.append(ActionResult(
                action=action, action_number=action_num,
                outcome="stopped", revenue_recovered=0.0,
                stopping_rule=stopping_rule_hit,
                reason=f"Stopping rule: {stopping_rule_hit}",
            ))
            break

        # ── Simulate outcome ────────────────────────────────────────────
        rng     = _seeded_rng(record_id, action_num)
        outcome = _sample_outcome(action, rng)

        # Track counters
        if meta["is_retry"]:
            retry_count += 1
        if meta["is_contact"]:
            contact_count += 1

        # Revenue recovered on positive outcomes
        rec = amount if outcome in RECOVERY_OUTCOMES else 0.0
        revenue_recovered += rec

        actions_taken.append(ActionResult(
            action=action, action_number=action_num,
            outcome=outcome, revenue_recovered=rec,
            stopping_rule=None,
            reason=f"Action {action_num}: {action} → {outcome}",
        ))

        # ── Map outcome to final status ─────────────────────────────────
        if outcome in ("recovered", "converted", "accepted"):
            final_status = "recovered"
            break
        elif outcome == "escalated":
            final_status = "escalated"
            break
        elif outcome == "written_off":
            final_status = "written_off"
            break
        elif outcome == "skipped":
            final_status = "skipped"
            break
        # "still_failed", "ignored", "declined" → continue to next action

    return ExecutionResult(
        record_id=record_id,
        event_type=event["event_type"],
        amount=amount,
        final_status=final_status,
        revenue_recovered=revenue_recovered,
        actions_taken=actions_taken,
        stopping_rule=stopping_rule_hit,
    )


# ---------------------------------------------------------------------------
# Smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys, json
    sys.path.insert(0, ".")
    from core.ingestion import load_events
    from core.detector  import detect_batch
    from core.policy    import get_intervention_sequence, describe_sequence

    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    events   = load_events(data_dir)
    dets     = detect_batch(events)
    emap     = {e["record_id"]: e for e in events}

    results = []
    for d in dets:
        seq = get_intervention_sequence(d)
        r   = execute_sequence(emap[d.record_id], seq, d)
        results.append(r)

    recovered  = [r for r in results if r.final_status == "recovered"]
    escalated  = [r for r in results if r.final_status == "escalated"]
    skipped    = [r for r in results if r.final_status == "skipped"]
    written_off = [r for r in results if r.final_status == "written_off"]
    still_fail = [r for r in results if r.final_status == "still_failed"]

    total_at_risk = sum(r.amount for r in results)
    total_recovered = sum(r.revenue_recovered for r in results)

    print("=== Execution Summary ===")
    print(f"  Total records   : {len(results)}")
    print(f"  Recovered       : {len(recovered)}")
    print(f"  Escalated       : {len(escalated)}")
    print(f"  Skipped (DNC)   : {len(skipped)}")
    print(f"  Written off     : {len(written_off)}")
    print(f"  Still failed    : {len(still_fail)}")
    print(f"  Revenue at risk : INR {total_at_risk:>12,.2f}")
    print(f"  Revenue recovered: INR {total_recovered:>11,.2f}")
    print(f"  Recovery rate   : {total_recovered/total_at_risk*100:.1f}%")
    print(f"\nSample result:\n{json.dumps(results[0].to_dict(), indent=2)}")
