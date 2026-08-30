import argparse
import csv
import json
import random
import uuid
from datetime import datetime, timedelta

CURRENCIES = ["INR"]
FEE_RATE = 0.02  # 2% gateway fee, roughly matches typical payment gateway pricing


def money(x):
    return round(x, 2)


def make_base_records(n, rng, start_date):
    """Generate n 'true' underlying transactions before we scatter them
    across three messy, imperfectly-aligned source files."""
    records = []
    for i in range(n):
        txn_id = f"pay_{uuid.uuid4().hex[:10]}"
        amount = money(rng.uniform(500, 85000))
        date = start_date + timedelta(days=rng.randint(0, 27))
        records.append({
            "txn_id": txn_id,
            "amount": amount,
            "date": date,
            "narration": f"Order #{rng.randint(10000, 99999)} - {rng.choice(['Retail','Subscription','B2B Invoice','Marketplace'])}",
        })
    return records


def assign_cases(n, rng):
    """Allocate case types by guaranteed proportion rather than independent
    random rolls, so rare categories (duplicate, unresolvable) always show
    up in the data instead of vanishing by chance on a small n."""
    weights = {
        "clean_match": 0.60,
        "fee_mismatch": 0.10,
        "partial_split": 0.10,
        "timing_lag": 0.10,
        "duplicate": 0.05,
        "unresolvable": 0.05,
    }
    counts = {case: max(1, round(n * w)) for case, w in weights.items()}
    diff = n - sum(counts.values())
    counts["clean_match"] += diff
    cases = []
    for case, c in counts.items():
        cases.extend([case] * c)
    rng.shuffle(cases)
    return cases


def build_sources(base_records, rng):
    gateway_rows = []
    bank_rows = []
    ledger_rows = []
    ground_truth = []

    case_assignments = assign_cases(len(base_records), rng)

    for rec, case in zip(base_records, case_assignments):

        gw_id = f"gw_{rec['txn_id']}"
        bk_id = f"bk_{rec['txn_id']}"
        lg_id = f"lg_{rec['txn_id']}"

        if case == "clean_match":
            gateway_rows.append({"record_id": gw_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                  "date": rec["date"].isoformat(), "narration": rec["narration"]})
            bank_rows.append({"record_id": bk_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                               "date": rec["date"].isoformat(), "narration": rec["narration"]})
            ledger_rows.append({"record_id": lg_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                 "date": rec["date"].isoformat(), "narration": rec["narration"]})
            ground_truth.append({"case": case, "match_group": [gw_id, bk_id, lg_id], "resolvable": True})

        elif case == "fee_mismatch":
            net_amount = money(rec["amount"] * (1 - FEE_RATE))
            gateway_rows.append({"record_id": gw_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                  "date": rec["date"].isoformat(), "narration": rec["narration"]})
            bank_rows.append({"record_id": bk_id, "txn_ref": rec["txn_id"], "amount": net_amount,
                               "date": rec["date"].isoformat(), "narration": f"NEFT settlement {rec['txn_id'][-6:]}"})
            ledger_rows.append({"record_id": lg_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                 "date": rec["date"].isoformat(), "narration": rec["narration"]})
            ground_truth.append({"case": case, "match_group": [gw_id, bk_id, lg_id], "resolvable": True,
                                  "note": "bank amount is net of gateway fee"})

        elif case == "partial_split":
            part1 = money(rec["amount"] * 0.6)
            part2 = money(rec["amount"] - part1)
            gateway_rows.append({"record_id": gw_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                  "date": rec["date"].isoformat(), "narration": rec["narration"]})
            bk_id2 = bk_id + "_b"
            bank_rows.append({"record_id": bk_id, "txn_ref": rec["txn_id"], "amount": part1,
                               "date": rec["date"].isoformat(), "narration": "Partial settlement 1/2"})
            bank_rows.append({"record_id": bk_id2, "txn_ref": rec["txn_id"], "amount": part2,
                               "date": (rec["date"] + timedelta(days=1)).isoformat(), "narration": "Partial settlement 2/2"})
            ledger_rows.append({"record_id": lg_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                 "date": rec["date"].isoformat(), "narration": rec["narration"]})
            ground_truth.append({"case": case, "match_group": [gw_id, bk_id, bk_id2, lg_id], "resolvable": True,
                                  "note": "bank settled as two partial payments"})

        elif case == "timing_lag":
            lag = timedelta(days=rng.randint(2, 5))
            gateway_rows.append({"record_id": gw_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                  "date": rec["date"].isoformat(), "narration": rec["narration"]})
            bank_rows.append({"record_id": bk_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                               "date": (rec["date"] + lag).isoformat(), "narration": rec["narration"]})
            ledger_rows.append({"record_id": lg_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                 "date": rec["date"].isoformat(), "narration": rec["narration"]})
            ground_truth.append({"case": case, "match_group": [gw_id, bk_id, lg_id], "resolvable": True,
                                  "note": f"bank settlement lagged by {lag.days} days"})

        elif case == "duplicate":
            gateway_rows.append({"record_id": gw_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                  "date": rec["date"].isoformat(), "narration": rec["narration"]})
            bank_rows.append({"record_id": bk_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                               "date": rec["date"].isoformat(), "narration": rec["narration"]})
            bk_id_dup = bk_id + "_dup"
            bank_rows.append({"record_id": bk_id_dup, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                               "date": rec["date"].isoformat(), "narration": rec["narration"] + " (dup)"})
            ledger_rows.append({"record_id": lg_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                 "date": rec["date"].isoformat(), "narration": rec["narration"]})
            ground_truth.append({"case": case, "match_group": [gw_id, bk_id, lg_id], "resolvable": True,
                                  "note": f"{bk_id_dup} is a duplicate bank entry, should NOT be matched"})

        else:  # unresolvable
            gateway_rows.append({"record_id": gw_id, "txn_ref": rec["txn_id"], "amount": rec["amount"],
                                  "date": rec["date"].isoformat(), "narration": rec["narration"]})
            ground_truth.append({"case": case, "match_group": [gw_id], "resolvable": False,
                                  "note": "no counterpart in bank or ledger, genuine exception"})

    return gateway_rows, bank_rows, ledger_rows, ground_truth


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=60)
    parser.add_argument("--outdir", type=str, default=".")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    start_date = datetime(2026, 8, 1)

    base_records = make_base_records(args.n, rng, start_date)
    gateway_rows, bank_rows, ledger_rows, ground_truth = build_sources(base_records, rng)

    rng.shuffle(gateway_rows)
    rng.shuffle(bank_rows)
    rng.shuffle(ledger_rows)

    fieldnames = ["record_id", "txn_ref", "amount", "date", "narration"]
    write_csv(f"{args.outdir}/gateway_export.csv", gateway_rows, fieldnames)
    write_csv(f"{args.outdir}/bank_statement.csv", bank_rows, fieldnames)
    write_csv(f"{args.outdir}/internal_ledger.csv", ledger_rows, fieldnames)

    with open(f"{args.outdir}/ground_truth.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    case_counts = {}
    for g in ground_truth:
        case_counts[g["case"]] = case_counts.get(g["case"], 0) + 1

    print(f"Generated {args.n} base records:")
    print(f"  gateway_export.csv  -> {len(gateway_rows)} rows")
    print(f"  bank_statement.csv  -> {len(bank_rows)} rows")
    print(f"  internal_ledger.csv -> {len(ledger_rows)} rows")
    print(f"Case distribution: {case_counts}")
    print("ground_truth.json written -- do NOT read this from the matching engine.")


if __name__ == "__main__":
    main()