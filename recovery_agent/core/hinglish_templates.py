"""
hinglish_templates.py — Multichannel outreach templates (Hinglish / Bilingual).

Provides formatted message payloads for:
  - SMS / WhatsApp Nudges
  - Voice IVR / AI Call Scripts (Twilio / ElevenLabs format)
  - Bilingual Email Reminders
  - Payment Plan Offers
"""

from typing import Dict, Any


def format_sms_hinglish(
    customer_name: str,
    amount: float,
    action_type: str,
    link: str = "https://pay.razorpay.com/rec/xyz",
) -> str:
    """Format SMS/WhatsApp nudge in Hinglish."""
    first_name = customer_name.split()[0] if customer_name else "Customer"
    amt_fmt    = f"₹{amount:,.2f}"

    if action_type == "send_card_update_link":
        return (
            f"Namaste {first_name}, aapka {amt_fmt} payment expire card ki wajah se fail ho gaya. "
            f"Card details update karke recovery complete karein: {link}"
        )
    elif action_type == "send_correction_link":
        return (
            f"Hi {first_name}, {amt_fmt} transaction mein issue aaya tha. "
            f"Kripya payment re-enter karein: {link}"
        )
    elif action_type == "send_abandon_reminder":
        return (
            f"Hi {first_name}, aapka checkout incomplete reha gaya ({amt_fmt}). "
            f"Abhi complete karein aur order confirm karein: {link}"
        )
    elif action_type == "send_discount_offer":
        return (
            f"Special offer for {first_name}! Complete your payment of {amt_fmt} "
            f"now and get 10% instant discount: {link}"
        )
    elif action_type == "offer_payment_plan":
        return (
            f"Namaste {first_name}, {amt_fmt} payment ko easy monthly installments mein pay karein. "
            f"Choose payment plan here: {link}"
        )
    else:
        return (
            f"Namaste {first_name}, aapka {amt_fmt} payment pending hai. "
            f"Kripya is link se complete karein: {link}"
        )


def format_voice_ivr_hinglish(
    customer_name: str,
    amount: float,
    reason: str = "subscription renewal",
) -> Dict[str, Any]:
    """Format Voice Call IVR payload (Hinglish/English mixed)."""
    first_name = customer_name.split()[0] if customer_name else "Customer"
    amt_fmt    = f"INR {amount:,.0f}"

    spoken_script = (
        f"Namaste {first_name}. Razorpay automatic recovery system se call kar rahe hain. "
        f"Aapka {reason} amount {amt_fmt} process nahi ho paya. "
        f"Payment retry karne ke liye 1 dabayein. Support executive se baat karne ke liye 2 dabayein."
    )

    return {
        "channel": "voice_bilingual",
        "recipient": customer_name,
        "language": "hi-IN-hinglish",
        "script": spoken_script,
        "dtmf_options": {
            "1": "trigger_retry_immediate",
            "2": "escalate_human_agent",
        },
    }


def format_email_hinglish(
    customer_name: str,
    amount: float,
    event_type: str,
    invoice_id: str = "INV-1001",
    link: str = "https://pay.razorpay.com/rec/xyz",
) -> Dict[str, str]:
    """Format bilingual Email outreach."""
    first_name = customer_name.split()[0] if customer_name else "Customer"
    amt_fmt    = f"₹{amount:,.2f}"

    subject = f"Action Required: Payment status update for {invoice_id} ({amt_fmt})"
    body = f"""Dear {first_name},

Aapka {amt_fmt} ka recent payment ({event_type}) process nahi ho paya.

Transaction Details:
- Invoice / Reference: {invoice_id}
- Amount: {amt_fmt}
- Status: Action Required

To resolve this issue immediately and prevent service disruption, please complete payment here:
{link}

Agar aapko kisi help ki zaroorat hai, feel free to reply to this email.

Best regards,
Revenue Recovery Team
"""
    return {"subject": subject, "body": body}
