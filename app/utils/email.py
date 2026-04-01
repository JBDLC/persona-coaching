import mimetypes
import smtplib
from email.message import EmailMessage
from datetime import datetime, time, timedelta, timezone

from flask import current_app, render_template_string
import pytz

from app.utils.crypto import decrypt_text
from app.utils.platform_settings import get_platform_setting


def _smtp_config_from_coach_settings(coach_settings):
    if not coach_settings or not coach_settings.smtp_server:
        return None
    return {
        "server": coach_settings.smtp_server,
        "port": coach_settings.smtp_port or 587,
        "use_tls": bool(coach_settings.smtp_use_tls),
        "username": coach_settings.smtp_username,
        "password": decrypt_text(coach_settings.smtp_password),
        "default_sender": coach_settings.smtp_default_sender,
    }


def _smtp_config_from_app():
    server = get_platform_setting("mail_server") or current_app.config.get("MAIL_SERVER")
    if not server:
        return None
    port_val = get_platform_setting("mail_port")
    use_tls_val = get_platform_setting("mail_use_tls")
    username = get_platform_setting("mail_username") or current_app.config.get("MAIL_USERNAME")
    password = get_platform_setting("mail_password", decrypt=True) or current_app.config.get("MAIL_PASSWORD")
    default_sender = get_platform_setting("mail_default_sender") or current_app.config.get("MAIL_DEFAULT_SENDER")
    if use_tls_val is None:
        use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    else:
        use_tls = str(use_tls_val).lower() in ("1", "true", "yes")
    return {
        "server": server,
        "port": int(port_val or current_app.config.get("MAIL_PORT") or 587),
        "use_tls": use_tls,
        "username": username,
        "password": password,
        "default_sender": default_sender,
    }


def _send_email(subject: str, recipients: list[str], body: str, smtp_config: dict, attachments: list[dict] | None = None) -> bool:
    sender = smtp_config.get("default_sender") or smtp_config.get("username")
    if not sender:
        current_app.logger.warning("Envoi email ignoré: expéditeur SMTP manquant.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    for attachment in attachments or []:
        filename = attachment["filename"]
        content = attachment["content"]
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    try:
        with smtplib.SMTP(smtp_config["server"], int(smtp_config["port"]), timeout=20) as smtp:
            smtp.ehlo()
            if smtp_config.get("use_tls"):
                smtp.starttls()
                smtp.ehlo()
            if smtp_config.get("username") and smtp_config.get("password"):
                smtp.login(smtp_config["username"], smtp_config["password"])
            smtp.send_message(msg)
        return True
    except Exception:
        current_app.logger.exception("Envoi email échoué")
        return False


def send_booking_confirmation(patient_email: str, patient_name: str, slot_str: str, coach_name: str, coach_settings=None):
    smtp_config = _smtp_config_from_coach_settings(coach_settings) or _smtp_config_from_app()
    if not smtp_config:
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
    ).strip()
    return _send_email("Confirmation de rendez-vous", [patient_email], body, smtp_config)


def send_coach_new_booking(coach_email: str, patient_name: str, slot_str: str, coach_settings=None):
    smtp_config = _smtp_config_from_coach_settings(coach_settings) or _smtp_config_from_app()
    if not smtp_config:
        return False
    return _send_email(
        f"Nouvelle reservation - {patient_name}",
        [coach_email],
        f"{patient_name} a reserve : {slot_str}",
        smtp_config,
    )


def send_patient_day_before_reminder(patient_email: str, patient_name: str, slot_str: str, coach_name: str, coach_settings=None):
    smtp_config = _smtp_config_from_coach_settings(coach_settings) or _smtp_config_from_app()
    if not smtp_config:
        return False
    body = render_template_string(
        """
Bonjour {{ name }},

Rappel: vous avez rendez-vous demain.
Horaire: {{ slot }}

A bientot,
{{ coach }}
        """,
        name=patient_name,
        slot=slot_str,
        coach=coach_name,
    ).strip()
    return _send_email("Rappel de rendez-vous (demain)", [patient_email], body, smtp_config)


def send_session_report_email(patient_email: str, patient_name: str, slot_str: str, coach_name: str, notes: str, coach_settings=None):
    smtp_config = _smtp_config_from_coach_settings(coach_settings) or _smtp_config_from_app()
    if not smtp_config:
        return False
    body = render_template_string(
        """
Bonjour {{ name }},

Voici le compte rendu de votre seance du {{ slot }}.

Compte rendu:
{{ notes }}

Cordialement,
{{ coach }}
        """,
        name=patient_name,
        slot=slot_str,
        notes=notes,
        coach=coach_name,
    ).strip()
    return _send_email("Compte rendu de seance", [patient_email], body, smtp_config)


def send_session_invoice_email(
    patient_email: str,
    patient_name: str,
    slot_str: str,
    coach_name: str,
    invoice_filename: str,
    invoice_content: bytes,
    coach_settings=None,
):
    smtp_config = _smtp_config_from_coach_settings(coach_settings) or _smtp_config_from_app()
    if not smtp_config:
        return False
    body = render_template_string(
        """
Bonjour {{ name }},

Veuillez trouver votre facture en piece jointe pour la seance du {{ slot }}.

Cordialement,
{{ coach }}
        """,
        name=patient_name,
        slot=slot_str,
        coach=coach_name,
    ).strip()
    return _send_email(
        "Facture de seance",
        [patient_email],
        body,
        smtp_config,
        attachments=[{"filename": invoice_filename, "content": invoice_content}],
    )


def get_day_before_utc_window(tz_name: str):
    tz = pytz.timezone(tz_name or "Europe/Paris")
    now_local = datetime.now(tz)
    tomorrow = now_local.date() + timedelta(days=1)
    start_local = tz.localize(datetime.combine(tomorrow, time.min))
    end_local = tz.localize(datetime.combine(tomorrow + timedelta(days=1), time.min))
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )
