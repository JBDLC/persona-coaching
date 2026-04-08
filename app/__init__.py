from pathlib import Path
from datetime import datetime, timedelta, timezone

from flask import Flask, flash, redirect, request, url_for
from flask_login import current_user, logout_user

from config import Config
from app.extensions import csrf, db, limiter, login_manager, mail


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    upload = Path(app.config["UPLOAD_FOLDER"])
    upload.mkdir(parents=True, exist_ok=True)
    (upload / "contracts").mkdir(exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.models import AuditLog, GdprRequest, SecurityIncident, Slot, User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth import bp as auth_bp
    from app.admin import bp as admin_bp
    from app.coach import bp as coach_bp
    from app.main import bp as main_bp
    from app.patient import bp as patient_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(coach_bp, url_prefix="/coach")
    app.register_blueprint(patient_bp, url_prefix="/patient")

    @app.cli.command("init-db")
    def init_db():
        """Crée les tables (SQLite)."""
        db.create_all()
        print("Base initialisée.")

    @app.cli.command("send-reminders")
    def send_reminders():
        """Envoie les rappels J-1 pour tous les coachs."""
        sent_count = _run_auto_day_before_reminders()
        print(f"Rappels envoyés: {sent_count}")

    @app.cli.command("purge-data")
    def purge_data():
        """Purge RGPD des données expirées (hors legal hold)."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        audit_cutoff = now - timedelta(days=app.config.get("GDPR_AUDIT_RETENTION_DAYS", 730))
        sec_cutoff = now - timedelta(days=app.config.get("GDPR_SECURITY_INCIDENT_RETENTION_DAYS", 1825))
        inactive_cutoff = now - timedelta(days=app.config.get("GDPR_INACTIVE_USER_RETENTION_DAYS", 1095))

        protected_user_ids = {u.id for u in User.query.filter_by(legal_hold=True).all()}
        purge_counts = {"audit_logs": 0, "security_incidents": 0, "inactive_users": 0}

        audit_rows = AuditLog.query.filter(AuditLog.created_at < audit_cutoff).all()
        for row in audit_rows:
            if row.coach_id in protected_user_ids:
                continue
            db.session.delete(row)
            purge_counts["audit_logs"] += 1

        sec_rows = SecurityIncident.query.filter(SecurityIncident.created_at < sec_cutoff).all()
        for row in sec_rows:
            if row.related_user_id in protected_user_ids:
                continue
            db.session.delete(row)
            purge_counts["security_incidents"] += 1

        for user in User.query.filter(User.created_at < inactive_cutoff, User.legal_hold.is_(False)).all():
            if user.role == "admin":
                continue
            # Soft anonymization for very old inactive records.
            user.name = f"Anonymise user{user.id}"
            user.email = f"anonymise-user{user.id}@example.invalid"
            user.is_suspended = True
            purge_counts["inactive_users"] += 1

        done_rows = GdprRequest.query.filter(
            GdprRequest.status.in_(("done", "rejected")),
            GdprRequest.handled_at.isnot(None),
            GdprRequest.handled_at < audit_cutoff,
        ).all()
        for row in done_rows:
            db.session.delete(row)
        db.session.commit()
        print(f"Purge done: {purge_counts}")

    from app.utils.datetime_parse import utc_naive_to_local_str

    @app.template_filter("local_dt")
    def local_dt_filter(dt, tz_name="Europe/Paris"):
        return utc_naive_to_local_str(dt, tz_name)

    def _coach_smtp_ready(settings) -> bool:
        if not settings or not settings.smtp_server:
            return False
        if settings.smtp_username and not settings.smtp_password:
            return False
        return bool(settings.smtp_default_sender or settings.smtp_username)

    def _run_auto_day_before_reminders() -> int:
        from app.utils.email import get_day_before_utc_window, send_patient_day_before_reminder

        sent_count = 0
        coaches = User.query.filter_by(role="coach").all()
        for coach in coaches:
            s = coach.settings
            if not s or not s.email_notifications or not s.notify_reminder_day_before:
                continue
            if not _coach_smtp_ready(s):
                continue
            start_utc, end_utc = get_day_before_utc_window(s.timezone)
            rows = (
                Slot.query.filter(
                    Slot.coach_id == coach.id,
                    Slot.status == "booked",
                    Slot.start_utc >= start_utc,
                    Slot.start_utc < end_utc,
                    Slot.reminder_sent_at.is_(None),
                )
                .all()
            )
            for slot in rows:
                if not slot.patient or not slot.patient.user:
                    continue
                ok = send_patient_day_before_reminder(
                    slot.patient.user.email,
                    slot.patient.display_name(),
                    local_dt_filter(slot.start_utc, s.timezone),
                    coach.name,
                    coach_settings=s,
                )
                if ok:
                    slot.reminder_sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    sent_count += 1
        if sent_count:
            db.session.commit()
        return sent_count

    @app.context_processor
    def coach_tz():
        def _terms_for_kind(kind: str):
            if kind == "psychologue":
                return {
                    "professional_singular": "psychologue",
                    "professional_singular_title": "Psychologue",
                    "professional_plural": "psychologues",
                    "professional_plural_title": "Psychologues",
                    "followed_singular": "patient",
                    "followed_singular_title": "Patient",
                    "followed_plural": "patients",
                    "followed_plural_title": "Patients",
                }
            return {
                "professional_singular": "coach",
                "professional_singular_title": "Coach",
                "professional_plural": "coachs",
                "professional_plural_title": "Coachs",
                "followed_singular": "client",
                "followed_singular_title": "Client",
                "followed_plural": "clients",
                "followed_plural_title": "Clients",
            }

        tz = "Europe/Paris"
        terms = _terms_for_kind("coach")
        if current_user.is_authenticated:
            if current_user.is_coach() and current_user.settings:
                tz = current_user.settings.timezone or tz
                terms = _terms_for_kind(current_user.professional_kind())
            elif current_user.is_patient() and current_user.coach_id:
                c = db.session.get(User, current_user.coach_id)
                if c and c.settings:
                    tz = c.settings.timezone or tz
                    terms = _terms_for_kind(c.professional_kind())
        return {"coach_tz": tz, "terms": terms}

    @app.before_request
    def force_logout_if_suspended():
        if current_user.is_authenticated and not current_user.is_active:
            if request.endpoint not in ("auth.login", "auth.logout"):
                logout_user()
                flash("Votre compte est suspendu.", "warning")
                return redirect(url_for("auth.login"))

    @app.before_request
    def auto_send_day_before_reminders():
        # Limite la charge: exécute au plus une fois toutes les 10 minutes par process.
        now_utc = datetime.now(timezone.utc)
        last_run = app.config.get("_LAST_AUTO_REMINDER_RUN_UTC")
        if last_run and (now_utc - last_run).total_seconds() < 600:
            return None
        app.config["_LAST_AUTO_REMINDER_RUN_UTC"] = now_utc
        try:
            _run_auto_day_before_reminders()
        except Exception:
            app.logger.exception("Échec envoi automatique rappels J-1")
        return None

    return app
