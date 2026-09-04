"""
scorer.py — Layer 8: Recovery math, ground-truth scoring, and report generation.

Computes:
  - Total revenue at risk / recovered / recovery rate
  - Breakdown by event type, detection category, intervention type
  - Ground-truth accuracy: compares pipeline decisions against ground_truth.json
  - Exception table: every unrecovered record with a stated reason

Outputs:
  - recovery_report.json
  - exception_table.csv
  - report.html  (rich, self-contained HTML report)
"""

import csv
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.orchestrator import PipelineResult


# ---------------------------------------------------------------------------
# Ground-truth scoring
# ---------------------------------------------------------------------------

def load_ground_truth(path: str) -> Dict[str, Dict]:
    """Load ground_truth.json as a dict keyed by record_id."""
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)
    return {e["record_id"]: e for e in entries}


def score_against_ground_truth(
    results: List[PipelineResult],
    gt: Dict[str, Dict],
) -> Dict[str, Any]:
    """
    Compare pipeline outcomes against ground truth.

    Ground truth fields used:
      gt_category   : expected detection category
      gt_disposition: expected action hint
      resolvable    : whether the case should be recoverable

    Scoring:
      detection_correct  : pipeline category == gt_category
      disposition_correct: pipeline final action matches gt_disposition hint
      recoverable_correct: resolvable cases that were recovered (TP)
                           + unresolvable cases that were not recovered (TN)
    """
    detection_correct   = 0
    disposition_correct = 0
    recoverable_tp      = 0   # resolvable + recovered
    recoverable_fn      = 0   # resolvable + NOT recovered
    exception_tn        = 0   # unresolvable + correctly not recovered
    exception_fp        = 0   # unresolvable + wrongly recovered
    total_with_gt       = 0

    for r in results:
        rid = r.event["record_id"]
        if rid not in gt:
            continue
        total_with_gt += 1
        g = gt[rid]

        # Detection accuracy
        if r.detection.category == g.get("gt_category", ""):
            detection_correct += 1

        # Disposition accuracy (loose match on hint)
        hint        = g.get("gt_disposition", "")
        final_action = r.execution.actions_taken[-1].action if r.execution.actions_taken else ""
        if hint and hint != "llm_diagnosis_required":
            if hint in " ".join(r.sequence):
                disposition_correct += 1

        # Recovery accuracy
        resolvable = g.get("resolvable", True)
        recovered  = r.execution.final_status == "recovered"
        if resolvable and recovered:
            recoverable_tp += 1
        elif resolvable and not recovered:
            recoverable_fn += 1
        elif not resolvable and not recovered:
            exception_tn += 1
        else:
            exception_fp += 1

    precision = recoverable_tp / (recoverable_tp + exception_fp) if (recoverable_tp + exception_fp) > 0 else 0
    recall    = recoverable_tp / (recoverable_tp + recoverable_fn) if (recoverable_tp + recoverable_fn) > 0 else 0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    return {
        "total_with_ground_truth": total_with_gt,
        "detection_accuracy_pct":  round(detection_correct / total_with_gt * 100, 1) if total_with_gt else 0,
        "disposition_accuracy_pct": round(disposition_correct / total_with_gt * 100, 1) if total_with_gt else 0,
        "recovery_precision_pct":  round(precision * 100, 1),
        "recovery_recall_pct":     round(recall * 100, 1),
        "recovery_f1_pct":         round(f1 * 100, 1),
        "true_positives":          recoverable_tp,
        "false_negatives":         recoverable_fn,
        "true_negatives":          exception_tn,
        "false_positives":         exception_fp,
    }


# ---------------------------------------------------------------------------
# Recovery math
# ---------------------------------------------------------------------------

def compute_recovery_stats(results: List[PipelineResult]) -> Dict[str, Any]:
    total_at_risk  = sum(r.event.get("amount", 0) for r in results)
    total_recovered = sum(r.execution.revenue_recovered for r in results)
    recovery_rate  = total_recovered / total_at_risk if total_at_risk > 0 else 0

    by_status: Dict[str, Dict] = {}
    for r in results:
        s = r.execution.final_status
        if s not in by_status:
            by_status[s] = {"count": 0, "amount": 0.0, "recovered": 0.0}
        by_status[s]["count"]     += 1
        by_status[s]["amount"]    += r.event.get("amount", 0)
        by_status[s]["recovered"] += r.execution.revenue_recovered

    by_category: Dict[str, Dict] = {}
    for r in results:
        cat = r.detection.category
        if cat not in by_category:
            by_category[cat] = {"count": 0, "amount": 0.0, "recovered": 0.0}
        by_category[cat]["count"]     += 1
        by_category[cat]["amount"]    += r.event.get("amount", 0)
        by_category[cat]["recovered"] += r.execution.revenue_recovered

    by_event_type: Dict[str, Dict] = {}
    for r in results:
        et = r.event["event_type"]
        if et not in by_event_type:
            by_event_type[et] = {"count": 0, "amount": 0.0, "recovered": 0.0}
        by_event_type[et]["count"]     += 1
        by_event_type[et]["amount"]    += r.event.get("amount", 0)
        by_event_type[et]["recovered"] += r.execution.revenue_recovered

    # Round all floats
    for d in [by_status, by_category, by_event_type]:
        for v in d.values():
            v["amount"]    = round(v["amount"], 2)
            v["recovered"] = round(v["recovered"], 2)
            v["rate_pct"]  = round(v["recovered"] / v["amount"] * 100, 1) if v["amount"] else 0

    return {
        "total_records":       len(results),
        "total_at_risk":       round(total_at_risk, 2),
        "total_recovered":     round(total_recovered, 2),
        "recovery_rate_pct":   round(recovery_rate * 100, 1),
        "by_final_status":     by_status,
        "by_detection_category": by_category,
        "by_event_type":       by_event_type,
    }


# ---------------------------------------------------------------------------
# Exception table
# ---------------------------------------------------------------------------

def build_exception_table(results: List[PipelineResult]) -> List[Dict]:
    """Every unrecovered record with a reason."""
    exceptions = []
    non_recovered = {"still_failed", "escalated", "written_off", "skipped"}

    for r in results:
        if r.execution.final_status not in non_recovered:
            continue
        last_action = r.execution.actions_taken[-1] if r.execution.actions_taken else None
        exceptions.append({
            "record_id":        r.event["record_id"],
            "event_type":       r.event["event_type"],
            "customer_segment": r.event.get("customer_segment", ""),
            "amount":           r.event.get("amount", 0.0),
            "detection_category": r.detection.category,
            "diagnosis":        r.diagnosis.diagnosis if r.diagnosis else "N/A",
            "final_status":     r.execution.final_status,
            "last_action":      last_action.action if last_action else "none",
            "last_outcome":     last_action.outcome if last_action else "none",
            "stopping_rule":    r.execution.stopping_rule or "",
            "dnc_flag":         r.detection.do_not_contact,
            "reason":           last_action.reason if last_action else "no action taken",
            "sequence":         " -> ".join(r.sequence),
        })

    return sorted(exceptions, key=lambda x: x["amount"], reverse=True)


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

def write_json_report(
    stats:      Dict,
    gt_scores:  Optional[Dict],
    exceptions: List[Dict],
    output_dir: str,
):
    report = {
        "generated_at":    datetime.now().isoformat(),
        "recovery_stats":  stats,
        "ground_truth_scores": gt_scores,
        "exception_count": len(exceptions),
        "exceptions":      exceptions,
    }
    path = os.path.join(output_dir, "recovery_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# CSV exception table
# ---------------------------------------------------------------------------

def write_exception_csv(exceptions: List[Dict], output_dir: str) -> str:
    if not exceptions:
        return ""
    path = os.path.join(output_dir, "exception_table.csv")
    fieldnames = list(exceptions[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(exceptions)
    return path


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def _fmt_inr(amount: float) -> str:
    return f"INR {amount:,.2f}"


def write_html_report(
    stats:      Dict,
    gt_scores:  Optional[Dict],
    exceptions: List[Dict],
    results:    List[PipelineResult],
    output_dir: str,
) -> str:

    recovered_count  = stats["by_final_status"].get("recovered", {}).get("count", 0)
    escalated_count  = stats["by_final_status"].get("escalated", {}).get("count", 0)
    skipped_count    = stats["by_final_status"].get("skipped", {}).get("count", 0)
    written_off_count = stats["by_final_status"].get("written_off", {}).get("count", 0)
    still_failed_count = stats["by_final_status"].get("still_failed", {}).get("count", 0)

    # Category breakdown rows
    cat_rows = ""
    for cat, v in sorted(stats["by_detection_category"].items(), key=lambda x: -x[1]["amount"]):
        cat_rows += (
            f"<tr><td>{cat}</td><td>{v['count']}</td>"
            f"<td>{_fmt_inr(v['amount'])}</td>"
            f"<td>{_fmt_inr(v['recovered'])}</td>"
            f"<td><span class='badge {'green' if v['rate_pct']>50 else 'orange' if v['rate_pct']>0 else 'red'}'>"
            f"{v['rate_pct']}%</span></td></tr>\n"
        )

    # Exception rows (top 20)
    exc_rows = ""
    for e in exceptions[:20]:
        dnc = "<span class='badge red'>DNC</span>" if e["dnc_flag"] else ""
        exc_rows += (
            f"<tr><td>{e['record_id']}</td>"
            f"<td>{e['event_type']}</td>"
            f"<td>{e['customer_segment']}</td>"
            f"<td>{_fmt_inr(e['amount'])}</td>"
            f"<td>{e['detection_category']}</td>"
            f"<td>{e['diagnosis']}</td>"
            f"<td><span class='badge red'>{e['final_status']}</span></td>"
            f"<td>{e['last_action']}</td>"
            f"<td>{dnc} {e['stopping_rule'] or e['reason'][:60]}</td></tr>\n"
        )

    # GT scores block
    gt_block = ""
    if gt_scores:
        gt_block = f"""
        <div class="section">
          <h2>Ground Truth Accuracy</h2>
          <div class="cards">
            <div class="card blue">
              <div class="card-value">{gt_scores['detection_accuracy_pct']}%</div>
              <div class="card-label">Detection Accuracy</div>
            </div>
            <div class="card blue">
              <div class="card-value">{gt_scores['recovery_precision_pct']}%</div>
              <div class="card-label">Recovery Precision</div>
            </div>
            <div class="card blue">
              <div class="card-value">{gt_scores['recovery_recall_pct']}%</div>
              <div class="card-label">Recovery Recall</div>
            </div>
            <div class="card blue">
              <div class="card-value">{gt_scores['recovery_f1_pct']}%</div>
              <div class="card-label">F1 Score</div>
            </div>
          </div>
          <p style="margin-top:12px;color:#64748b;font-size:0.9rem;">
            TP={gt_scores['true_positives']} &nbsp;|&nbsp;
            FN={gt_scores['false_negatives']} &nbsp;|&nbsp;
            TN={gt_scores['true_negatives']} &nbsp;|&nbsp;
            FP={gt_scores['false_positives']}
          </p>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Revenue Recovery Agent — Report</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Inter',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:32px}}
  h1{{font-size:1.8rem;font-weight:700;color:#f8fafc;margin-bottom:4px}}
  h2{{font-size:1.1rem;font-weight:600;color:#cbd5e1;margin-bottom:16px;text-transform:uppercase;letter-spacing:.05em}}
  .subtitle{{color:#64748b;font-size:0.9rem;margin-bottom:32px}}
  .section{{background:#1e293b;border-radius:12px;padding:24px;margin-bottom:24px;border:1px solid #334155}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px}}
  .card{{background:#0f172a;border-radius:10px;padding:20px;text-align:center;border:1px solid #334155}}
  .card.green{{border-color:#10b981;background:linear-gradient(135deg,#064e3b22,#0f172a)}}
  .card.blue{{border-color:#3b82f6;background:linear-gradient(135deg,#1e3a5f22,#0f172a)}}
  .card.orange{{border-color:#f59e0b;background:linear-gradient(135deg,#78350f22,#0f172a)}}
  .card.red{{border-color:#ef4444;background:linear-gradient(135deg,#7f1d1d22,#0f172a)}}
  .card.purple{{border-color:#8b5cf6;background:linear-gradient(135deg,#4c1d9522,#0f172a)}}
  .card-value{{font-size:2rem;font-weight:700;color:#f8fafc;line-height:1}}
  .card-label{{font-size:0.75rem;color:#64748b;margin-top:8px;text-transform:uppercase;letter-spacing:.05em}}
  table{{width:100%;border-collapse:collapse;font-size:0.85rem}}
  th{{text-align:left;padding:10px 12px;background:#0f172a;color:#94a3b8;font-weight:500;border-bottom:1px solid #334155;text-transform:uppercase;font-size:0.75rem;letter-spacing:.05em}}
  td{{padding:10px 12px;border-bottom:1px solid #1e293b;color:#cbd5e1;vertical-align:top}}
  tr:hover td{{background:#1e293b88}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:20px;font-size:0.75rem;font-weight:500}}
  .badge.green{{background:#064e3b;color:#10b981}}
  .badge.orange{{background:#78350f;color:#f59e0b}}
  .badge.red{{background:#7f1d1d;color:#ef4444}}
  .badge.blue{{background:#1e3a5f;color:#60a5fa}}
</style>
</head>
<body>
<h1>Revenue Recovery Agent</h1>
<p class="subtitle">Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp; {stats['total_records']} records processed</p>

<div class="section">
  <h2>Recovery Summary</h2>
  <div class="cards">
    <div class="card purple">
      <div class="card-value">{_fmt_inr(stats['total_at_risk'])}</div>
      <div class="card-label">Total at Risk</div>
    </div>
    <div class="card green">
      <div class="card-value">{_fmt_inr(stats['total_recovered'])}</div>
      <div class="card-label">Recovered</div>
    </div>
    <div class="card {'green' if stats['recovery_rate_pct']>=50 else 'orange'}">
      <div class="card-value">{stats['recovery_rate_pct']}%</div>
      <div class="card-label">Recovery Rate</div>
    </div>
    <div class="card blue">
      <div class="card-value">{recovered_count}</div>
      <div class="card-label">Records Recovered</div>
    </div>
    <div class="card orange">
      <div class="card-value">{escalated_count}</div>
      <div class="card-label">Escalated</div>
    </div>
    <div class="card red">
      <div class="card-value">{still_failed_count + written_off_count}</div>
      <div class="card-label">Unresolved</div>
    </div>
  </div>
</div>

{gt_block}

<div class="section">
  <h2>Breakdown by Detection Category</h2>
  <table>
    <tr><th>Category</th><th>Count</th><th>At Risk</th><th>Recovered</th><th>Rate</th></tr>
    {cat_rows}
  </table>
</div>

<div class="section">
  <h2>Exception Table — Unrecovered Records ({len(exceptions)} total, showing top 20 by amount)</h2>
  <table>
    <tr><th>Record ID</th><th>Type</th><th>Segment</th><th>Amount</th>
        <th>Category</th><th>Diagnosis</th><th>Status</th><th>Last Action</th><th>Reason</th></tr>
    {exc_rows}
  </table>
</div>

</body></html>"""

    path = os.path.join(output_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


# ---------------------------------------------------------------------------
# Main scorer entry point
# ---------------------------------------------------------------------------

def score_and_report(
    results:    List[PipelineResult],
    output_dir: str,
    gt_path:    Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute all metrics, write all reports.
    Returns the full stats dict for programmatic access.
    """
    stats      = compute_recovery_stats(results)
    exceptions = build_exception_table(results)

    gt_scores = None
    if gt_path and os.path.exists(gt_path):
        gt = load_ground_truth(gt_path)
        gt_scores = score_against_ground_truth(results, gt)

    json_path = write_json_report(stats, gt_scores, exceptions, output_dir)
    csv_path  = write_exception_csv(exceptions, output_dir)
    html_path = write_html_report(stats, gt_scores, exceptions, results, output_dir)

    print(f"\n[Scorer] Reports written:")
    print(f"  {json_path}")
    if csv_path:
        print(f"  {csv_path}")
    print(f"  {html_path}")

    if gt_scores:
        print(f"\n[Scorer] Ground-truth accuracy:")
        print(f"  Detection accuracy  : {gt_scores['detection_accuracy_pct']}%")
        print(f"  Recovery precision  : {gt_scores['recovery_precision_pct']}%")
        print(f"  Recovery recall     : {gt_scores['recovery_recall_pct']}%")
        print(f"  F1 score            : {gt_scores['recovery_f1_pct']}%")

    return {"stats": stats, "gt_scores": gt_scores, "exceptions": exceptions}
