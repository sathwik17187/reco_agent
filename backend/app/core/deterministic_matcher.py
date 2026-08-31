
import csv
from datetime import datetime


def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["amount"] = float(row["amount"])
            row["date"] = datetime.fromisoformat(row["date"])
            rows.append(row)
    return rows


def index_by_ref(rows):
    index = {}
    for row in rows:
        index.setdefault(row["txn_ref"], []).append(row)
    return index


def deterministic_match(gateway, bank, ledger, amount_tolerance=0.01, date_tolerance_days=1):
    bank_idx = index_by_ref(bank)
    ledger_idx = index_by_ref(ledger)

    matched = []
    needs_review = []

    for row in gateway:
        ref = row["txn_ref"]
        bank_rows = bank_idx.get(ref, [])
        ledger_rows = ledger_idx.get(ref, [])

        if not bank_rows:
            needs_review.append({"gateway_record": row, "reason": "missing_in_bank"})
            continue

        if not ledger_rows:
            needs_review.append({"gateway_record": row, "reason": "missing_in_ledger"})
            continue

        bank_sum = sum(r["amount"] for r in bank_rows)
        ledger_amount = ledger_rows[0]["amount"]

        bank_diff = bank_sum - row["amount"]
        ledger_diff = ledger_amount - row["amount"]

        if abs(bank_diff) >= amount_tolerance or abs(ledger_diff) >= amount_tolerance:
            needs_review.append({
                "gateway_record": row,
                "bank_records": bank_rows,
                "ledger_record": ledger_rows[0],
                "reason": "amount_mismatch",
                "bank_diff": round(bank_diff, 2),
                "ledger_diff": round(ledger_diff, 2),
            })
            continue

        max_date_gap = max(abs((r["date"] - row["date"]).days) for r in bank_rows)

        if max_date_gap > date_tolerance_days:
            needs_review.append({
                "gateway_record": row,
                "bank_records": bank_rows,
                "ledger_record": ledger_rows[0],
                "reason": "date_mismatch",
                "date_gap_days": max_date_gap,
            })
            continue

        matched.append({
            "gateway_record": row,
            "bank_records": bank_rows,
            "ledger_record": ledger_rows[0],
        })

    return {
        "matched": matched,
        "needs_review": needs_review,
        "summary": {
            "matched": len(matched),
            "needs_review": len(needs_review),
            "total": len(gateway),
        },
    }


if __name__ == "__main__":
    gateway = load_csv("../../../data/gateway_export.csv")
    bank = load_csv("../../../data/bank_statement.csv")
    ledger = load_csv("../../../data/internal_ledger.csv")

    result = deterministic_match(gateway, bank, ledger)
    print(result["summary"])