"""
playbook_gen.py — Generates synthetic payment recovery policy documents.

Each document chunk is ~100-200 words covering a specific scenario.
These are the RAG knowledge base that the LLM retriever will query at diagnosis time.

Usage:
  python playbook_gen.py [--outdir .]
"""

import os
import argparse

POLICY_CHUNKS = {
    "gateway_timeout.txt": """\
POLICY: Gateway Timeout Failures

When a payment fails with a gateway_timeout error code, this indicates a transient
infrastructure issue rather than a customer problem. The card was never charged.

Recommended intervention:
1. Attempt one immediate retry (within 5 minutes of original failure). Do not notify
   the customer for this first retry — it is invisible to them.
2. If the immediate retry also fails with a timeout, wait 30 minutes and retry once more.
3. If the second retry fails for any reason (including a different error code), send
   a brief SMS/email to the customer: "We had a technical hiccup processing your
   payment. Please try again or contact support."
4. Do NOT retry more than 3 times total for gateway timeout failures.
5. Do NOT classify gateway_timeout as a hard decline — it is always soft.

Priority: HIGH (no customer action needed for first retry; fast recovery path).
Segment note: No segment-specific variation. Apply uniformly across retail, SMB, enterprise.
""",

    "card_expired.txt": """\
POLICY: Expired Card Failures

When a payment fails with card_expired, the customer must update their card details.
Automated retries will always fail — do not retry without new card information.

Recommended intervention:
1. Send a card update link immediately (within 1 hour of failure).
   - Retail/SMB: email + SMS with secure card update link.
   - Enterprise: email only; include account manager CC if invoice > INR 50,000.
2. Wait 72 hours. If card not updated, send one reminder (email).
3. Wait another 72 hours. If still no update, escalate to human for manual follow-up.
4. Hard stop: If the customer has not updated their card within 14 days,
   mark as "pending customer action" and stop automated outreach.

Do NOT retry the original payment — it will fail until the card is updated.
Do NOT send more than 3 automated contacts total.
""",

    "insufficient_funds.txt": """\
POLICY: Insufficient Funds Failures

Insufficient_funds indicates the customer's account lacked balance at time of charge.
This is a soft decline — the customer's card is valid but temporarily unfunded.

Recommended intervention:
1. Wait 3 days before first retry (most customers receive salary/transfers within 1-3 days).
2. If first retry fails: wait another 4 days, then retry once more.
3. If second retry fails:
   - Retail customers: Send friendly reminder email. Offer payment plan if amount > INR 5,000.
   - SMB customers: Offer payment plan or EMI split automatically.
   - Enterprise customers: Escalate to account manager within 24h.
4. Maximum 3 automated retries. After third failure, offer payment plan or escalate.
5. Never retry more frequently than once every 3 days — aggressive retrying
   increases churn risk significantly.

Note: Customers with 3+ consecutive insufficient_funds failures on different
transactions are high churn risk. Escalate these to human review.
""",

    "soft_decline_retryable.txt": """\
POLICY: Soft Decline — Retryable Cases (do_not_honor)

A do_not_honor response is ambiguous — it can indicate a temporary bank-side
restriction, a fraud hold, or a customer-initiated block. Context matters.

Signals that suggest RETRYABLE:
- First-time failure for this customer (no prior do_not_honor history)
- Amount is consistent with customer's historical transaction range
- No prior dispute history
- Payment method: card (not UPI — UPI do_not_honor is almost always hard)

Recommended intervention for retryable cases:
1. Wait 24 hours, then retry once.
2. If retry succeeds: close. If fails: send a polite notification to customer
   ("Your payment could not be processed. Please contact your bank or try a
   different payment method.")
3. Do not retry more than once for do_not_honor without customer action.

Segment note: Enterprise customers — escalate to human for any do_not_honor
regardless of retry eligibility, given the relationship risk.
""",

    "soft_decline_churn_risk.txt": """\
POLICY: Soft Decline — Probable Churn or Dispute Risk

Some do_not_honor failures indicate the customer has proactively blocked the
merchant or is in the process of filing a dispute. Aggressive outreach in these
cases worsens outcomes.

Signals that suggest CHURN or DISPUTE risk:
- Customer has 2+ prior do_not_honor failures in last 30 days
- Customer contacted support in last 7 days about a billing issue
- Payment amount is much higher than customer's historical average (potential
  friendly fraud)
- Customer has recently requested a refund or filed a complaint

Recommended intervention:
1. Do NOT retry automatically.
2. Escalate to human review team within 4 hours.
3. Human reviewer checks for open disputes before any outreach.
4. If dispute confirmed: halt all recovery efforts immediately and route to
   dispute management workflow.
5. If no dispute: human makes one outreach attempt (phone call preferred).

Never send automated dunning emails for probable_churn cases — it can
be used against the merchant in a chargeback.
""",

    "card_lost_stolen.txt": """\
POLICY: Lost or Stolen Card Failures

card_lost_stolen is a hard decline. The customer's card has been reported
to the bank as lost or stolen. Automated recovery is not possible.

Recommended intervention:
1. Do NOT retry — the card is permanently blocked by the issuing bank.
2. Do NOT send a standard payment failure notification.
3. Escalate to human team immediately.
4. Human agent contacts the customer (phone preferred) to:
   a. Verify the customer is aware their card was blocked.
   b. Offer to complete the transaction via a different payment method.
   c. Confirm no fraud occurred on their account.
5. If the customer cannot be reached within 48h, send a secure email asking
   them to contact us to complete their purchase.

Security note: Never mention "lost or stolen" in automated communication —
this may alarm the customer unnecessarily if the block was a bank error.
""",

    "invalid_cvv.txt": """\
POLICY: Invalid CVV Failures

An invalid_cvv failure means the customer entered an incorrect card security code.
The card itself is valid — this is a data entry error, not a bank block.

Recommended intervention:
1. Send an immediate, friendly notification (email + SMS):
   "Your payment didn't go through — the security code entered didn't match.
    Please try again with the correct CVV from the back of your card."
   Include a direct link to retry the payment.
2. Wait 24 hours. If no retry attempted: send one reminder.
3. If still no retry after 48 hours: close the recovery attempt.
   (Customer has chosen not to complete the purchase.)
4. Do NOT retry server-side — CVV validation requires customer input.

Note: Multiple invalid_cvv failures from the same card in a short window
may indicate card testing fraud. Flag for fraud team review if 3+ failures
occur within 10 minutes.
""",

    "high_intent_abandonment.txt": """\
POLICY: High-Intent Cart Abandonment (review/confirm step)

Customers who abandon at the review or confirm step have completed all
data entry — they have high intent and encountered a last-minute hesitation.
Recovery rates for this segment are typically 25-40%.

Recommended intervention:
1. Send a recovery email within 1 hour of abandonment. Include:
   - Exact cart contents (item names, quantities, total)
   - Direct "Complete your purchase" link (pre-filled cart)
   - Social proof if available ("Join 10,000+ customers who ordered this week")
2. If no conversion in 24 hours: send one more email with a time-limited offer
   (5% discount or free shipping if margin allows).
3. If no conversion in 48 hours: close. Do not send more than 2 recovery emails.

Segment note:
- Enterprise / B2B carts > INR 25,000: Skip discount, assign to sales rep instead.
- Retail carts < INR 500: Close after first email — recovery cost exceeds margin.
""",

    "medium_intent_abandonment.txt": """\
POLICY: Medium-Intent Cart Abandonment (payment_info step)

Customers who abandon at the payment_info step have expressed purchase intent
but did not complete card/payment details. Reasons vary: price sensitivity,
payment method not available, distraction.

Recommended intervention:
1. Send one recovery email within 2 hours: "You left something behind."
   Include cart summary and a "Return to checkout" link.
2. Do NOT offer a discount automatically (it trains customers to abandon for discounts).
3. If cart value > INR 10,000: add a note about EMI/pay-later options available.
4. Send at most 1 recovery email. Close after 48 hours if no conversion.

Do NOT escalate or call for medium-intent abandonment — the cost/benefit
does not justify it.
""",

    "overdue_mild.txt": """\
POLICY: Mildly Overdue Invoices (1-7 days past due)

Invoices 1-7 days past due often represent oversight rather than inability to pay.
Most customers in this bucket respond to a single polite reminder.

Recommended intervention:
1. Send a friendly invoice reminder email on day 1 or 2:
   "Just a reminder — Invoice #XXX for INR YYY was due on [date]."
   Include the invoice PDF and a payment link.
2. If unpaid after 5 days: send one follow-up (email or SMS, not both).
3. Do not call or escalate for invoices < 7 days overdue unless enterprise
   customer with a specific SLA arrangement.

Tone: Friendly, not threatening. No late fee mention until day 8.
""",

    "overdue_moderate.txt": """\
POLICY: Moderately Overdue Invoices (8-30 days past due)

Invoices 8-30 days overdue indicate the customer may be experiencing cash flow
issues or is deprioritising payment. Intervention escalates slightly.

Recommended intervention:
1. Day 8: Send invoice reminder with payment link. Mention that late fees
   may apply per contract terms.
2. Day 15: Follow up. Offer a payment plan (2-3 installments) if the invoice
   is > INR 10,000.
3. Day 25: Final reminder before escalation. Clearly state that the account
   will be escalated if not resolved by day 30.
4. Day 30: If unpaid, escalate to account manager / collections team.

Contact limit: Maximum 1 contact per 7 days for this bucket.
Segment note: Enterprise accounts — escalate to account manager at day 15, not day 30.
""",

    "overdue_severe.txt": """\
POLICY: Severely Overdue Invoices (31-90 days past due)

Invoices 31-90 days past due require assertive but still relationship-preserving
intervention. Automated dunning is no longer sufficient.

Recommended intervention:
1. Immediately offer a structured payment plan (3-6 installments).
2. Assign to a human collections representative within 48 hours.
3. Human representative makes one phone call attempt.
4. If payment plan accepted: halt further automated outreach, monitor installments.
5. If no response after 14 days of human outreach: send a formal "Notice of
   Overdue Account" letter (email + physical if enterprise).
6. Day 90: If still unpaid with no payment plan in place, initiate write-off review.

Do not threaten legal action in automated communications — this must come
from the human collections team after internal approval.
""",

    "likely_uncollectable.txt": """\
POLICY: Likely Uncollectable Invoices (>90 days past due)

Invoices more than 90 days overdue with multiple failed contact attempts have
a low probability of recovery without significant intervention.

Before marking uncollectable, the following review is REQUIRED:
1. Check if the customer has any active relationship with the business
   (open orders, active subscriptions, recent support tickets).
2. Check the total outstanding balance — if > INR 100,000, escalate to senior
   management and legal before writing off.
3. If the customer has responded to any contact in the last 30 days, make one
   more structured offer: settlement at 70-80% of invoice value.
4. If all above fail: mark as uncollectable, write off the amount in the
   accounting system, and send a formal final notice to the customer.

Recovery after write-off: If customer pays after write-off, treat as a payment
reversal — do NOT re-open the invoice; create a new credit entry.
""",

    "compliance_contact_limits.txt": """\
POLICY: Contact Frequency and Compliance Rules

These rules apply to ALL recovery interventions regardless of failure type.
Violation of these rules creates legal and reputational risk.

Hard rules (non-negotiable):
1. Do-Not-Contact (DNC) flag: If a customer has set a DNC flag, NO automated
   or manual outreach is permitted. The only exception is sending a legally
   required final notice (must be approved by legal team).
2. Maximum 3 automated contacts per customer per week across all channels.
3. No contact between 9:00 PM and 8:00 AM local customer time.
4. No contact on national public holidays (India: Republic Day, Independence Day,
   Gandhi Jayanti, all gazetted holidays).
5. Customers who have filed a dispute or chargeback: HALT all recovery outreach
   immediately. Route to dispute management only.
6. Maximum outreach period: 14 days of automated outreach per recovery event.
   After 14 days, escalate to human or close.

All contacts must be logged in the audit trail with timestamp, channel, and outcome.
""",

    "retry_payment_rules.txt": """\
POLICY: Payment Retry Rules and Limits

Retrying failed payments without guardrails increases decline rates and can
trigger issuer-side blocks on the merchant ID.

Hard limits on retries:
1. Maximum 3 retry attempts per original payment failure.
2. Minimum 24-hour gap between retries (except gateway_timeout: immediate retry allowed once).
3. Never retry a hard decline: card_lost_stolen, do_not_honor on UPI, fraudulent_transaction.
4. Never retry after a customer has initiated a refund or dispute.
5. If a retry fails with a DIFFERENT error code than the original, stop and diagnose
   the new code before retrying again — the situation may have changed.

Retry windows by failure type:
- gateway_timeout: immediate, then 30 minutes, then stop.
- card_expired: no retry until card updated.
- insufficient_funds: day 3, day 7, day 14.
- do_not_honor (retryable): day 1 only.
- invalid_cvv: no server-side retry.

Logging: Every retry attempt must be logged with: original_payment_id, retry_number,
attempt_timestamp, outcome, new_failure_code (if applicable).
""",

    "enterprise_customer_policy.txt": """\
POLICY: Enterprise Customer Recovery — Special Handling

Enterprise customers (typically B2B, invoice amounts > INR 50,000, or flagged as
enterprise segment) require relationship-first recovery, not automated dunning.

Key differences from retail/SMB:
1. No automated SMS for enterprise customers — email only, or phone via account manager.
2. Any payment failure > INR 50,000 must trigger an account manager notification
   within 4 hours, even if automated retry is also in progress.
3. Do not offer generic payment plans — negotiate custom terms via account manager.
4. Dispute handling: Assign a dedicated point-of-contact from the enterprise support team.
5. Dunning emails for enterprise accounts must be reviewed and approved by the account
   manager before sending — do not use standard retail templates.
6. Recovery timeline for enterprise: up to 30 days before escalating to collections,
   versus 14 days for retail/SMB.

Priority: Enterprise accounts represent high LTV — err on the side of human
relationship management over aggressive automated recovery.
""",

    "payment_plan_policy.txt": """\
POLICY: Payment Plan / EMI Offer Guidelines

Offering a payment plan can recover revenue that would otherwise be lost, but
offering it too early trains customers to request it as a default.

When to offer:
- insufficient_funds on invoices > INR 5,000: After 2 failed retries.
- moderately/severely overdue invoices > INR 10,000: As a standard option.
- SMB customers with cash flow signals: Proactively on day 7 of overdue.
- Never offer a payment plan on the first contact (except severely overdue enterprise).

Standard plans:
- Retail: 2-3 installments over 30-60 days, 0% interest.
- SMB: 3-6 installments over 60-90 days, 0% interest up to INR 50,000.
- Enterprise: Negotiated by account manager, custom terms.

Process:
1. Customer clicks "Payment Plan" link in dunning email → enters agreement flow.
2. System creates installment schedule and sends confirmation.
3. Installments are auto-charged on scheduled dates with standard retry rules.
4. If an installment fails: send immediate notification and pause the plan;
   do not auto-retry the installment.
""",
}


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic payment recovery policy documents")
    parser.add_argument("--outdir", type=str, default=".", help="Output directory for .txt policy files")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    for filename, content in POLICY_CHUNKS.items():
        path = os.path.join(args.outdir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")

    print(f"Generated {len(POLICY_CHUNKS)} policy document chunks in '{args.outdir}/':")
    for fname in sorted(POLICY_CHUNKS.keys()):
        print(f"  {fname}")


if __name__ == "__main__":
    main()
