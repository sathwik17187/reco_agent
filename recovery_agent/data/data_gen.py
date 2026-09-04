"""
data_gen.py — Synthetic event generator for the revenue recovery agent.

Produces three CSV files:
  - failed_payments.csv     (40 records)
  - abandoned_checkouts.csv (25 records)
  - overdue_invoices.csv    (20 records)

Plus a ground_truth.json with the expected diagnosis/disposition for each record.

Usage:
  python data_gen.py [--seed 42] [--outdir .]
"""

import argparse
import csv
import json
import random
import uuid
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 4, 12, 0, 0)  # fixed "now" for reproducibility


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.UUID(int=random.getrandbits(128)).hex[:10]}"


def _random_email(customer_id: str) -> str:
    domains = ["gmail.com", "yahoo.com", "outlook.com", "company.in", "biz.co.in"]
    return f"{customer_id.replace('_', '.')}@{random.choice(domains)}"


def _days_ago(n: int) -> str:
    return (NOW - timedelta(days=n)).isoformat()


CUSTOMER_SEGMENTS = ["retail", "smb", "enterprise"]
PAYMENT_METHODS   = ["card", "upi", "netbanking"]

# ---------------------------------------------------------------------------
# FAILED PAYMENTS
# ---------------------------------------------------------------------------

FAILURE_CODES = {
    "card_expired":        {"pct": 0.20, "needs_llm": False, "gt_category": "CARD_EXPIRED",        "gt_disposition": "send_card_update_link"},
    "insufficient_funds":  {"pct": 0.25, "needs_llm": False, "gt_category": "INSUFFICIENT_FUNDS",   "gt_disposition": "retry_payment_3d"},
    "gateway_timeout":     {"pct": 0.15, "needs_llm": False, "gt_category": "GATEWAY_TIMEOUT",      "gt_disposition": "retry_payment_immediate"},
    "do_not_honor":        {"pct": 0.25, "needs_llm": True,  "gt_category": "SOFT_DECLINE",         "gt_disposition": "llm_diagnosis_required"},
    "card_lost_stolen":    {"pct": 0.05, "needs_llm": False, "gt_category": "CARD_LOST",            "gt_disposition": "escalate_human"},
    "invalid_cvv":         {"pct": 0.10, "needs_llm": False, "gt_category": "INVALID_CVV",          "gt_disposition": "send_correction_link"},
}


def _weighted_failure_code(rng: random.Random) -> str:
    codes  = list(FAILURE_CODES.keys())
    weights = [FAILURE_CODES[c]["pct"] for c in codes]
    return rng.choices(codes, weights=weights, k=1)[0]


def generate_failed_payments(n: int, rng: random.Random):
    rows, gt = [], []
    # Guarantee at least one of every failure code
    forced_codes = list(FAILURE_CODES.keys())
    rng.shuffle(forced_codes)

    for i in range(n):
        payment_id = _uid("pay")
        customer_id = f"cust_{rng.randint(1000, 9999)}"
        code = forced_codes[i] if i < len(forced_codes) else _weighted_failure_code(rng)
        method = rng.choice(PAYMENT_METHODS)
        segment = rng.choice(CUSTOMER_SEGMENTS)
        amount = round(rng.uniform(500, 85000), 2)
        days_ago = rng.randint(0, 29)
        retry_count = rng.randint(0, 3)
        dnc = rng.random() < 0.05  # 5% do-not-contact

        row = {
            "payment_id":       payment_id,
            "customer_id":      customer_id,
            "customer_email":   _random_email(customer_id),
            "customer_segment": segment,
            "amount":           amount,
            "currency":         "INR",
            "payment_method":   method,
            "card_last4":       str(rng.randint(1000, 9999)) if method == "card" else "",
            "failure_code":     code,
            "retry_count":      retry_count,
            "timestamp":        _days_ago(days_ago),
            "do_not_contact":   str(dnc).lower(),
        }
        rows.append(row)

        meta = FAILURE_CODES[code]
        gt.append({
            "record_id":     payment_id,
            "event_type":    "failed_payment",
            "gt_category":   meta["gt_category"],
            "gt_disposition": meta["gt_disposition"],
            "needs_llm":     meta["needs_llm"],
            "do_not_contact": dnc,
            "amount":        amount,
            "resolvable":    not dnc,
        })

    return rows, gt


# ---------------------------------------------------------------------------
# ABANDONED CHECKOUTS
# ---------------------------------------------------------------------------

ABANDON_STEPS = {
    "address":      {"risk": "LOW",    "gt_category": "LOW_INTENT_ABANDON",    "gt_disposition": "skip"},
    "payment_info": {"risk": "MEDIUM", "gt_category": "MEDIUM_INTENT_ABANDON", "gt_disposition": "send_abandon_reminder"},
    "review":       {"risk": "HIGH",   "gt_category": "HIGH_INTENT_ABANDON",   "gt_disposition": "send_abandon_reminder"},
    "confirm":      {"risk": "HIGH",   "gt_category": "HIGH_INTENT_ABANDON",   "gt_disposition": "send_abandon_reminder"},
}


def generate_abandoned_checkouts(n: int, rng: random.Random):
    rows, gt = [], []
    steps = list(ABANDON_STEPS.keys())

    for _ in range(n):
        session_id  = _uid("sess")
        customer_id = f"cust_{rng.randint(1000, 9999)}"
        step        = rng.choice(steps)
        segment     = rng.choice(CUSTOMER_SEGMENTS)
        cart_value  = round(rng.uniform(200, 30000), 2)
        items_count = rng.randint(1, 10)
        days_ago    = rng.randint(0, 13)
        dnc         = rng.random() < 0.05

        row = {
            "session_id":        session_id,
            "customer_id":       customer_id,
            "customer_email":    _random_email(customer_id),
            "customer_segment":  segment,
            "cart_value":        cart_value,
            "items_count":       items_count,
            "abandoned_at_step": step,
            "timestamp":         _days_ago(days_ago),
            "do_not_contact":    str(dnc).lower(),
        }
        rows.append(row)

        meta = ABANDON_STEPS[step]
        gt.append({
            "record_id":     session_id,
            "event_type":    "abandoned_checkout",
            "gt_category":   meta["gt_category"],
            "gt_disposition": meta["gt_disposition"],
            "needs_llm":     False,
            "do_not_contact": dnc,
            "amount":        cart_value,
            "resolvable":    meta["risk"] != "LOW" and not dnc,
        })

    return rows, gt


# ---------------------------------------------------------------------------
# OVERDUE INVOICES
# ---------------------------------------------------------------------------

def _overdue_category(days: int) -> dict:
    if days <= 7:
        return {"gt_category": "MILDLY_OVERDUE",          "gt_disposition": "send_invoice_reminder",  "needs_llm": False}
    elif days <= 30:
        return {"gt_category": "MODERATELY_OVERDUE",      "gt_disposition": "send_invoice_reminder",  "needs_llm": False}
    elif days <= 90:
        return {"gt_category": "SEVERELY_OVERDUE",        "gt_disposition": "offer_payment_plan",     "needs_llm": False}
    else:
        return {"gt_category": "LIKELY_UNCOLLECTABLE",    "gt_disposition": "llm_diagnosis_required", "needs_llm": True}


def generate_overdue_invoices(n: int, rng: random.Random):
    rows, gt = [], []
    INVOICE_STATUSES = ["sent", "viewed", "ignored"]

    for _ in range(n):
        invoice_id      = _uid("inv")
        customer_id     = f"cust_{rng.randint(1000, 9999)}"
        segment         = rng.choice(CUSTOMER_SEGMENTS)
        amount          = round(rng.uniform(1000, 200000), 2)
        days_overdue    = rng.randint(1, 120)
        due_date        = NOW - timedelta(days=days_overdue)
        status          = rng.choice(INVOICE_STATUSES)
        contact_attempts = rng.randint(0, 5)
        dnc             = rng.random() < 0.05

        row = {
            "invoice_id":         invoice_id,
            "customer_id":        customer_id,
            "customer_email":     _random_email(customer_id),
            "customer_segment":   segment,
            "amount":             amount,
            "currency":           "INR",
            "due_date":           due_date.date().isoformat(),
            "days_overdue":       days_overdue,
            "invoice_status":     status,
            "contact_attempts":   contact_attempts,
            "timestamp":          due_date.isoformat(),
            "do_not_contact":     str(dnc).lower(),
        }
        rows.append(row)

        meta = _overdue_category(days_overdue)
        gt.append({
            "record_id":      invoice_id,
            "event_type":     "overdue_invoice",
            "gt_category":    meta["gt_category"],
            "gt_disposition": meta["gt_disposition"],
            "needs_llm":      meta["needs_llm"],
            "do_not_contact":  dnc,
            "amount":         amount,
            "resolvable":     days_overdue <= 90 and not dnc,
        })

    return rows, gt


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _write_csv(path: str, rows: list, fieldnames: list):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_all(n_pay: int = 600, n_cart: int = 250, n_inv: int = 150, outdir: str = ".", seed: int = 42):
    import os
    os.makedirs(outdir, exist_ok=True)
    random.seed(seed)
    rng = random.Random(seed)

    pay_rows,  pay_gt  = generate_failed_payments(n_pay,  rng)
    cart_rows, cart_gt = generate_abandoned_checkouts(n_cart, rng)
    inv_rows,  inv_gt  = generate_overdue_invoices(n_inv,  rng)

    # Shuffle within each type so order isn't predictable
    rng.shuffle(pay_rows)
    rng.shuffle(cart_rows)
    rng.shuffle(inv_rows)

    _write_csv(
        f"{outdir}/failed_payments.csv", pay_rows,
        ["payment_id","customer_id","customer_email","customer_segment","amount","currency",
         "payment_method","card_last4","failure_code","retry_count","timestamp","do_not_contact"],
    )
    _write_csv(
        f"{outdir}/abandoned_checkouts.csv", cart_rows,
        ["session_id","customer_id","customer_email","customer_segment","cart_value",
         "items_count","abandoned_at_step","timestamp","do_not_contact"],
    )
    _write_csv(
        f"{outdir}/overdue_invoices.csv", inv_rows,
        ["invoice_id","customer_id","customer_email","customer_segment","amount","currency",
         "due_date","days_overdue","invoice_status","contact_attempts","timestamp","do_not_contact"],
    )

    ground_truth = pay_gt + cart_gt + inv_gt
    with open(f"{outdir}/ground_truth.json", "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2)

    total = len(pay_rows) + len(cart_rows) + len(inv_rows)
    total_risk = sum(g["amount"] for g in ground_truth)
    llm_cases  = sum(1 for g in ground_truth if g["needs_llm"])
    dnc_cases  = sum(1 for g in ground_truth if g["do_not_contact"])
    summary = {
        "total": total,
        "n_pay": len(pay_rows),
        "n_cart": len(cart_rows),
        "n_inv": len(inv_rows),
        "total_risk": total_risk,
        "llm_cases": llm_cases,
        "dnc_cases": dnc_cases
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic recovery agent data")
    parser.add_argument("--seed",   type=int, default=42,  help="Random seed for reproducibility")
    parser.add_argument("--n_pay",  type=int, default=600, help="Number of failed payment records")
    parser.add_argument("--n_cart", type=int, default=250, help="Number of abandoned checkout records")
    parser.add_argument("--n_inv",  type=int, default=150, help="Number of overdue invoice records")
    parser.add_argument("--outdir", type=str, default=".", help="Output directory for CSV + JSON files")
    args = parser.parse_args()

    summary = generate_all(
        n_pay=args.n_pay,
        n_cart=args.n_cart,
        n_inv=args.n_inv,
        outdir=args.outdir,
        seed=args.seed
    )

    print(f"Generated {summary['total']} synthetic events:")
    print(f"  failed_payments.csv      -> {summary['n_pay']} rows")
    print(f"  abandoned_checkouts.csv  -> {summary['n_cart']} rows")
    print(f"  overdue_invoices.csv     -> {summary['n_inv']} rows")
    print(f"  ground_truth.json        -> {summary['total']} entries")
    print(f"  Total revenue at risk    : INR {summary['total_risk']:,.2f}")
    print(f"  Cases needing LLM        : {summary['llm_cases']}")
    print(f"  Do-not-contact flagged   : {summary['dnc_cases']}")
    print("NOTE: Do NOT read ground_truth.json from the matching engine.")


if __name__ == "__main__":
    main()

