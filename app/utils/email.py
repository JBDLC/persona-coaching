from flask import current_app, render_template_string
from flask_mail import Message

from app.extensions import mail


def send_booking_confirmation(patient_email: str, patient_name: str, slot_str: str, coach_name: str):
    if not current_app.config.get("MAIL_SERVER"):
        return False
    body = render_template_string(
        """
Bonjour {{ name }},

Votre rendez-vous est confirmé :
{{ slot }}

Cordialement,
{{ coach }}
        """,
        name=patient_name,
        slot=slot_str,
        coach=coach_name,
    )
    msg = Message(
        subject="Confirmation de rendez-vous",
        recipients=[patient_email],
        body=body.strip(),
    )
    try:
        mail.send(msg)
        return True
    except Exception:
        current_app.logger.exception("Envoi email échoué")
        return False


def send_coach_new_booking(coach_email: str, patient_name: str, slot_str: str):
    if not current_app.config.get("MAIL_SERVER"):
        return False
    msg = Message(
        subject=f"Nouvelle réservation — {patient_name}",
        recipients=[coach_email],
        body=f"{patient_name} a réservé : {slot_str}",
    )
    try:
        mail.send(msg)
        return True
    except Exception:
        current_app.logger.exception("Envoi email coach échoué")
        return False
