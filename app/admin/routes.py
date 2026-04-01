from pathlib import Path
from datetime import datetime, timezone
import io
import json
import zipfile

from flask import current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app import db
from app.admin import bp
from app.forms import (
    CoachRegisterForm,
    GdprRequestForm,
    PlatformSmtpSettingsForm,
    PlatformStripeSettingsForm,
    ResetCoachPasswordForm,
    SecurityIncidentForm,
)
from app.models import (
    AuditLog,
    CoachSettings,
    ContractVersion,
    GdprRequest,
    Patient,
    PaymentTransaction,
    SecurityIncident,
    Slot,
    User,
    create_security_incident,
)
from app.utils.decorators import admin_required
from app.utils.platform_settings import get_platform_setting, set_platform_setting


@bp.route("/")
@login_required
@admin_required
def dashboard():
    create_form = CoachRegisterForm()
    reset_password_form = ResetCoachPasswordForm()
    now = datetime.now(timezone.utc)
    selected_year = request.args.get("year", type=int) or now.year
    selected_month = request.args.get("month", type=int) or now.month
    if selected_month < 1 or selected_month > 12:
        selected_month = now.month
    month_start = datetime(selected_year, selected_month, 1)
    if selected_month == 12:
        month_end = datetime(selected_year + 1, 1, 1)
    else:
        month_end = datetime(selected_year, selected_month + 1, 1)

    coaches = (
        db.session.query(
            User.id,
            User.name,
            User.is_suspended,
            func.count(Patient.id).label("patients_count"),
        )
        .outerjoin(Patient, Patient.coach_id == User.id)
        .filter(User.role == "coach")
        .group_by(User.id, User.name, User.is_suspended)
        .order_by(User.created_at.desc())
        .all()
    )
    coach_ids = [c.id for c in coaches]
    coach_users = User.query.filter(User.id.in_(coach_ids)).all() if coach_ids else []
    coach_by_id = {u.id: u for u in coach_users}
    monthly_revenue_by_coach: dict[int, float] = {cid: 0.0 for cid in coach_ids}
    if coach_ids:
        successful_tx = (
            PaymentTransaction.query.filter(
                PaymentTransaction.coach_id.in_(coach_ids),
                PaymentTransaction.status == "succeeded",
            )
            .order_by(PaymentTransaction.updated_at.desc(), PaymentTransaction.id.desc())
            .all()
        )
        tx_by_slot: dict[int, PaymentTransaction] = {}
        for tx in successful_tx:
            # Keep the most recent successful transaction per slot.
            if tx.slot_id not in tx_by_slot:
                tx_by_slot[tx.slot_id] = tx

        paid_slots = (
            db.session.query(Slot, Patient)
            .join(Patient, Slot.patient_id == Patient.id)
            .filter(
                Slot.coach_id.in_(coach_ids),
                Slot.status.in_(("booked", "completed")),
                Slot.paid.is_(True),
            )
            .all()
        )
        for slot, patient in paid_slots:
            paid_date = slot.paid_at
            if not paid_date:
                tx = tx_by_slot.get(slot.id)
                if tx:
                    paid_date = tx.updated_at or tx.created_at
            if not paid_date:
                # Fallback legacy data (manual paid before paid_at existed).
                paid_date = slot.start_utc
            if not paid_date or paid_date < month_start or paid_date >= month_end:
                continue
            coach = coach_by_id.get(slot.coach_id)
            default_rate = float(coach.settings.default_hourly_rate) if coach and coach.settings else 0.0
            rate = patient.effective_hourly_rate(default_rate)
            monthly_revenue_by_coach[slot.coach_id] = monthly_revenue_by_coach.get(slot.coach_id, 0.0) + (slot.duration_hours() * rate)

    monthly_billing_rows = []
    for c in coaches:
        monthly_billing_rows.append(
            {
                "coach_id": c.id,
                "coach_name": c.name,
                "revenue": f"{monthly_revenue_by_coach.get(c.id, 0.0):.2f}",
            }
        )
    monthly_total = f"{sum(monthly_revenue_by_coach.values()):.2f}"

    return render_template(
        "admin/dashboard.html",
        create_form=create_form,
        reset_password_form=reset_password_form,
        coaches=coaches,
        selected_year=selected_year,
        selected_month=selected_month,
        monthly_billing_rows=monthly_billing_rows,
        monthly_total=monthly_total,
    )


@bp.route("/create-coach", methods=["POST"])
@login_required
@admin_required
def create_coach():
    create_form = CoachRegisterForm()
    if not create_form.validate_on_submit():
        flash("Formulaire invalide.", "danger")
        return redirect(url_for("admin.dashboard"))

    email = create_form.email.data.strip().lower()
    if User.query.filter(func.lower(User.email) == email).first():
        flash("Cet email est déjà utilisé.", "danger")
        return redirect(url_for("admin.dashboard"))

    u = User(
        email=email,
        name=create_form.name.data.strip(),
        role="coach",
    )
    u.set_password(create_form.password.data)
    db.session.add(u)
    db.session.flush()
    db.session.add(CoachSettings(user_id=u.id))
    db.session.commit()
    flash("Compte coach créé avec succès.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/coach/<int:coach_id>/reset-password", methods=["POST"])
@login_required
@admin_required
def reset_coach_password(coach_id):
    reset_password_form = ResetCoachPasswordForm()
    if not reset_password_form.validate_on_submit():
        flash("Mot de passe invalide (minimum 8 caractères).", "danger")
        return redirect(url_for("admin.dashboard"))

    coach = User.query.filter_by(id=coach_id, role="coach").first_or_404()
    coach.set_password(reset_password_form.password.data)
    coach.must_change_password = True
    db.session.commit()
    flash(f"Mot de passe réinitialisé pour {coach.name}. Le coach devra le changer à la prochaine connexion.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/coach/<int:coach_id>/toggle-suspension", methods=["POST"])
@login_required
@admin_required
def toggle_suspension(coach_id):
    coach = User.query.filter_by(id=coach_id, role="coach").first_or_404()
    new_state = not bool(coach.is_suspended)
    coach.is_suspended = new_state
    for pu in User.query.filter_by(coach_id=coach.id, role="patient").all():
        pu.is_suspended = new_state
    db.session.commit()
    if new_state:
        flash("Coach suspendu. Ses patients n'ont plus accès.", "warning")
    else:
        flash("Coach réactivé. Ses patients ont de nouveau accès.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/coach/<int:coach_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_coach(coach_id):
    coach = User.query.filter_by(id=coach_id, role="coach").first_or_404()
    if coach.legal_hold:
        flash("Suppression impossible: coach sous legal hold.", "warning")
        return redirect(url_for("admin.dashboard"))

    patients = Patient.query.filter_by(coach_id=coach.id).all()
    patient_ids = [p.id for p in patients]
    patient_user_ids = [p.user_id for p in patients]

    # Nettoyage des fichiers contrats
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    for cv in ContractVersion.query.filter(ContractVersion.patient_id.in_(patient_ids)).all() if patient_ids else []:
        fpath = upload_root / cv.file_path
        if fpath.is_file():
            try:
                fpath.unlink()
            except OSError:
                current_app.logger.warning("Impossible de supprimer le fichier contrat: %s", fpath)

    # Suppression des données liées
    if patient_ids:
        ContractVersion.query.filter(ContractVersion.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        Slot.query.filter(Slot.patient_id.in_(patient_ids)).delete(synchronize_session=False)
        Patient.query.filter(Patient.id.in_(patient_ids)).delete(synchronize_session=False)
    Slot.query.filter(Slot.coach_id == coach.id).delete(synchronize_session=False)
    AuditLog.query.filter(AuditLog.coach_id == coach.id).delete(synchronize_session=False)
    CoachSettings.query.filter(CoachSettings.user_id == coach.id).delete(synchronize_session=False)
    if patient_user_ids:
        User.query.filter(User.id.in_(patient_user_ids)).delete(synchronize_session=False)

    db.session.delete(coach)
    db.session.commit()
    flash("Coach et tous ses clients supprimés définitivement.", "success")
    return redirect(url_for("admin.dashboard"))


def _user_export_payload(user: User) -> dict:
    payload = {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "is_suspended": bool(user.is_suspended),
            "legal_hold": bool(user.legal_hold),
        },
        "coach_settings": None,
        "patients": [],
        "slots_as_coach": [],
        "slots_as_patient": [],
        "contracts": [],
        "gdpr_requests": [],
        "security_incidents": [],
    }
    if user.settings:
        payload["coach_settings"] = {
            "default_hourly_rate": str(user.settings.default_hourly_rate),
            "min_days_between_sessions": user.settings.min_days_between_sessions,
            "timezone": user.settings.timezone,
            "cancellation_hours": user.settings.cancellation_hours,
            "email_notifications": bool(user.settings.email_notifications),
        }
    if user.role == "coach":
        for p in Patient.query.filter_by(coach_id=user.id).all():
            payload["patients"].append(
                {
                    "id": p.id,
                    "user_id": p.user_id,
                    "first_name": p.first_name,
                    "last_name": p.last_name,
                    "email": p.user.email if p.user else None,
                    "sessions_planned": p.sessions_planned,
                    "active": bool(p.active),
                }
            )
        for s in Slot.query.filter_by(coach_id=user.id).all():
            payload["slots_as_coach"].append(
                {
                    "id": s.id,
                    "patient_id": s.patient_id,
                    "start_utc": s.start_utc.isoformat() if s.start_utc else None,
                    "end_utc": s.end_utc.isoformat() if s.end_utc else None,
                    "status": s.status,
                    "paid": bool(s.paid),
                }
            )
    if user.role == "patient" and user.patient_profile:
        pp = user.patient_profile
        for s in Slot.query.filter_by(patient_id=pp.id).all():
            payload["slots_as_patient"].append(
                {
                    "id": s.id,
                    "coach_id": s.coach_id,
                    "start_utc": s.start_utc.isoformat() if s.start_utc else None,
                    "end_utc": s.end_utc.isoformat() if s.end_utc else None,
                    "status": s.status,
                    "notes": s.notes,
                }
            )
        for c in ContractVersion.query.filter_by(patient_id=pp.id).all():
            payload["contracts"].append(
                {
                    "id": c.id,
                    "title": c.title,
                    "file_path": c.file_path,
                    "version": c.version,
                    "uploaded_at": c.uploaded_at.isoformat() if c.uploaded_at else None,
                }
            )
    for req in GdprRequest.query.filter_by(user_id=user.id).all():
        payload["gdpr_requests"].append(
            {
                "id": req.id,
                "request_type": req.request_type,
                "status": req.status,
                "created_at": req.created_at.isoformat() if req.created_at else None,
                "handled_at": req.handled_at.isoformat() if req.handled_at else None,
            }
        )
    for inc in SecurityIncident.query.filter(SecurityIncident.related_user_id == user.id).all():
        payload["security_incidents"].append(
            {
                "id": inc.id,
                "incident_type": inc.incident_type,
                "severity": inc.severity,
                "status": inc.status,
                "created_at": inc.created_at.isoformat() if inc.created_at else None,
                "closed_at": inc.closed_at.isoformat() if inc.closed_at else None,
            }
        )
    return payload


def _anonymize_user(user: User):
    suffix = f"user{user.id}"
    user.name = f"Anonymise {suffix}"
    user.email = f"anonymise-{suffix}@example.invalid"
    user.is_suspended = True
    if user.patient_profile:
        user.patient_profile.first_name = "Anonymise"
        user.patient_profile.last_name = suffix
        user.patient_profile.phone = None
    for sl in Slot.query.filter_by(patient_id=user.patient_profile.id).all() if user.patient_profile else []:
        sl.notes = None
        sl.meeting_link = None


@bp.route("/gdpr")
@login_required
@admin_required
def gdpr_dashboard():
    request_form = GdprRequestForm()
    incident_form = SecurityIncidentForm()
    gdpr_rows = GdprRequest.query.order_by(GdprRequest.created_at.desc()).limit(100).all()
    incident_rows = SecurityIncident.query.order_by(SecurityIncident.created_at.desc()).limit(100).all()
    return render_template(
        "admin/gdpr.html",
        request_form=request_form,
        incident_form=incident_form,
        gdpr_rows=gdpr_rows,
        incident_rows=incident_rows,
    )


@bp.route("/gdpr/request/new", methods=["POST"])
@login_required
@admin_required
def gdpr_request_new():
    form = GdprRequestForm()
    if not form.validate_on_submit():
        flash("Formulaire RGPD invalide.", "danger")
        return redirect(url_for("admin.gdpr_dashboard"))
    email = form.user_email.data.strip().lower()
    user = User.query.filter(func.lower(User.email) == email).first()
    if not user:
        flash("Utilisateur introuvable.", "danger")
        return redirect(url_for("admin.gdpr_dashboard"))
    req = GdprRequest(
        user_id=user.id,
        request_type=form.request_type.data.strip().lower(),
        notes=(form.notes.data or "").strip() or None,
    )
    db.session.add(req)
    db.session.commit()
    flash("Demande RGPD créée.", "success")
    return redirect(url_for("admin.gdpr_dashboard"))


@bp.route("/gdpr/request/<int:rid>/status", methods=["POST"])
@login_required
@admin_required
def gdpr_request_status(rid):
    req = GdprRequest.query.get_or_404(rid)
    status = (request.form.get("status") or "").strip().lower()
    if status not in ("new", "in_review", "done", "rejected"):
        flash("Statut invalide.", "danger")
        return redirect(url_for("admin.gdpr_dashboard"))
    req.status = status
    req.handled_by_user_id = current_user.id
    req.handled_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash("Statut RGPD mis à jour.", "success")
    return redirect(url_for("admin.gdpr_dashboard"))


@bp.route("/gdpr/export/<int:user_id>")
@login_required
@admin_required
def gdpr_export_user(user_id):
    user = User.query.get_or_404(user_id)
    payload = _user_export_payload(user)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("export.json", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    mem.seek(0)
    return send_file(
        mem,
        as_attachment=True,
        mimetype="application/zip",
        download_name=f"gdpr-export-user-{user.id}.zip",
    )


@bp.route("/gdpr/anonymize/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def gdpr_anonymize_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.legal_hold:
        flash("Utilisateur sous legal hold: anonymisation bloquée.", "warning")
        return redirect(url_for("admin.gdpr_dashboard"))
    _anonymize_user(user)
    db.session.commit()
    flash("Utilisateur anonymisé.", "success")
    return redirect(url_for("admin.gdpr_dashboard"))


@bp.route("/gdpr/legal-hold/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def toggle_legal_hold(user_id):
    user = User.query.get_or_404(user_id)
    user.legal_hold = not bool(user.legal_hold)
    db.session.commit()
    flash("Legal hold mis à jour.", "success")
    return redirect(url_for("admin.gdpr_dashboard"))


@bp.route("/security/incident/new", methods=["POST"])
@login_required
@admin_required
def security_incident_new():
    form = SecurityIncidentForm()
    if not form.validate_on_submit():
        flash("Formulaire incident invalide.", "danger")
        return redirect(url_for("admin.gdpr_dashboard"))
    related_user_id = None
    if form.related_user_email.data:
        ru = User.query.filter(func.lower(User.email) == form.related_user_email.data.strip().lower()).first()
        related_user_id = ru.id if ru else None
    create_security_incident(
        incident_type=form.incident_type.data.strip(),
        severity=form.severity.data.strip().lower(),
        description=form.description.data.strip(),
        related_user_id=related_user_id,
        created_by_user_id=current_user.id,
    )
    db.session.commit()
    flash("Incident enregistré.", "success")
    return redirect(url_for("admin.gdpr_dashboard"))


@bp.route("/security/incident/<int:iid>/close", methods=["POST"])
@login_required
@admin_required
def security_incident_close(iid):
    inc = SecurityIncident.query.get_or_404(iid)
    inc.status = "closed"
    inc.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    inc.closed_by_user_id = current_user.id
    db.session.commit()
    flash("Incident clôturé.", "success")
    return redirect(url_for("admin.gdpr_dashboard"))


@bp.route("/platform-payments", methods=["GET", "POST"])
@login_required
@admin_required
def platform_payments():
    form = PlatformStripeSettingsForm()
    if form.validate_on_submit():
        # Critical values are encrypted at rest.
        set_platform_setting("stripe_secret_key", form.stripe_secret_key.data, encrypt=True)
        set_platform_setting("stripe_webhook_secret", form.stripe_webhook_secret.data, encrypt=True)
        set_platform_setting("stripe_publishable_key", form.stripe_publishable_key.data, encrypt=False)
        set_platform_setting("stripe_connect_refresh_url", form.stripe_connect_refresh_url.data, encrypt=False)
        set_platform_setting("stripe_connect_return_url", form.stripe_connect_return_url.data, encrypt=False)
        db.session.commit()
        flash("Configuration Stripe plateforme enregistrée.", "success")
        return redirect(url_for("admin.platform_payments"))

    if request.method == "GET":
        form.stripe_publishable_key.data = (
            get_platform_setting("stripe_publishable_key")
            or current_app.config.get("STRIPE_PUBLISHABLE_KEY")
            or ""
        )
        form.stripe_connect_refresh_url.data = (
            get_platform_setting("stripe_connect_refresh_url")
            or current_app.config.get("STRIPE_CONNECT_REFRESH_URL")
            or ""
        )
        form.stripe_connect_return_url.data = (
            get_platform_setting("stripe_connect_return_url")
            or current_app.config.get("STRIPE_CONNECT_RETURN_URL")
            or ""
        )

    return render_template(
        "admin/platform_payments.html",
        form=form,
        has_secret=bool(get_platform_setting("stripe_secret_key", decrypt=True) or current_app.config.get("STRIPE_SECRET_KEY")),
        has_webhook=bool(get_platform_setting("stripe_webhook_secret", decrypt=True) or current_app.config.get("STRIPE_WEBHOOK_SECRET")),
    )


@bp.route("/platform-email", methods=["GET", "POST"])
@login_required
@admin_required
def platform_email():
    form = PlatformSmtpSettingsForm()
    if form.validate_on_submit():
        # Password is stored encrypted at rest.
        set_platform_setting("mail_server", form.mail_server.data, encrypt=False)
        if form.mail_port.data:
            set_platform_setting("mail_port", str(form.mail_port.data), encrypt=False)
        set_platform_setting("mail_use_tls", "true" if form.mail_use_tls.data else "false", encrypt=False)
        set_platform_setting("mail_username", form.mail_username.data, encrypt=False)
        if (form.mail_password.data or "").strip():
            set_platform_setting("mail_password", form.mail_password.data, encrypt=True)
        set_platform_setting("mail_default_sender", form.mail_default_sender.data, encrypt=False)
        db.session.commit()
        flash("Configuration SMTP globale enregistrée.", "success")
        return redirect(url_for("admin.platform_email"))

    if request.method == "GET":
        form.mail_server.data = get_platform_setting("mail_server") or current_app.config.get("MAIL_SERVER") or ""
        port_v = get_platform_setting("mail_port") or current_app.config.get("MAIL_PORT")
        try:
            form.mail_port.data = int(port_v) if port_v else 587
        except (TypeError, ValueError):
            form.mail_port.data = 587
        tls_v = get_platform_setting("mail_use_tls")
        if tls_v is None:
            form.mail_use_tls.data = bool(current_app.config.get("MAIL_USE_TLS", True))
        else:
            form.mail_use_tls.data = str(tls_v).lower() in ("1", "true", "yes")
        form.mail_username.data = get_platform_setting("mail_username") or current_app.config.get("MAIL_USERNAME") or ""
        form.mail_default_sender.data = get_platform_setting("mail_default_sender") or current_app.config.get("MAIL_DEFAULT_SENDER") or ""

    return render_template(
        "admin/platform_email.html",
        form=form,
        has_password=bool(get_platform_setting("mail_password", decrypt=True) or current_app.config.get("MAIL_PASSWORD")),
    )
