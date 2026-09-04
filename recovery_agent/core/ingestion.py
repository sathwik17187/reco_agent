"""
ingestion.py — Layer 1: Load, validate, and normalize all event source files.

Reads the three CSV event sources and returns a unified list of Event dicts,
each tagged with its event_type and fully normalized fields. Pure code, no LLM.

Normalizations applied:
  - timestamps  → ISO string (stored) + datetime object (for date arithmetic)
  - amounts     → float, rounded to 2dp, stripped of currency symbols/commas
  - string cols → .strip().lower() except emails/IDs which preserve case
  - booleans    → "true"/"false"/"1"/"0"/"yes"/"no" → Python bool
  - days_overdue → int (invoices only), computed from due_date if missing

Schema validation:
  Raises IngestionError(<field>, <file>) if a required column is absent.
"""

import csv
import os
from datetime import datetime
from typing import List, Dict, Any


# ---------------------------------------------------------------------------
# Required columns per source file
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "failed_payment": [
        "payment_id", "customer_id", "customer_email", "customer_segment",
        "amount", "currency", "payment_method", "failure_code",
        "retry_count", "timestamp", "do_not_contact",
    ],
    "abandoned_checkout": [
        "session_id", "customer_id", "customer_email", "customer_segment",
        "cart_value", "items_count", "abandoned_at_step", "timestamp",
        "do_not_contact",
    ],
    "overdue_invoice": [
        "invoice_id", "customer_id", "customer_email", "customer_segment",
        "amount", "currency", "due_date", "days_overdue",
        "invoice_status", "contact_attempts", "timestamp", "do_not_contact",
    ],
}

# Canonical ID field per event type (used as record_id)
ID_FIELD = {
    "failed_payment":    "payment_id",
    "abandoned_checkout": "session_id",
    "overdue_invoice":   "invoice_id",
}

# Amount field per event type
AMOUNT_FIELD = {
    "failed_payment":    "amount",
    "abandoned_checkout": "cart_value",
    "overdue_invoice":   "amount",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IngestionError(Exception):
    """Raised when a required field is missing or a value cannot be parsed."""
    def __init__(self, field: str, source_file: str, detail: str = ""):
        msg = f"IngestionError in '{source_file}': field '{field}' {detail or 'is missing or invalid'}"
        super().__init__(msg)
        self.field = field
        self.source_file = source_file


# ---------------------------------------------------------------------------
# Field normalizers
# ---------------------------------------------------------------------------

def _parse_bool(value: str, field: str, source: str) -> bool:
    """Parses common boolean representations to Python bool."""
    v = str(value).strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no", ""):
        return False
    raise IngestionError(field, source, f"cannot parse as bool: '{value}'")


def _parse_amount(value: str, field: str, source: str) -> float:
    """Strips ₹, commas, spaces; returns float rounded to 2dp."""
    try:
        cleaned = str(value).strip().replace("₹", "").replace(",", "").replace(" ", "")
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        raise IngestionError(field, source, f"cannot parse as amount: '{value}'")


def _parse_int(value: str, field: str, source: str) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        raise IngestionError(field, source, f"cannot parse as int: '{value}'")


def _parse_timestamp(value: str, field: str, source: str) -> str:
    """
    Accepts ISO 8601, date-only (YYYY-MM-DD), and DD/MM/YYYY formats.
    Returns canonical ISO string (stored on the Event).
    """
    value = str(value).strip()
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m-%d-%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    raise IngestionError(field, source, f"cannot parse timestamp: '{value}'")


def _normalize_str(value: str) -> str:
    return str(value).strip().lower()


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def _validate_schema(fieldnames: List[str], event_type: str, source_file: str):
    required = REQUIRED_FIELDS[event_type]
    for col in required:
        if col not in fieldnames:
            raise IngestionError(col, source_file, "column is missing from CSV header")


# ---------------------------------------------------------------------------
# Row normalizers per event type
# ---------------------------------------------------------------------------

def _normalize_failed_payment(row: Dict, source: str) -> Dict[str, Any]:
    amount = _parse_amount(row["amount"], "amount", source)
    return {
        "record_id":        row["payment_id"].strip(),
        "event_type":       "failed_payment",
        "payment_id":       row["payment_id"].strip(),
        "customer_id":      row["customer_id"].strip(),
        "customer_email":   row["customer_email"].strip(),
        "customer_segment": _normalize_str(row["customer_segment"]),
        "amount":           amount,
        "currency":         _normalize_str(row.get("currency", "inr")),
        "payment_method":   _normalize_str(row["payment_method"]),
        "card_last4":       row.get("card_last4", "").strip(),
        "failure_code":     _normalize_str(row["failure_code"]),
        "retry_count":      _parse_int(row["retry_count"], "retry_count", source),
        "timestamp":        _parse_timestamp(row["timestamp"], "timestamp", source),
        "do_not_contact":   _parse_bool(row["do_not_contact"], "do_not_contact", source),
    }


def _normalize_abandoned_checkout(row: Dict, source: str) -> Dict[str, Any]:
    cart_value = _parse_amount(row["cart_value"], "cart_value", source)
    return {
        "record_id":          row["session_id"].strip(),
        "event_type":         "abandoned_checkout",
        "session_id":         row["session_id"].strip(),
        "customer_id":        row["customer_id"].strip(),
        "customer_email":     row["customer_email"].strip(),
        "customer_segment":   _normalize_str(row["customer_segment"]),
        "amount":             cart_value,   # unified field for scoring
        "cart_value":         cart_value,
        "items_count":        _parse_int(row["items_count"], "items_count", source),
        "abandoned_at_step":  _normalize_str(row["abandoned_at_step"]),
        "timestamp":          _parse_timestamp(row["timestamp"], "timestamp", source),
        "do_not_contact":     _parse_bool(row["do_not_contact"], "do_not_contact", source),
    }


def _normalize_overdue_invoice(row: Dict, source: str) -> Dict[str, Any]:
    amount = _parse_amount(row["amount"], "amount", source)
    days_overdue = _parse_int(row["days_overdue"], "days_overdue", source)
    return {
        "record_id":          row["invoice_id"].strip(),
        "event_type":         "overdue_invoice",
        "invoice_id":         row["invoice_id"].strip(),
        "customer_id":        row["customer_id"].strip(),
        "customer_email":     row["customer_email"].strip(),
        "customer_segment":   _normalize_str(row["customer_segment"]),
        "amount":             amount,
        "currency":           _normalize_str(row.get("currency", "inr")),
        "due_date":           row["due_date"].strip(),
        "days_overdue":       days_overdue,
        "invoice_status":     _normalize_str(row["invoice_status"]),
        "contact_attempts":   _parse_int(row["contact_attempts"], "contact_attempts", source),
        "timestamp":          _parse_timestamp(row["timestamp"], "timestamp", source),
        "do_not_contact":     _parse_bool(row["do_not_contact"], "do_not_contact", source),
    }


_NORMALIZERS = {
    "failed_payment":    _normalize_failed_payment,
    "abandoned_checkout": _normalize_abandoned_checkout,
    "overdue_invoice":   _normalize_overdue_invoice,
}

_FILE_MAP = {
    "failed_payments.csv":    "failed_payment",
    "abandoned_checkouts.csv": "abandoned_checkout",
    "overdue_invoices.csv":   "overdue_invoice",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_events(data_dir: str) -> List[Dict[str, Any]]:
    """
    Load and normalize all event source files from data_dir.

    Returns a list of normalized Event dicts, each with:
      - record_id     : unique ID
      - event_type    : 'failed_payment' | 'abandoned_checkout' | 'overdue_invoice'
      - amount        : float (unified amount field for scoring)
      - do_not_contact: bool
      - (plus all event-specific fields)

    Raises:
      FileNotFoundError if a required CSV is missing.
      IngestionError    if a required column is absent or a value cannot be parsed.
    """
    events: List[Dict[str, Any]] = []
    ingestion_errors = []

    for filename, event_type in _FILE_MAP.items():
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"Required source file not found: '{filepath}'. "
                f"Run data/data_gen.py --outdir {data_dir} first."
            )

        normalizer = _NORMALIZERS[event_type]
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            _validate_schema(list(reader.fieldnames or []), event_type, filename)

            for line_num, row in enumerate(reader, start=2):  # 1-indexed, row 1 = header
                try:
                    event = normalizer(row, filename)
                    events.append(event)
                except IngestionError as e:
                    ingestion_errors.append(f"  Line {line_num}: {e}")
                except Exception as e:
                    ingestion_errors.append(f"  Line {line_num} ({filename}): Unexpected error: {e}")

    if ingestion_errors:
        raise IngestionError(
            "multiple fields",
            "batch",
            f"\n{len(ingestion_errors)} row(s) failed to parse:\n" + "\n".join(ingestion_errors),
        )

    return events


def summarize(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a quick ingestion summary for logging."""
    by_type: Dict[str, int] = {}
    total_amount = 0.0
    dnc_count = 0
    for e in events:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
        total_amount += e.get("amount", 0.0)
        if e.get("do_not_contact"):
            dnc_count += 1
    return {
        "total_events":       len(events),
        "by_type":            by_type,
        "total_revenue_at_risk": round(total_amount, 2),
        "dnc_flagged":        dnc_count,
    }


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys, json
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    events = load_events(data_dir)
    summary = summarize(events)
    print(json.dumps(summary, indent=2))
    print(f"\nSample event (first record):")
    print(json.dumps(events[0], indent=2))
