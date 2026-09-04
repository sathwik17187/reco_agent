"""
diagnoser.py — Layer 3b: RAG-augmented LLM diagnosis for ambiguous cases.

Only called for events where detector.needs_llm == True:
  - SOFT_DECLINE     (do_not_honor failure code)
  - LIKELY_UNCOLLECTABLE (invoice >90 days overdue)

For each case, the orchestrator:
  1. Retrieves relevant policy snippets via rag_retriever.retrieve()
  2. Passes them here alongside the event + detection context
  3. Gets back a DiagnosisResult with diagnosis, confidence, reasoning, policy_applied

LLM: llama3 via Ollama (local, no API key needed).
Retry: on any error → retry once after 2s → fallback to rule-based default.
JSON parsing: strips markdown fences, validates schema, raises on unknown fields.
"""

import json
import time
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import ollama

from core.detector import DetectionResult


LLM_MODEL            = "llama3"
LLM_TIMEOUT          = 60          # seconds
CONFIDENCE_THRESHOLD = 0.65        # below this → exception, not match

# Valid diagnosis values
VALID_DIAGNOSES = {
    "retryable_soft_decline",
    "probable_churn",
    "suspected_dispute",
    "confirm_write_off",
    "escalate_before_write_off",
    "unknown",
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DiagnosisResult:
    record_id:          str
    diagnosis:          str           # one of VALID_DIAGNOSES
    confidence:         float         # 0.0 – 1.0
    reasoning:          str           # one sentence from LLM
    recommended_hint:   str           # retry | escalate | payment_plan | write_off | skip
    policy_applied:     str           # which policy doc most influenced the decision
    rag_snippets_used:  List[str] = field(default_factory=list)   # doc_ids retrieved
    llm_fallback:       bool = False  # True if LLM failed and we used rule-based default
    llm_error:          Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id":         self.record_id,
            "diagnosis":         self.diagnosis,
            "confidence":        self.confidence,
            "reasoning":         self.reasoning,
            "recommended_hint":  self.recommended_hint,
            "policy_applied":    self.policy_applied,
            "rag_snippets_used": self.rag_snippets_used,
            "llm_fallback":      self.llm_fallback,
            "llm_error":         self.llm_error,
        }


# ---------------------------------------------------------------------------
# Rule-based fallback (no LLM)
# ---------------------------------------------------------------------------

_FALLBACK_DEFAULTS: Dict[str, Dict] = {
    "SOFT_DECLINE": {
        "diagnosis":        "retryable_soft_decline",
        "confidence":       0.50,
        "reasoning":        "LLM unavailable — defaulting to cautious retryable classification",
        "recommended_hint": "retry",
        "policy_applied":   "fallback_rule",
    },
    "LIKELY_UNCOLLECTABLE": {
        "diagnosis":        "escalate_before_write_off",
        "confidence":       0.50,
        "reasoning":        "LLM unavailable — defaulting to escalation before write-off",
        "recommended_hint": "escalate",
        "policy_applied":   "fallback_rule",
    },
}

def _rule_fallback(detection: DetectionResult, error: str) -> DiagnosisResult:
    defaults = _FALLBACK_DEFAULTS.get(detection.category, {
        "diagnosis":        "unknown",
        "confidence":       0.40,
        "reasoning":        "LLM unavailable — unknown category, routing to escalation",
        "recommended_hint": "escalate",
        "policy_applied":   "fallback_rule",
    })
    return DiagnosisResult(
        record_id=         detection.record_id,
        diagnosis=         defaults["diagnosis"],
        confidence=        defaults["confidence"],
        reasoning=         defaults["reasoning"],
        recommended_hint=  defaults["recommended_hint"],
        policy_applied=    defaults["policy_applied"],
        llm_fallback=      True,
        llm_error=         error,
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a payments recovery analyst at a fintech company.
Your job is to diagnose failed payment and overdue invoice cases that are ambiguous
and cannot be resolved by simple rules.

You will be given:
1. Relevant recovery policy snippets (retrieved from our internal playbook)
2. The transaction/event context (JSON)
3. The rule-based detection result

Your task: diagnose the case and recommend an intervention.

IMPORTANT RULES:
- Use the policy snippets to inform your judgment — cite the most relevant one
- Be conservative: when in doubt between retry and escalate, choose escalate
- For enterprise customers with large amounts, always lean toward human escalation
- Never recommend retrying a hard decline or a suspected dispute

Respond with ONLY valid JSON — no markdown, no explanation outside the JSON.
Schema:
{
  "diagnosis": "<one of: retryable_soft_decline | probable_churn | suspected_dispute | confirm_write_off | escalate_before_write_off>",
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<one sentence explaining your diagnosis, citing policy if relevant>",
  "recommended_hint": "<one of: retry | escalate | payment_plan | write_off>",
  "policy_applied": "<brief name of the policy doc that most influenced your decision>"
}"""


def _build_user_prompt(
    event: Dict[str, Any],
    detection: DetectionResult,
    policy_snippets: List[str],
) -> str:
    snippets_block = "\n\n---\n\n".join(policy_snippets) if policy_snippets else "No policy snippets retrieved."

    # Redact fields not needed by LLM
    event_for_llm = {k: v for k, v in event.items()
                     if k not in ("customer_email", "card_last4")}

    return f"""## Relevant Recovery Policies
{snippets_block}

## Transaction / Event Context
{json.dumps(event_for_llm, indent=2)}

## Detection Result
Category  : {detection.category}
Risk Level: {detection.risk_level}
Rule fired: {detection.reason}

## Task
Diagnose this case and fill in the JSON schema above."""


# ---------------------------------------------------------------------------
# JSON parser / validator
# ---------------------------------------------------------------------------

def _parse_llm_response(raw: str, record_id: str) -> Dict[str, Any]:
    """
    Strip markdown fences, parse JSON, validate required fields.
    Raises ValueError on parse/validation failure.
    """
    # Strip ```json ... ``` or ``` ... ``` fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Find first { ... } block
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {raw[:200]}")

    parsed = json.loads(match.group(0))

    required = {"diagnosis", "confidence", "reasoning", "recommended_hint", "policy_applied"}
    missing = required - set(parsed.keys())
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")

    if parsed["diagnosis"] not in VALID_DIAGNOSES:
        # coerce unknown diagnoses to "unknown" rather than crashing
        parsed["diagnosis"] = "unknown"

    parsed["confidence"] = max(0.0, min(1.0, float(parsed["confidence"])))
    return parsed


# ---------------------------------------------------------------------------
# Core LLM call
# ---------------------------------------------------------------------------

def _call_llm(user_prompt: str) -> str:
    """Single Ollama call. Raises on timeout or API error."""
    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        options={"temperature": 0.1},   # low temp for deterministic JSON output
    )
    return response["message"]["content"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def diagnose(
    event:           Dict[str, Any],
    detection:       DetectionResult,
    policy_snippets: List[str],
    raw_snippets:    Optional[List[Dict]] = None,  # from retrieve_raw(), for audit
) -> DiagnosisResult:
    """
    Run LLM diagnosis for an ambiguous event.

    Retries once on failure, then falls back to rule-based default.
    Never raises — always returns a DiagnosisResult.

    Args:
        event           : normalized Event dict from ingestion
        detection       : DetectionResult from detector
        policy_snippets : annotated text snippets from rag_retriever.retrieve()
        raw_snippets    : structured snippet dicts from retrieve_raw() (for audit trail)
    """
    user_prompt  = _build_user_prompt(event, detection, policy_snippets)
    snippet_ids  = [s["doc_id"] for s in (raw_snippets or [])]
    last_error   = None

    for attempt in range(2):   # try once, retry once
        try:
            raw = _call_llm(user_prompt)
            parsed = _parse_llm_response(raw, detection.record_id)

            return DiagnosisResult(
                record_id=        detection.record_id,
                diagnosis=        parsed["diagnosis"],
                confidence=       parsed["confidence"],
                reasoning=        parsed["reasoning"],
                recommended_hint= parsed["recommended_hint"],
                policy_applied=   parsed["policy_applied"],
                rag_snippets_used=snippet_ids,
                llm_fallback=     False,
                llm_error=        None,
            )

        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"parse_error (attempt {attempt+1}): {e}"
            if attempt == 0:
                time.sleep(1)   # brief pause before retry
                continue
            break

        except Exception as e:
            last_error = f"llm_error (attempt {attempt+1}): {type(e).__name__}: {e}"
            if attempt == 0:
                time.sleep(2)   # longer pause on API errors
                continue
            break

    # Both attempts failed — use rule-based fallback
    print(f"  [Diagnoser] FALLBACK for {detection.record_id}: {last_error}")
    return _rule_fallback(detection, last_error)


def diagnose_batch(
    cases:        List[Dict],   # list of (event, detection, snippets, raw_snippets)
    verbose:      bool = True,
) -> List[DiagnosisResult]:
    """
    Diagnose a list of cases sequentially.
    Each item in `cases` is a dict with keys:
      event, detection, policy_snippets, raw_snippets
    """
    results = []
    for i, case in enumerate(cases, 1):
        event     = case["event"]
        detection = case["detection"]
        snippets  = case.get("policy_snippets", [])
        raw       = case.get("raw_snippets", [])

        if verbose:
            print(f"  [{i}/{len(cases)}] diagnosing {detection.record_id} ({detection.category})...")

        result = diagnose(event, detection, snippets, raw)

        if verbose:
            flag = "⚠ FALLBACK" if result.llm_fallback else ""
            print(f"    -> {result.diagnosis} (conf={result.confidence:.2f}) {flag}")

        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from core.ingestion    import load_events
    from core.detector     import detect_batch
    from core.rag_retriever import RAGRetriever, build_query

    data_dir   = sys.argv[1] if len(sys.argv) > 1 else "data"
    policy_dir = sys.argv[2] if len(sys.argv) > 2 else "data/policy_docs"

    print("Loading events and running detection...")
    events     = load_events(data_dir)
    detections = detect_batch(events)

    event_map = {e["record_id"]: e for e in events}

    llm_cases_raw = [
        (event_map[d.record_id], d)
        for d in detections if d.needs_llm
    ]

    # Limit smoke-test to first 3 LLM cases
    test_cases = llm_cases_raw[:3]
    print(f"\nRunning LLM diagnosis on {len(test_cases)} cases (of {len(llm_cases_raw)} total)...")

    retriever = RAGRetriever(persist_dir="chroma_db")
    retriever.ensure_index(policy_dir)

    cases = []
    for event, detection in test_cases:
        query    = build_query(event, detection.category)
        snippets = retriever.retrieve(query, top_k=3)
        raw      = retriever.retrieve_raw(query, top_k=3)
        cases.append({"event": event, "detection": detection,
                       "policy_snippets": snippets, "raw_snippets": raw})

    results = diagnose_batch(cases, verbose=True)

    print("\n=== Diagnosis Results ===")
    for r in results:
        print(json.dumps(r.to_dict(), indent=2))
