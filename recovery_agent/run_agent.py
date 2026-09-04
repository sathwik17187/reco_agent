"""
run_agent.py — Single entrypoint for the Revenue Recovery Agent.

Runs the full pipeline end-to-end:
  1. Ingest events (failed payments, abandoned checkouts, overdue invoices)
  2. Detect risk (rule-based)
  3. Retrieve policy snippets via RAG (ChromaDB + nomic-embed-text)
  4. Diagnose ambiguous cases (llama3 via Ollama)
  5. Look up intervention sequence (policy table)
  6. Execute sequences (simulated outcomes)
  7. Write audit trail (audit.jsonl)
  8. Score against ground truth + generate reports

Usage:
  python run_agent.py
  python run_agent.py --data-dir data/ --output-dir output/ --gt-path data/ground_truth.json
  python run_agent.py --skip-llm   (fast run without LLM calls, for testing)
"""

import argparse
import os
import sys
import time

# Ensure recovery_agent root is on path when run from repo root
sys.path.insert(0, os.path.dirname(__file__))

from core.diagnoser import set_llm_model
from core.orchestrator import run as orchestrate
from core.scorer       import score_and_report


def parse_args():
    p = argparse.ArgumentParser(
        description="Revenue Recovery Agent — end-to-end pipeline"
    )
    p.add_argument(
        "--data-dir", default="data",
        help="Directory containing failed_payments.csv, abandoned_checkouts.csv, overdue_invoices.csv",
    )
    p.add_argument(
        "--output-dir", default="output",
        help="Directory for audit.jsonl, recovery_report.json, exception_table.csv, report.html",
    )
    p.add_argument(
        "--policy-dir", default=None,
        help="Directory containing policy .txt chunks (defaults to <data-dir>/policy_docs/)",
    )
    p.add_argument(
        "--gt-path", default=None,
        help="Path to ground_truth.json for accuracy scoring (optional)",
    )
    p.add_argument(
        "--model", default="qwen2.5:0.5b",
        help="Ollama model for diagnosis (default: qwen2.5:0.5b for speed, or llama3)",
    )
    p.add_argument(
        "--verbose", action="store_true", default=True,
        help="Print progress to stdout",
    )
    return p.parse_args()


def main():
    args = parse_args()

    # Resolve paths relative to script location
    base_dir   = os.path.dirname(os.path.abspath(__file__))
    data_dir   = os.path.join(base_dir, args.data_dir)
    output_dir = os.path.join(base_dir, args.output_dir)
    policy_dir = os.path.join(base_dir, args.policy_dir) if args.policy_dir else None
    gt_path    = os.path.join(base_dir, args.gt_path) if args.gt_path else \
                 os.path.join(data_dir, "ground_truth.json")

    print("=" * 60)
    print("  Revenue Recovery Agent (LangGraph + Ollama)")
    print("=" * 60)
    print(f"  Data dir    : {data_dir}")
    print(f"  Output dir  : {output_dir}")
    print(f"  Model       : {args.model}")
    print(f"  GT path     : {gt_path if os.path.exists(gt_path) else '(not found)'}")
    print("=" * 60)

    set_llm_model(args.model)

    t0 = time.time()

    # Run pipeline
    results = orchestrate(
        data_dir=data_dir,
        output_dir=output_dir,
        policy_dir=policy_dir,
        verbose=args.verbose,
    )

    # Score and report
    gt = gt_path if os.path.exists(gt_path) else None
    score_and_report(results, output_dir, gt_path=gt)

    elapsed = time.time() - t0
    print(f"\n[Done] Total runtime: {elapsed:.1f}s")
    print(f"       Open report : {os.path.join(output_dir, 'report.html')}")


if __name__ == "__main__":
    main()
