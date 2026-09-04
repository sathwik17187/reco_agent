"""
api_server.py — FastAPI Web Server for Razorpay Revenue Recovery Agent Dashboard

Provides REST APIs for dashboard statistics, customer record exploration,
audit trace inspection, RAG policy docs, live pipeline execution, and interactive event simulation.
"""

import asyncio
import json
import os
import sys
import subprocess
from typing import Dict, Any, List, Optional
import pandas as pd

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

# Ensure recovery_agent directory is on path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Core imports for simulation & pipeline
from core.detector import detect
from core.policy import get_intervention_sequence, POLICY_TABLE
from core.hinglish_templates import format_sms_hinglish, format_email_hinglish, format_voice_ivr_hinglish
from core.rl_bandit import get_bandit, extract_feature_vector
from core.ingestion import load_events
from core.rag_retriever import RAGRetriever, build_query
from core.diagnoser import diagnose
from core.langgraph_agent import run_langgraph_record, state_to_execution_result
from data.data_gen import generate_all


app = FastAPI(
    title="Razorpay Revenue Recovery Agent API",
    description="Backend API for Revenue Recovery Agent Dashboard",
    version="1.0.0",
)

# Enable CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
POLICY_DIR = os.path.join(DATA_DIR, "policy_docs")

# Global pipeline execution state
pipeline_status = {
    "is_running": False,
    "last_run": None,
    "logs": [],
    "error": None
}


def load_recovery_report() -> Dict[str, Any]:
    report_path = os.path.join(OUTPUT_DIR, "recovery_report.json")
    if not os.path.exists(report_path):
        return {}
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_audit_logs() -> List[Dict[str, Any]]:
    audit_path = os.path.join(OUTPUT_DIR, "audit.jsonl")
    if not os.path.exists(audit_path):
        return []
    logs = []
    with open(audit_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    logs.append(json.loads(line))
                except Exception:
                    pass
    return logs


def load_ground_truth() -> Dict[str, Any]:
    gt_path = os.path.join(DATA_DIR, "ground_truth.json")
    if not os.path.exists(gt_path):
        return {}
    with open(gt_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {item["record_id"]: item for item in data if isinstance(item, dict) and "record_id" in item}
    elif isinstance(data, dict):
        return data
    return {}


class LiveAgentSession:

    """
    Stateful real-time session manager for sequential one-by-one agent execution.
    Maintains running metrics, audit trail, LinUCB arm adaptations, and ground truth scoring.
    """
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self.gt_data: Dict[str, Any] = {}
        self.current_index: int = 0
        self.is_streaming: bool = False
        self.speed_ms: int = 250
        self.task: Optional[asyncio.Task] = None
        self.processed_records: List[Dict[str, Any]] = []
        self.latest_record: Optional[Dict[str, Any]] = None
        self.subscribers: List[asyncio.Queue] = []
        self.retriever: Optional[RAGRetriever] = None
        self.stats = self._init_stats()
        self.load_data()

    def _init_stats(self) -> Dict[str, Any]:
        return {
            "total_records": 0,
            "total_at_risk": 0.0,
            "total_recovered": 0.0,
            "recovery_rate_pct": 0.0,
            "by_final_status": {
                "recovered": {"count": 0, "amount": 0.0, "recovered": 0.0, "rate_pct": 0.0},
                "escalated": {"count": 0, "amount": 0.0, "recovered": 0.0, "rate_pct": 0.0},
                "still_failed": {"count": 0, "amount": 0.0, "recovered": 0.0, "rate_pct": 0.0},
                "skipped": {"count": 0, "amount": 0.0, "recovered": 0.0, "rate_pct": 0.0},
                "written_off": {"count": 0, "amount": 0.0, "recovered": 0.0, "rate_pct": 0.0},
            },
            "by_detection_category": {},
            "ground_truth_stats": {
                "detection_accuracy_pct": 100.0,
                "recovery_precision_pct": 100.0,
                "recovery_recall_pct": 100.0,
                "recovery_f1_pct": 100.0,
                "confusion_matrix": {"TP": 0, "FN": 0, "TN": 0, "FP": 0}
            }
        }

    def load_data(self):
        try:
            self.events = load_events(DATA_DIR)
        except Exception as e:
            print(f"[LiveAgent] Could not load events: {e}")
            self.events = []
        self.gt_data = load_ground_truth()
        if not self.retriever and os.path.exists(POLICY_DIR):
            try:
                self.retriever = RAGRetriever(persist_dir=os.path.join(BASE_DIR, "chroma_db"))
                self.retriever.ensure_index(POLICY_DIR)
            except Exception as ex:
                print(f"[LiveAgent] Warning initializing retriever: {ex}")

    def reset(self):
        self.is_streaming = False
        if self.task and not self.task.done():
            self.task.cancel()
            self.task = None
        self.current_index = 0
        self.processed_records = []
        self.latest_record = None
        self.stats = self._init_stats()
        self.load_data()
        self._broadcast({"type": "reset", "state": self.get_state()})

    def _broadcast(self, data: Dict[str, Any]):
        dead = []
        for q in self.subscribers:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def step_one(self) -> Optional[Dict[str, Any]]:
        if not self.events or self.current_index >= len(self.events):
            self.is_streaming = False
            return None

        event = self.events[self.current_index]
        rid = event["record_id"]

        # Step 1: Detect risk
        detection = detect(event)

        # Step 2: RAG & Diagnosis if ambiguous
        diag = None
        rag_snippets = []
        if detection.needs_llm and self.retriever:
            try:
                query = build_query(event, detection.category)
                snippets = self.retriever.retrieve(query, top_k=3)
                raw = self.retriever.retrieve_raw(query, top_k=3)
                diag = diagnose(event, detection, snippets, raw)
                rag_snippets = [s["doc_id"] for s in raw] if raw else []
            except Exception as ex:
                print(f"[LiveAgent] Diagnosis error for {rid}: {ex}")

        # Step 3: Policy intervention sequence
        sequence = get_intervention_sequence(detection, diag)

        # Step 4: LangGraph Execution
        state = run_langgraph_record(event, detection, diag, sequence)
        exec_res = state_to_execution_result(state, event)

        # Step 5: LinUCB Bandit update
        bandit = get_bandit()
        bandit_rec = bandit.select_arm(event, risk_level=detection.risk_level, dnc_flag=detection.do_not_contact)
        chosen_arm = bandit_rec.get("selected_arm", "no_action")
        is_rec = (exec_res.final_status == "recovered")
        bandit.update(
            arm=chosen_arm,
            event=event,
            risk_level=detection.risk_level,
            recovered=is_rec,
            amount_recovered=exec_res.revenue_recovered
        )

        # Step 6: Update running stats
        amt = float(event.get("amount", 0.0))
        rec_amt = float(exec_res.revenue_recovered)
        cat = detection.category
        status = exec_res.final_status

        self.stats["total_records"] += 1
        self.stats["total_at_risk"] = round(self.stats["total_at_risk"] + amt, 2)
        self.stats["total_recovered"] = round(self.stats["total_recovered"] + rec_amt, 2)
        if self.stats["total_at_risk"] > 0:
            self.stats["recovery_rate_pct"] = round((self.stats["total_recovered"] / self.stats["total_at_risk"]) * 100, 1)

        # by_final_status
        if status in self.stats["by_final_status"]:
            st_dict = self.stats["by_final_status"][status]
            st_dict["count"] += 1
            st_dict["amount"] = round(st_dict["amount"] + amt, 2)
            st_dict["recovered"] = round(st_dict["recovered"] + rec_amt, 2)
            if st_dict["amount"] > 0:
                st_dict["rate_pct"] = round((st_dict["recovered"] / st_dict["amount"]) * 100, 1)

        # by_detection_category
        if cat not in self.stats["by_detection_category"]:
            self.stats["by_detection_category"][cat] = {"count": 0, "amount": 0.0, "recovered": 0.0, "rate_pct": 0.0}
        cat_dict = self.stats["by_detection_category"][cat]
        cat_dict["count"] += 1
        cat_dict["amount"] = round(cat_dict["amount"] + amt, 2)
        cat_dict["recovered"] = round(cat_dict["recovered"] + rec_amt, 2)
        if cat_dict["amount"] > 0:
            cat_dict["rate_pct"] = round((cat_dict["recovered"] / cat_dict["amount"]) * 100, 1)

        # Ground truth comparison
        gt = self.gt_data.get(rid, {})
        gt_cm = self.stats["ground_truth_stats"]["confusion_matrix"]
        resolvable = gt.get("resolvable", True)
        if resolvable and is_rec:
            gt_cm["TP"] += 1
        elif resolvable and not is_rec:
            gt_cm["FN"] += 1
        elif not resolvable and not is_rec:
            gt_cm["TN"] += 1
        else:
            gt_cm["FP"] += 1

        tp, fn, tn, fp = gt_cm["TP"], gt_cm["FN"], gt_cm["TN"], gt_cm["FP"]
        prec = (tp / (tp + fp) * 100) if (tp + fp) > 0 else 100.0
        rec = (tp / (tp + fn) * 100) if (tp + fn) > 0 else 100.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 100.0
        self.stats["ground_truth_stats"]["recovery_precision_pct"] = round(prec, 1)
        self.stats["ground_truth_stats"]["recovery_recall_pct"] = round(rec, 1)
        self.stats["ground_truth_stats"]["recovery_f1_pct"] = round(f1, 1)

        # Record summary
        record_summary = {
            "record_id": rid,
            "event_type": event["event_type"],
            "customer_segment": event.get("customer_segment", "retail"),
            "amount": amt,
            "risk_level": detection.risk_level,
            "detection_category": cat,
            "final_status": status,
            "total_recovered": round(rec_amt, 2),
            "dnc_flag": detection.do_not_contact,
            "actions_count": len(exec_res.actions_taken),
            "actions_taken": [
                {
                    "action": a.action,
                    "outcome": a.outcome,
                    "revenue_recovered": a.revenue_recovered,
                    "reason": a.reason,
                    "logged_at": pd.Timestamp.now().isoformat()
                } for a in exec_res.actions_taken
            ],
            "diagnosis": {
                "root_cause": diag.diagnosis,
                "confidence": diag.confidence,
                "fallback": diag.llm_fallback
            } if diag else None,
            "rag_snippets": rag_snippets,
            "bandit_arm": chosen_arm,
            "rules_fired": detection.rules_fired,
            "detection_reason": detection.reason,
            "ground_truth": {
                "expected_status": "recovered" if gt.get("resolvable") else "escalated",
                "recovered": gt.get("resolvable", False),
                "reason": f"GT Category: {gt.get('gt_category', 'N/A')}"
            } if gt else {}
        }

        self.processed_records.insert(0, record_summary)
        self.latest_record = record_summary
        self.current_index += 1

        # Incremental audit line append
        try:
            audit_file = os.path.join(OUTPUT_DIR, "audit.jsonl")
            with open(audit_file, "a", encoding="utf-8") as af:
                for a in exec_res.actions_taken:
                    af.write(json.dumps({
                        "record_id": rid,
                        "event_type": event["event_type"],
                        "customer_segment": event.get("customer_segment", "retail"),
                        "amount": amt,
                        "stage": "execution",
                        "action": a.action,
                        "outcome": a.outcome,
                        "revenue_recovered": a.revenue_recovered,
                        "detection_category": cat,
                        "diagnosis": diag.diagnosis if diag else None,
                        "reason": a.reason,
                        "logged_at": pd.Timestamp.now().isoformat()
                    }) + "\n")
        except Exception:
            pass

        payload = {
            "type": "step",
            "record": record_summary,
            "stats": self.get_report(),
            "progress": {
                "current": self.current_index,
                "total": len(self.events),
                "pct": round((self.current_index / len(self.events)) * 100, 1)
            }
        }
        self._broadcast(payload)
        return payload

    def get_report(self) -> Dict[str, Any]:
        return {
            "generated_at": pd.Timestamp.now().isoformat(),
            "recovery_stats": {
                "total_records": self.stats["total_records"],
                "total_at_risk": self.stats["total_at_risk"],
                "total_recovered": self.stats["total_recovered"],
                "recovery_rate_pct": self.stats["recovery_rate_pct"],
                "by_final_status": self.stats["by_final_status"],
                "by_detection_category": self.stats["by_detection_category"],
            },
            "ground_truth_stats": self.stats["ground_truth_stats"],
            "top_exceptions": [
                {
                    "record_id": r["record_id"],
                    "event_type": r["event_type"],
                    "amount": r["amount"],
                    "detection_category": r["detection_category"],
                    "final_status": r["final_status"],
                    "reason": r["actions_taken"][-1]["reason"] if r["actions_taken"] else "Unresolved"
                }
                for r in self.processed_records if r["final_status"] != "recovered"
            ][:10]
        }

    def get_state(self) -> Dict[str, Any]:
        total = len(self.events)
        return {
            "is_streaming": self.is_streaming,
            "current_index": self.current_index,
            "total_records": total,
            "speed_ms": self.speed_ms,
            "progress_pct": round((self.current_index / total * 100), 1) if total else 0,
            "stats": self.get_report(),
            "latest_record": self.latest_record,
            "recent_records": self.processed_records[:20]
        }

    async def _stream_loop(self):
        while self.is_streaming and self.current_index < len(self.events):
            self.step_one()
            await asyncio.sleep(self.speed_ms / 1000.0)
        self.is_streaming = False
        self._broadcast({"type": "complete", "state": self.get_state()})

    def start_stream(self, speed_ms: Optional[int] = None):
        if speed_ms is not None:
            self.speed_ms = max(20, speed_ms)
        self.is_streaming = True
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._stream_loop())

    def pause_stream(self):
        self.is_streaming = False
        if self.task and not self.task.done():
            self.task.cancel()
            self.task = None
        self._broadcast({"type": "pause", "state": self.get_state()})

    def fast_forward(self, count: int = 50):
        target = min(len(self.events), self.current_index + count)
        while self.current_index < target:
            self.step_one()
        return self.get_state()


live_session = LiveAgentSession()





def build_records_summary() -> List[Dict[str, Any]]:
    audit_logs = load_audit_logs()
    gt_data = load_ground_truth()
    report = load_recovery_report()
    exceptions_map = {
        e["record_id"]: e for e in report.get("exceptions", [])
        if isinstance(e, dict) and "record_id" in e
    }
    
    # Group audit entries by record_id
    records_dict: Dict[str, List[Dict[str, Any]]] = {}
    for entry in audit_logs:
        rid = entry.get("record_id")
        if rid:
            if rid not in records_dict:
                records_dict[rid] = []
            records_dict[rid].append(entry)

    summary_list = []

    for rid, entries in records_dict.items():
        # Identify detection entry
        det_entries = [e for e in entries if e.get("stage") == "detection"]
        det_entry = det_entries[0] if det_entries else entries[0]
        exec_entries = [e for e in entries if e.get("stage") == "execution"]
        
        # Calculate totals & final state
        total_recovered = 0.0
        final_status = "unresolved"
        detection_category = det_entry.get("detection_category", "UNKNOWN")
        risk_level = det_entry.get("risk_level", "MEDIUM")
        event_type = det_entry.get("event_type", "failed_payment")
        amount = float(det_entry.get("amount", 0.0))
        customer_segment = det_entry.get("customer_segment", "retail")
        dnc_flag = bool(det_entry.get("dnc_flag", False))
        
        actions_taken = []
        diagnosis_info = None
        rag_snippets = []

        # Extract diagnosis / rag from any logged entry
        for e in entries:
            if e.get("diagnosis") and not diagnosis_info:
                diagnosis_info = {
                    "root_cause": e.get("diagnosis"),
                    "confidence": e.get("llm_confidence"),
                    "fallback": e.get("llm_fallback")
                }
            if e.get("rag_snippets_used") and not rag_snippets:
                rag_snippets = e.get("rag_snippets_used")

        for e in exec_entries:
            rec_amt = float(e.get("revenue_recovered", 0.0))
            total_recovered += rec_amt
            actions_taken.append({
                "action": e.get("action"),
                "outcome": e.get("outcome"),
                "revenue_recovered": rec_amt,
                "reason": e.get("reason"),
                "logged_at": e.get("logged_at")
            })

        # Determine authoritative final_status:
        # First priority: check exception map from recovery_report
        if rid in exceptions_map:
            final_status = exceptions_map[rid].get("final_status", "still_failed")
        elif total_recovered > 0 or any(e.get("outcome") in ("recovered", "converted", "accepted") for e in exec_entries):
            final_status = "recovered"
        elif any(e.get("outcome") == "escalated" or e.get("action") == "escalate_human" or "escalat" in str(e.get("stopping_rule_triggered", "")).lower() for e in exec_entries):
            final_status = "escalated"
        elif any(e.get("outcome") == "written_off" or e.get("action") == "mark_uncollectable" or "written" in str(e.get("stopping_rule_triggered", "")).lower() for e in exec_entries):
            final_status = "written_off"
        elif dnc_flag or any(e.get("outcome") == "skipped" or e.get("action") == "no_action" for e in exec_entries):
            final_status = "skipped"
        elif exec_entries:
            final_status = "still_failed"
        elif dnc_flag or det_entry.get("outcome") == "skipped":
            final_status = "skipped"

        gt_raw = gt_data.get(rid, {})
        gt_info = {
            **gt_raw,
            "expected_status": "recovered" if gt_raw.get("resolvable") else ("skipped" if gt_raw.get("do_not_contact") else "escalated"),
            "recovered": gt_raw.get("resolvable", False),
            "reason": f"GT Category: {gt_raw.get('gt_category', 'N/A')}, Disposition: {gt_raw.get('gt_disposition', 'N/A')}"
        } if gt_raw else {}

        summary_list.append({
            "record_id": rid,
            "event_type": event_type,
            "customer_segment": customer_segment,
            "amount": amount,
            "risk_level": risk_level,
            "detection_category": detection_category,
            "final_status": final_status,
            "total_recovered": round(total_recovered, 2),
            "dnc_flag": dnc_flag,
            "actions_count": len(actions_taken),
            "actions_taken": actions_taken,
            "diagnosis": diagnosis_info,
            "rag_snippets": rag_snippets,
            "ground_truth": gt_info,
            "rules_fired": det_entry.get("rules_fired", []),
            "detection_reason": det_entry.get("reason", "")
        })

    return summary_list


@app.get("/api/stats")
def get_stats():
    """Retrieve overall recovery statistics and ground truth evaluation."""
    if live_session.stats["total_records"] > 0:
        return live_session.get_report()

    report = load_recovery_report()
    if not report:
        return live_session.get_report()

    # Normalize ground truth key names to what the frontend expects
    if "ground_truth_scores" in report and "ground_truth_stats" not in report:
        gs = report.pop("ground_truth_scores")
        report["ground_truth_stats"] = {
            "detection_accuracy_pct":   gs.get("detection_accuracy_pct", 0),
            "recovery_precision_pct":   gs.get("recovery_precision_pct", 0),
            "recovery_recall_pct":      gs.get("recovery_recall_pct", 0),
            "recovery_f1_pct":          gs.get("recovery_f1_pct", 0),
            "confusion_matrix": {
                "TP": gs.get("true_positives", 0),
                "FN": gs.get("false_negatives", 0),
                "TN": gs.get("true_negatives", 0),
                "FP": gs.get("false_positives", 0),
            }
        }

    return report


@app.get("/api/records")
def get_records(
    search: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    risk: Optional[str] = None,
):
    """Retrieve list of processed customer recovery records with filtering."""
    if live_session.processed_records:
        records = list(live_session.processed_records)
    else:
        records = build_records_summary()
    
    if search:
        s = search.lower()
        records = [
            r for r in records
            if s in r["record_id"].lower()
            or s in r["customer_segment"].lower()
            or s in r["detection_category"].lower()
        ]

    if event_type:
        records = [r for r in records if r["event_type"] == event_type]

    if status:
        records = [r for r in records if r["final_status"] == status]

    if category:
        records = [r for r in records if r["detection_category"] == category]

    if risk:
        records = [r for r in records if r["risk_level"] == risk]

    return {
        "total": len(records),
        "records": records
    }


@app.get("/api/records/{record_id}")
def get_record_detail(record_id: str):
    """Retrieve detailed step-by-step audit trace for a specific record."""
    if live_session.processed_records:
        records = live_session.processed_records
    else:
        records = build_records_summary()

    record = next((r for r in records if r["record_id"] == record_id), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found.")

    # Generate sample WhatsApp & SMS templates for preview
    name = f"Customer ({record['customer_segment'].capitalize()})"
    pay_link = f"https://rzp.io/i/{record_id[-6:]}"
    
    act_type = record["actions_taken"][0]["action"] if record.get("actions_taken") else "send_reminder"
    wa_msg = format_sms_hinglish(name, record["amount"], act_type, pay_link)
    sms_msg = format_sms_hinglish(name, record["amount"], "send_reminder", pay_link)

    # Get raw audit steps
    all_logs = load_audit_logs()
    raw_steps = [log for log in all_logs if log.get("record_id") == record_id]

    return {
        "record": record,
        "raw_steps": raw_steps,
        "previews": {
            "whatsapp": wa_msg,
            "sms": sms_msg
        }
    }


# ---------------------------------------------------------------------------
# Live Sequential Agent Streaming Endpoints
# ---------------------------------------------------------------------------

class StreamStartReq(BaseModel):
    speed_ms: Optional[int] = 250

class FastForwardReq(BaseModel):
    count: Optional[int] = 50

class RegenerateReq(BaseModel):
    n_pay: int = 600
    n_cart: int = 250
    n_inv: int = 150


@app.get("/api/live/state")
def get_live_state():
    """Retrieve the current live streaming playback and progress state."""
    return live_session.get_state()


@app.post("/api/live/step")
def step_live_agent():
    """Execute the recovery agent on exactly one next record from the dataset."""
    res = live_session.step_one()
    if res is None:
        return {"status": "finished", "state": live_session.get_state()}
    return res


@app.post("/api/live/start")
def start_live_agent(req: StreamStartReq = StreamStartReq()):
    """Start continuous row-by-row playback streaming."""
    live_session.start_stream(req.speed_ms)
    return live_session.get_state()


@app.post("/api/live/pause")
def pause_live_agent():
    """Pause live agent row-by-row playback."""
    live_session.pause_stream()
    return live_session.get_state()


@app.post("/api/live/reset")
def reset_live_agent():
    """Reset live playback to record 0 and clear running metrics."""
    live_session.reset()
    return live_session.get_state()


@app.post("/api/live/fast-forward")
def fast_forward_agent(req: FastForwardReq = FastForwardReq()):
    """Rapidly process records in bulk without streaming delay."""
    return live_session.fast_forward(req.count or 50)


@app.get("/api/live/stream")
async def live_stream_sse():
    """Server-Sent Events endpoint streaming live agent updates row-by-row."""
    queue = asyncio.Queue()
    live_session.subscribers.append(queue)

    async def event_generator():
        init_data = json.dumps({"type": "init", "state": live_session.get_state()})
        yield f"data: {init_data}\n\n"
        try:
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in live_session.subscribers:
                live_session.subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/dataset/regenerate")
def regenerate_dataset_endpoint(req: RegenerateReq):
    """Regenerate synthetic dataset with custom row counts."""
    summary = generate_all(
        n_pay=req.n_pay,
        n_cart=req.n_cart,
        n_inv=req.n_inv,
        outdir=DATA_DIR
    )
    live_session.reset()
    return summary



@app.get("/api/policies")
def get_policies():
    """Retrieve policy documentation snippets from disk."""
    policies = []
    if os.path.exists(POLICY_DIR):
        for fname in sorted(os.listdir(POLICY_DIR)):
            if fname.endswith(".txt"):
                fpath = os.path.join(POLICY_DIR, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                policies.append({
                    "filename": fname,
                    "title": fname.replace("_", " ").replace(".txt", "").title(),
                    "content": content
                })
    return {"policies": policies}


class SimulationRequest(BaseModel):
    event_type: str = "failed_payment"
    customer_id: str = "cust_sim_123"
    amount: float = 25000.0
    failure_code: Optional[str] = "card_expired"
    customer_segment: str = "retail"
    dnc_flag: bool = False
    intent_score: Optional[float] = 0.85
    hours_overdue: Optional[int] = 0


@app.post("/api/simulate")
def simulate_event(req: SimulationRequest):
    """Simulate single transaction risk detection and policy intervention sequence."""
    event = {
        "record_id": f"sim_{req.customer_id}",
        "event_type": req.event_type,
        "amount": req.amount,
        "customer_segment": req.customer_segment,
        "failure_code": req.failure_code,
        "dnc_flag": req.dnc_flag,
        "intent_score": req.intent_score,
        "hours_overdue": req.hours_overdue,
    }

    # Step 1: Detect Risk
    res = detect(event)
    det_cat = res.category
    risk_lvl = res.risk_level
    needs_llm = res.needs_llm
    rules_fired = res.rules_fired
    reason = res.reason

    # Step 2: Look up intervention sequence
    sequence = get_intervention_sequence(res)
    max_retries = len(sequence)

    # Step 3: Render Hinglish messages
    amount_str = f"₹{req.amount:,.2f}"
    pay_link = f"https://rzp.io/i/sim123"
    act_type = sequence[0] if sequence else "send_reminder"
    whatsapp_preview = format_sms_hinglish("Valued Customer", req.amount, act_type, pay_link)
    sms_preview = format_sms_hinglish("Valued Customer", req.amount, "send_reminder", pay_link)

    # Step 4: Contextual Bandit (LinUCB) Recommendation
    bandit = get_bandit()
    bandit_rec = bandit.select_arm(event, risk_level=risk_lvl, dnc_flag=req.dnc_flag)

    return {
        "event": event,
        "detection": {
            "category": det_cat,
            "risk_level": risk_lvl,
            "needs_llm": needs_llm,
            "rules_fired": rules_fired,
            "reason": reason
        },
        "policy": {
            "intervention_sequence": sequence,
            "max_retries": max_retries
        },
        "rl_bandit": bandit_rec,
        "previews": {
            "whatsapp": whatsapp_preview,
            "sms": sms_preview
        }
    }


class RLRecommendRequest(BaseModel):
    record_id: Optional[str] = None
    event_type: str = "failed_payment"
    amount: float = 5000.0
    customer_segment: str = "retail"
    risk_level: str = "MEDIUM"
    dnc_flag: bool = False


class RLFeedbackRequest(BaseModel):
    arm: str
    event_type: str = "failed_payment"
    amount: float = 5000.0
    customer_segment: str = "retail"
    risk_level: str = "MEDIUM"
    recovered: bool = True
    amount_recovered: float = 5000.0
    discount_offered: float = 0.0


@app.get("/api/rl/bandit-stats")
def get_bandit_stats():
    """Retrieve LinUCB bandit training stats, arm counts, and expected rewards."""
    bandit = get_bandit()
    return bandit.get_summary()


@app.post("/api/rl/recommend")
def get_rl_recommendation(req: RLRecommendRequest):
    """Get LinUCB bandit optimal action recommendation with exploration bonus."""
    bandit = get_bandit()
    event = {
        "record_id": req.record_id or "sim_req",
        "event_type": req.event_type,
        "amount": req.amount,
        "customer_segment": req.customer_segment,
        "dnc_flag": req.dnc_flag,
    }
    result = bandit.select_arm(event, risk_level=req.risk_level, dnc_flag=req.dnc_flag)
    return {
        "event": event,
        "recommendation": result
    }


@app.post("/api/rl/feedback")
def submit_rl_feedback(req: RLFeedbackRequest):
    """Provide online reward feedback to update the LinUCB bandit weights."""
    bandit = get_bandit()
    event = {
        "amount": req.amount,
        "customer_segment": req.customer_segment,
        "event_type": req.event_type
    }
    bandit.update(
        arm=req.arm,
        event=event,
        risk_level=req.risk_level,
        recovered=req.recovered,
        amount_recovered=req.amount_recovered,
        discount_offered=req.discount_offered
    )
    return {"status": "updated", "arm": req.arm, "bandit_summary": bandit.get_summary()}


def _execute_agent_subprocess():
    global pipeline_status
    pipeline_status["is_running"] = True
    pipeline_status["logs"] = []
    pipeline_status["error"] = None
    
    try:
        cmd = [sys.executable, "-u", os.path.join(BASE_DIR, "run_agent.py")]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=BASE_DIR,
            encoding="utf-8",
            errors="replace"
        )
        for line in iter(proc.stdout.readline, ''):
            if line:
                pipeline_status["logs"].append(line.strip())
        proc.wait()
        if proc.returncode != 0:
            pipeline_status["error"] = f"Process exited with code {proc.returncode}"
    except Exception as ex:
        pipeline_status["error"] = str(ex)
    finally:
        pipeline_status["is_running"] = False
        pipeline_status["last_run"] = pd.Timestamp.now().isoformat()


@app.post("/api/run-agent")
def run_agent_pipeline(background_tasks: BackgroundTasks):
    """Trigger the python run_agent.py pipeline end-to-end in the background."""
    global pipeline_status
    if pipeline_status["is_running"]:
        raise HTTPException(status_code=400, detail="Pipeline is already running.")
    
    background_tasks.add_task(_execute_agent_subprocess)
    return {"status": "started", "message": "Pipeline execution started in background."}


@app.get("/api/pipeline-status")
def get_pipeline_status():
    """Check status and logs of background pipeline execution."""
    return pipeline_status


# Serve React app if build exists
FRONTEND_DIST = os.path.join(BASE_DIR, "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        target_file = os.path.join(FRONTEND_DIST, full_path)
        if os.path.exists(target_file) and os.path.isfile(target_file):
            return FileResponse(target_file)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
