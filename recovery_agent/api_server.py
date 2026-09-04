"""
api_server.py — FastAPI Web Server for Razorpay Revenue Recovery Agent Dashboard

Provides REST APIs for dashboard statistics, customer record exploration,
audit trace inspection, RAG policy docs, live pipeline execution, and interactive event simulation.
"""

import json
import os
import sys
import subprocess
from typing import Dict, Any, List, Optional
import pandas as pd

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Ensure recovery_agent directory is on path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Core imports for simulation & pipeline
from core.detector import detect
from core.policy import get_intervention_sequence, POLICY_TABLE
from core.hinglish_templates import format_sms_hinglish, format_email_hinglish, format_voice_ivr_hinglish

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
    report = load_recovery_report()
    if not report:
        raise HTTPException(status_code=404, detail="Recovery report not found. Run agent first.")

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
    records = build_records_summary()
    record = next((r for r in records if r["record_id"] == record_id), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found.")

    # Generate sample WhatsApp & SMS templates for preview
    name = f"Customer ({record['customer_segment'].capitalize()})"
    amount_str = f"₹{record['amount']:,.2f}"
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
        "previews": {
            "whatsapp": whatsapp_preview,
            "sms": sms_preview
        }
    }


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
