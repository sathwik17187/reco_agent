"""
langgraph_agent.py — LangGraph StateMachine Architecture for Revenue Recovery.

Defines the cyclic state machine:
  START -> agent_router -> compliance_guard_node -> execute_tools_node -> agent_router -> END

Tracks:
  - RevenueRecoveryState (TypedDict with metrics, tier, stopping rules, messages)
  - Hinglish outreach nudges
  - Immutable compliance guard checking DNC & max retries
"""

import os
import json
import time
from typing import Annotated, Literal, Sequence, List, Dict, Any, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from core.detector import DetectionResult
from core.diagnoser import DiagnosisResult, diagnose
from core.rag_retriever import RAGRetriever, build_query
from core.policy import get_intervention_sequence, action_metadata
from core.executor import _seeded_rng, _sample_outcome, RECOVERY_OUTCOMES
from core.hinglish_templates import (
    format_sms_hinglish,
    format_voice_ivr_hinglish,
    format_email_hinglish,
)


# ---------------------------------------------------------------------------
# 1. State Definition
# ---------------------------------------------------------------------------

class RevenueRecoveryState(TypedDict):
    # Core Chat & Execution Records
    messages:             Annotated[Sequence[BaseMessage], add_messages]
    
    # Financial Trackers
    record_id:            str
    account_id:           str
    invoice_id:           str
    customer_name:        str
    risk_category:        str   # payment_failure | checkout_abandonment | overdue_receivable
    revenue_at_risk:      float
    revenue_recovered:    float
    
    # Compliance & Guardrails
    retry_count:          int
    contact_count:        int
    max_retries_allowed:  int
    max_contacts_allowed: int
    escalation_tier:      Literal["soft_nudge", "firm_warning", "account_hold", "legal_escalation"]
    is_halted:            bool
    halt_reason:          Optional[str]
    do_not_contact:       bool
    
    # Policy & Action Log
    sequence:             List[str]
    current_action_idx:   int
    actions_taken:        List[Dict[str, Any]]
    final_status:         str   # recovered | still_failed | escalated | written_off | skipped


# ---------------------------------------------------------------------------
# 2. Node Implementations
# ---------------------------------------------------------------------------

def agent_router(state: RevenueRecoveryState) -> Dict[str, Any]:
    """
    Central brain node determining the next intervention action.
    """
    if state.get("is_halted") or state.get("final_status") in ("recovered", "escalated", "written_off", "skipped"):
        return {"messages": [SystemMessage(content="Workflow completed or halted.")]}

    sequence = state.get("sequence", [])
    idx      = state.get("current_action_idx", 0)

    if idx >= len(sequence):
        # All actions exhausted
        return {
            "is_halted": True,
            "halt_reason": "Sequence exhausted",
            "messages": [SystemMessage(content="Intervention sequence finished.")],
        }

    next_action = sequence[idx]
    return {
        "messages": [AIMessage(content=f"PROPOSE_ACTION:{next_action}")],
    }


def compliance_guard_node(state: RevenueRecoveryState) -> Dict[str, Any]:
    """
    System-level enforcement node that inspects proposed actions before execution.
    If policy is violated, sets is_halted = True.
    """
    if state.get("is_halted"):
        return {}

    # DNC Check
    if state.get("do_not_contact"):
        return {
            "is_halted": True,
            "halt_reason": "DNC flag present — no contact permitted",
            "final_status": "skipped",
            "messages": [SystemMessage(content="Compliance Guard: Blocked due to DNC flag.")],
        }

    # Get proposed action from last AI message
    last_msg = state["messages"][-1] if state.get("messages") else None
    if not last_msg or not hasattr(last_msg, "content") or not last_msg.content.startswith("PROPOSE_ACTION:"):
        return {}

    proposed_action = last_msg.content.split("PROPOSE_ACTION:")[1].strip()
    meta = action_metadata(proposed_action)

    # Check retry caps
    if meta["is_retry"] and state["retry_count"] >= state["max_retries_allowed"]:
        return {
            "is_halted": True,
            "halt_reason": f"Max retries limit reached ({state['max_retries_allowed']})",
            "messages": [SystemMessage(content="Compliance Guard: Blocked — max retries exceeded.")],
        }

    # Check contact frequency caps
    if meta["is_contact"] and state["contact_count"] >= state["max_contacts_allowed"]:
        return {
            "is_halted": True,
            "halt_reason": f"Max contact frequency cap reached ({state['max_contacts_allowed']})",
            "messages": [SystemMessage(content="Compliance Guard: Blocked — contact cap exceeded.")],
        }

    return {"messages": [SystemMessage(content=f"Compliance Guard: Action {proposed_action} APPROVED.")]}


def execute_tools_node(state: RevenueRecoveryState) -> Dict[str, Any]:
    """
    Executes approved recovery tools (retries, Hinglish nudges, escalations).
    """
    if state.get("is_halted"):
        return {}

    last_msg = state["messages"][-2] if len(state.get("messages", [])) >= 2 else None
    if not last_msg or not hasattr(last_msg, "content") or not last_msg.content.startswith("PROPOSE_ACTION:"):
        return {}

    action = last_msg.content.split("PROPOSE_ACTION:")[1].strip()
    idx    = state.get("current_action_idx", 0)
    meta   = action_metadata(action)
    rng    = _seeded_rng(state["record_id"], idx + 1)
    outcome = _sample_outcome(action, rng)

    new_retry_count   = state["retry_count"] + (1 if meta["is_retry"] else 0)
    new_contact_count = state["contact_count"] + (1 if meta["is_contact"] else 0)

    revenue_rec = state["revenue_at_risk"] if outcome in RECOVERY_OUTCOMES else 0.0
    total_recovered = state["revenue_recovered"] + revenue_rec

    # Hinglish multi-channel outreach payload generation
    outreach_payload = None
    if meta["is_contact"]:
        if "voice" in action or action == "offer_payment_plan":
            outreach_payload = format_voice_ivr_hinglish(state["customer_name"], state["revenue_at_risk"])
        else:
            outreach_payload = format_sms_hinglish(state["customer_name"], state["revenue_at_risk"], action)

    action_record = {
        "action": action,
        "action_number": idx + 1,
        "outcome": outcome,
        "revenue_recovered": revenue_rec,
        "outreach_payload": outreach_payload,
        "timestamp": time.time(),
    }

    actions_taken = list(state.get("actions_taken", [])) + [action_record]

    # Status mapping
    new_status = state["final_status"]
    is_halted  = False
    halt_reason = state.get("halt_reason")

    if outcome in ("recovered", "converted", "accepted"):
        new_status = "recovered"
        is_halted  = True
        halt_reason = "Revenue successfully recovered"
    elif outcome == "escalated":
        new_status = "escalated"
        is_halted  = True
        halt_reason = "Escalated to human agent"
    elif outcome == "written_off":
        new_status = "written_off"
        is_halted  = True
        halt_reason = "Marked uncollectable"
    elif outcome == "skipped":
        new_status = "skipped"
        is_halted  = True

    return {
        "retry_count":          new_retry_count,
        "contact_count":        new_contact_count,
        "revenue_recovered":    total_recovered,
        "current_action_idx":   idx + 1,
        "actions_taken":        actions_taken,
        "final_status":         new_status,
        "is_halted":            is_halted,
        "halt_reason":          halt_reason,
        "messages":             [SystemMessage(content=f"Tool Execution: {action} -> {outcome}")],
    }


# ---------------------------------------------------------------------------
# 3. Routing Conditionals
# ---------------------------------------------------------------------------

def route_after_agent(state: RevenueRecoveryState) -> str:
    if state.get("is_halted"):
        return "end"
    last_msg = state["messages"][-1] if state.get("messages") else None
    if last_msg and hasattr(last_msg, "content") and last_msg.content.startswith("PROPOSE_ACTION:"):
        return "compliance_guard"
    return "end"


def route_after_guard(state: RevenueRecoveryState) -> str:
    if state.get("is_halted"):
        return "end"
    return "tools"


# ---------------------------------------------------------------------------
# 4. Workflow Assembly
# ---------------------------------------------------------------------------

def build_recovery_graph() -> StateGraph:
    """Build and compile the LangGraph recovery workflow."""
    wf = StateGraph(RevenueRecoveryState)

    wf.add_node("agent", agent_router)
    wf.add_node("compliance_guard", compliance_guard_node)
    wf.add_node("tools", execute_tools_node)

    wf.add_edge(START, "agent")

    wf.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "compliance_guard": "compliance_guard",
            "end": END,
        },
    )

    wf.add_conditional_edges(
        "compliance_guard",
        route_after_guard,
        {
            "tools": "tools",
            "end": END,
        },
    )

    wf.add_edge("tools", "agent")

    return wf.compile()


# ---------------------------------------------------------------------------
# 5. Public Pipeline Function
# ---------------------------------------------------------------------------

def run_langgraph_record(
    event: Dict[str, Any],
    detection: DetectionResult,
    diagnosis: Optional[DiagnosisResult] = None,
    sequence: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Executes a single event through the LangGraph State Machine.
    """
    if sequence is None:
        sequence = get_intervention_sequence(detection, diagnosis)

    init_state: RevenueRecoveryState = {
        "messages":             [SystemMessage(content=f"Starting recovery for {event['record_id']}")],
        "record_id":            event["record_id"],
        "account_id":           event.get("customer_id", "ACC-UNKNOWN"),
        "invoice_id":           event.get("invoice_id", "INV-UNKNOWN"),
        "customer_name":        event.get("customer_name", "Valued Customer"),
        "risk_category":        detection.category,
        "revenue_at_risk":      float(event.get("amount", 0.0)),
        "revenue_recovered":    0.0,
        "retry_count":          0,
        "contact_count":        0,
        "max_retries_allowed":  3,
        "max_contacts_allowed": 3,
        "escalation_tier":      "soft_nudge",
        "is_halted":            False,
        "halt_reason":          None,
        "do_not_contact":       bool(detection.do_not_contact),
        "sequence":             sequence,
        "current_action_idx":   0,
        "actions_taken":        [],
        "final_status":         "still_failed",
    }

    graph_app = build_recovery_graph()
    final_state = graph_app.invoke(init_state)
    return final_state


# ---------------------------------------------------------------------------
# 6. Compatibility Helper (Maps LangGraph State to ExecutionResult)
# ---------------------------------------------------------------------------

from core.executor import ActionResult, ExecutionResult

def state_to_execution_result(
    state: RevenueRecoveryState, event: Dict[str, Any]
) -> ExecutionResult:
    """Map final RevenueRecoveryState into standard ExecutionResult dataclass."""
    actions = [
        ActionResult(
            action=a["action"],
            action_number=a["action_number"],
            outcome=a["outcome"],
            revenue_recovered=a["revenue_recovered"],
            stopping_rule=state.get("halt_reason") if i == len(state.get("actions_taken", [])) - 1 and state.get("is_halted") else None,
            reason=f"LangGraph Node: {a['action']} -> {a['outcome']}",
        )
        for i, a in enumerate(state.get("actions_taken", []))
    ]
    if not actions:
        actions = [
            ActionResult(
                action="no_action",
                action_number=0,
                outcome="skipped",
                revenue_recovered=0.0,
                stopping_rule=state.get("halt_reason"),
                reason=state.get("halt_reason", "DNC / skipped"),
            )
        ]

    return ExecutionResult(
        record_id=state["record_id"],
        event_type=event["event_type"],
        amount=state["revenue_at_risk"],
        final_status=state["final_status"],
        revenue_recovered=state["revenue_recovered"],
        actions_taken=actions,
        stopping_rule=state.get("halt_reason"),
    )
