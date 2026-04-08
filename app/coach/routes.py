import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.coach import bp
from app.forms import (
    CoachSettingsForm,
    ContractUploadForm,
    PatientCreateForm,
    PatientEditForm,
    ResetPatientPasswordForm,
    SessionInvoiceUploadForm,
    SessionNotesForm,
    SlotForm,
)
from app.models import AuditLog, ContractVersion, Patient, Slot, User, audit_log
from app.utils.datetime_parse import local_input_to_utc_naive, utc_naive_to_local_str
from app.utils.decorators import coach_required
from app.utils.email import (
    send_session_invoice_email,
    send_session_report_email,
)
from app.utils.forecast import collected_revenue_coach, net_after_charges_monthly, pipeline_revenue_coach, scheduled_revenue_coach
from app.utils.pdf import build_invoice_pdf
from app.utils.crypto import encrypt_text
from app.utils.stripe_connect import create_onboarding_link, get_or_create_connected_account, get_stripe_publishable_key, sync_account_state

PATIENT_ALERT_ACTIONS = (
    "patient_booking_created",
    "patient_booking_cancelled",
    "payment_succeeded",
    "payment_failed",
)


def _coach():
    return current_user


def _settings():
    s = _coach().settings
    if not s:
        abort(500)
    return s


def _followed_terms() -> tuple[str, str]:
    singular = "patient" if _coach().professional_kind() == "psychologue" else "client"
    return singular, f"{singular}s"


@bp.route("/")
@login_required
@coach_required
def dashboard():
    cid = _coach().id
    forecast = net_after_charges_monthly(cid)
    settings = _settings()
    patients = Patient.query.filter_by(coach_id=cid, active=True).count()
    alerts_q = AuditLog.query.filter(
        AuditLog.coach_id == cid,
        AuditLog.action.in_(PATIENT_ALERT_ACTIONS),
    )
    if settings.last_alert_seen_at:
        alerts_q = alerts_q.filter(AuditLog.created_at > settings.last_alert_seen_at)
    alerts_unread_count = alerts_q.count()
    funds_collected = collected_revenue_coach(cid)
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    upcoming = (
        Slot.query.filter(
            Slot.coach_id == cid,
            Slot.status.in_(("booked", "completed")),
            Slot.start_utc >= now_naive,
        )
        .order_by(Slot.start_utc.asc())
        .limit(8)
        .all()
    )
    return render_template(
        "coach/dashboard.html",
        forecast=forecast,
        scheduled_revenue=scheduled_revenue_coach(cid),
        pipeline_revenue=pipeline_revenue_coach(cid),
        patients_count=patients,
        alerts_unread_count=alerts_unread_count,
        funds_collected=f"{funds_collected:.2f}",
        upcoming=upcoming,
    )


@bp.route("/settings", methods=["GET", "POST"])
@login_required
@coach_required
def settings():
    s = _settings()
    existing_smtp_password = s.smtp_password
    form = CoachSettingsForm(
        default_hourly_rate=s.default_hourly_rate,
        min_days_between_sessions=s.min_days_between_sessions,
        timezone=s.timezone,
        cancellation_hours=s.cancellation_hours,
        email_notifications=s.email_notifications,
        notify_booking_patient=s.notify_booking_patient,
        notify_booking_coach=s.notify_booking_coach,
        notify_reminder_day_before=s.notify_reminder_day_before,
        smtp_server=s.smtp_server,
        smtp_port=s.smtp_port,
        smtp_use_tls=s.smtp_use_tls,
        smtp_username=s.smtp_username,
        smtp_default_sender=s.smtp_default_sender,
        profile_bio=s.profile_bio,
        profile_youtube_url=s.profile_youtube_url,
        tax_rate_percent=s.tax_rate_percent,
        social_charges_percent=s.social_charges_percent,
        fixed_costs_monthly=s.fixed_costs_monthly,
        target_net_salary_monthly=s.target_net_salary_monthly,
    )
    if form.validate_on_submit():
        s.default_hourly_rate = form.default_hourly_rate.data
        s.min_days_between_sessions = form.min_days_between_sessions.data
        s.timezone = form.timezone.data.strip()
        s.cancellation_hours = form.cancellation_hours.data
        s.email_notifications = bool(form.email_notifications.data)
        s.notify_booking_patient = bool(form.notify_booking_patient.data)
        s.notify_booking_coach = bool(form.notify_booking_coach.data)
        s.notify_reminder_day_before = bool(form.notify_reminder_day_before.data)
        s.smtp_server = (form.smtp_server.data or "").strip() or None
        s.smtp_port = form.smtp_port.data or 587
        s.smtp_use_tls = bool(form.smtp_use_tls.data)
        s.smtp_username = (form.smtp_username.data or "").strip() or None
        s.smtp_default_sender = (form.smtp_default_sender.data or "").strip() or None
        s.profile_bio = (form.profile_bio.data or "").strip() or None
        s.profile_youtube_url = (form.profile_youtube_url.data or "").strip() or None
        s.tax_rate_percent = form.tax_rate_percent.data
        s.social_charges_percent = form.social_charges_percent.data
        s.fixed_costs_monthly = form.fixed_costs_monthly.data
        s.target_net_salary_monthly = form.target_net_salary_monthly.data
        if form.smtp_password.data:
            s.smtp_password = encrypt_text(form.smtp_password.data)
        else:
            s.smtp_password = existing_smtp_password
        if form.profile_photo.data:
            ext = Path(form.profile_photo.data.filename).suffix.lower() or ".jpg"
            safe_stem = secure_filename(Path(form.profile_photo.data.filename).stem) or "coach"
            filename = f"{safe_stem}-{uuid.uuid4().hex}{ext}"
            base = Path(current_app.config["UPLOAD_FOLDER"]) / "coach_profiles" / str(_coach().id)
            base.mkdir(parents=True, exist_ok=True)
            dest = base / filename
            form.profile_photo.data.save(dest)
            up = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
            s.profile_image_path = str(dest.resolve().relative_to(up)).replace("\\", "/")
        db.session.commit()
        audit_log(_coach().id, _coach().id, "settings_updated", "CoachSettings", s.id, {})
        flash("Paramètres enregistrés.", "success")
        return redirect(url_for("coach.settings"))
    return render_template("coach/settings.html", form=form)


@bp.route("/payments")
@login_required
@coach_required
def payments_settings():
    s = _settings()
    error = None
    try:
        if s.stripe_account_id:
            sync_account_state(s)
            db.session.commit()
    except Exception as exc:
        current_app.logger.exception("Stripe sync failed")
        error = str(exc)
    return render_template(
        "coach/payments.html",
        stripe_account_id=s.stripe_account_id,
        stripe_state=s.stripe_onboarding_state or "not_connected",
        stripe_charges_enabled=bool(s.stripe_charges_enabled),
        stripe_payouts_enabled=bool(s.stripe_payouts_enabled),
        stripe_last_synced_at=s.stripe_last_synced_at,
        stripe_error=error,
        publishable_key=get_stripe_publishable_key(),
    )


@bp.route("/payments/connect", methods=["POST"])
@login_required
@coach_required
def payments_connect():
    s = _settings()
    try:
        account_id = get_or_create_connected_account(s, _coach().email)
        onboarding_url = create_onboarding_link(account_id)
        return redirect(onboarding_url)
    except Exception as exc:
        current_app.logger.exception("Stripe connect failed")
        flash(f"Impossible de lancer la connexion Stripe: {exc}", "danger")
        return redirect(url_for("coach.payments_settings"))


@bp.route("/payments/refresh", methods=["POST"])
@login_required
@coach_required
def payments_refresh():
    s = _settings()
    try:
        sync_account_state(s)
        db.session.commit()
        flash("Statut Stripe actualisé.", "success")
    except Exception as exc:
        current_app.logger.exception("Stripe refresh failed")
        flash(f"Échec de synchronisation Stripe: {exc}", "danger")
    return redirect(url_for("coach.payments_settings"))


@bp.route("/alerts")
@login_required
@coach_required
def alerts():
    rows = (
        AuditLog.query.filter(
            AuditLog.coach_id == _coach().id,
            AuditLog.action.in_(PATIENT_ALERT_ACTIONS),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(200)
        .all()
    )
    items = []
    for row in rows:
        meta = {}
        if row.meta_json:
            try:
                meta = json.loads(row.meta_json)
            except json.JSONDecodeError:
                meta = {}
        if row.action == "patient_booking_created":
            label = "Nouveau rendez-vous réservé"
        elif row.action == "patient_booking_cancelled":
            label = "Rendez-vous annulé"
        elif row.action == "payment_succeeded":
            label = "Paiement reçu"
        elif row.action == "payment_failed":
            label = "Paiement échoué"
        else:
            label = row.action
        items.append(
            {
                "label": label,
                "created_at": row.created_at,
                "patient_name": meta.get("patient_name"),
                "slot_id": row.entity_id if row.entity_type == "Slot" else None,
            }
        )
    s = _settings()
    s.last_alert_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    return render_template("coach/alerts.html", items=items)


@bp.route("/patients")
@login_required
@coach_required
def patients_list():
    rows = Patient.query.filter_by(coach_id=_coach().id).order_by(Patient.last_name, Patient.first_name).all()
    return render_template("coach/patients_list.html", patients=rows)


@bp.route("/patients/new", methods=["GET", "POST"])
@login_required
@coach_required
def patient_new():
    form = PatientCreateForm()
    followed_singular, followed_plural = _followed_terms()
    form.submit.label.text = f"Créer le {followed_singular}"
    form.sessions_planned.label.text = f"Nombre de séances prévues ({followed_plural})"
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("Cet email est déjà utilisé.", "danger")
        else:
            u = User(
                email=email,
                name=f"{form.first_name.data} {form.last_name.data}",
                role="patient",
                coach_id=_coach().id,
            )
            u.set_password(form.password.data)
            db.session.add(u)
            db.session.flush()
            p = Patient(
                coach_id=_coach().id,
                user_id=u.id,
                first_name=form.first_name.data.strip(),
                last_name=form.last_name.data.strip(),
                phone=form.phone.data,
                sessions_planned=form.sessions_planned.data,
                hourly_rate_override=form.hourly_rate_override.data if form.hourly_rate_override.data else None,
            )
            db.session.add(p)
            db.session.commit()
            audit_log(_coach().id, _coach().id, "patient_created", "Patient", p.id, {"email": email})
            flash(f"{followed_singular.capitalize()} créé. Il peut se connecter avec son email.", "success")
            return redirect(url_for("coach.patient_detail", pid=p.id))
    return render_template("coach/patient_new.html", form=form)


@bp.route("/patients/<int:pid>")
@login_required
@coach_required
def patient_detail(pid):
    p = Patient.query.filter_by(id=pid, coach_id=_coach().id).first_or_404()
    slots = (
        Slot.query.filter_by(patient_id=p.id)
        .order_by(Slot.start_utc.desc())
        .all()
    )
    done = Slot.query.filter_by(patient_id=p.id, status="completed").count()
    remaining = max(0, (p.sessions_planned or 0) - done)
    contract_form = ContractUploadForm()
    reset_password_form = ResetPatientPasswordForm()
    return render_template(
        "coach/patient_detail.html",
        patient=p,
        slots=slots,
        remaining_sessions=remaining,
        contracts=p.contracts,
        contract_form=contract_form,
        reset_password_form=reset_password_form,
    )


@bp.route("/patients/<int:pid>/edit", methods=["GET", "POST"])
@login_required
@coach_required
def patient_edit(pid):
    p = Patient.query.filter_by(id=pid, coach_id=_coach().id).first_or_404()
    form = PatientEditForm(
        first_name=p.first_name,
        last_name=p.last_name,
        phone=p.phone,
        sessions_planned=p.sessions_planned,
        hourly_rate_override=p.hourly_rate_override,
        active=p.active,
    )
    followed_singular, followed_plural = _followed_terms()
    form.sessions_planned.label.text = f"Séances prévues ({followed_plural})"
    if form.validate_on_submit():
        old = {"sessions_planned": p.sessions_planned, "hourly_rate": str(p.hourly_rate_override)}
        form.populate_obj(p)
        p.hourly_rate_override = form.hourly_rate_override.data if form.hourly_rate_override.data else None
        db.session.commit()
        audit_log(
            _coach().id,
            _coach().id,
            "patient_updated",
            "Patient",
            p.id,
            {"old": old, "new": {"sessions_planned": p.sessions_planned}},
        )
        flash(f"Fiche {followed_singular} mise à jour.", "success")
        return redirect(url_for("coach.patient_detail", pid=p.id))
    return render_template("coach/patient_edit.html", form=form, patient=p)


@bp.route("/patients/<int:pid>/reset-password", methods=["POST"])
@login_required
@coach_required
def patient_reset_password(pid):
    p = Patient.query.filter_by(id=pid, coach_id=_coach().id).first_or_404()
    form = ResetPatientPasswordForm()
    if not form.validate_on_submit():
        flash("Mot de passe invalide (minimum 8 caractères).", "danger")
        return redirect(url_for("coach.patient_detail", pid=pid))

    p.user.set_password(form.password.data)
    p.user.must_change_password = True
    db.session.commit()
    audit_log(_coach().id, _coach().id, "patient_password_reset", "Patient", p.id, {"patient_user_id": p.user.id})
    followed_singular, _ = _followed_terms()
    flash(
        f"Mot de passe {followed_singular} réinitialisé. Le {followed_singular} devra le changer à la prochaine connexion.",
        "success",
    )
    return redirect(url_for("coach.patient_detail", pid=pid))


@bp.route("/patients/<int:pid>/contract/download")
@login_required
@coach_required
def patient_contract_download(pid):
    p = Patient.query.filter_by(id=pid, coach_id=_coach().id).first_or_404()
    if not p.contracts:
        flash("Aucun contrat.", "warning")
        return redirect(url_for("coach.patient_detail", pid=pid))
    cv = p.contracts[0]
    base = Path(current_app.config["UPLOAD_FOLDER"])
    path = base / cv.file_path
    if not path.is_file():
        abort(404)
    ext = path.suffix or ".pdf"
    return send_file(path, as_attachment=True, download_name=f"contrat-v{cv.version}{ext}")


@bp.route("/patients/<int:pid>/contract/<int:cid>/download")
@login_required
@coach_required
def patient_contract_download_one(pid, cid):
    _ = Patient.query.filter_by(id=pid, coach_id=_coach().id).first_or_404()
    cv = ContractVersion.query.filter_by(id=cid, patient_id=pid).first_or_404()
    base = Path(current_app.config["UPLOAD_FOLDER"])
    path = base / cv.file_path
    if not path.is_file():
        abort(404)
    ext = path.suffix or ".pdf"
    return send_file(path, as_attachment=True, download_name=f"contrat-v{cv.version}{ext}")


@bp.route("/patients/<int:pid>/contract", methods=["POST"])
@login_required
@coach_required
def patient_contract_upload(pid):
    p = Patient.query.filter_by(id=pid, coach_id=_coach().id).first_or_404()
    form = ContractUploadForm()
    if form.validate_on_submit():
        ext = Path(form.file.data.filename).suffix.lower() or ".bin"
        fname = f"{uuid.uuid4().hex}{ext}"
        base = Path(current_app.config["UPLOAD_FOLDER"]) / "contracts" / str(p.id)
        base.mkdir(parents=True, exist_ok=True)
        dest = base / fname
        form.file.data.save(dest)
        ver = max((c.version for c in p.contracts), default=0) + 1
        up = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        rel = str(dest.resolve().relative_to(up)).replace("\\", "/")
        cv = ContractVersion(
            patient_id=p.id,
            title=form.title.data.strip(),
            file_path=rel,
            version=ver,
        )
        db.session.add(cv)
        db.session.commit()
        audit_log(_coach().id, _coach().id, "contract_uploaded", "ContractVersion", cv.id, {"patient_id": p.id})
        flash("Contrat enregistré.", "success")
    else:
        for e in form.file.errors:
            flash(e, "danger")
    return redirect(url_for("coach.patient_detail", pid=pid))


@bp.route("/slots", methods=["GET", "POST"])
@login_required
@coach_required
def slots():
    tz = _settings().timezone
    form = SlotForm()
    if form.validate_on_submit():
        try:
            start = local_input_to_utc_naive(form.start_local.data, tz)
        except Exception as exc:
            flash(f"Date invalide : {exc}", "danger")
            return redirect(url_for("coach.slots"))
        end = start + timedelta(hours=1)
        slot = Slot(coach_id=_coach().id, start_utc=start, end_utc=end, status="available")
        db.session.add(slot)
        db.session.commit()
        audit_log(_coach().id, _coach().id, "slot_created", "Slot", slot.id, {})
        flash("Créneau ajouté.", "success")
        return redirect(url_for("coach.slots"))
    rows = Slot.query.filter_by(coach_id=_coach().id).order_by(Slot.start_utc.desc()).limit(200).all()
    return render_template("coach/slots.html", form=form, slots=rows, tz=tz)


@bp.route("/slots/<int:sid>/session", methods=["GET", "POST"])
@login_required
@coach_required
def slot_session(sid):
    slot = Slot.query.filter_by(id=sid, coach_id=_coach().id).first_or_404()
    if slot.status == "available":
        flash("Ce créneau n’est pas réservé.", "warning")
        return redirect(url_for("coach.slots"))
    p = slot.patient
    form = SessionNotesForm(
        notes=slot.notes or "",
        meeting_link=slot.meeting_link or "",
        paid=slot.paid,
        invoice_number=slot.invoice_number or "",
        mark_completed=slot.status == "completed",
    )
    invoice_form = SessionInvoiceUploadForm()
    if form.validate_on_submit():
        old_paid = bool(slot.paid)
        slot.notes = form.notes.data
        slot.meeting_link = form.meeting_link.data.strip() if form.meeting_link.data else None
        slot.paid = form.paid.data
        if not old_paid and slot.paid:
            slot.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if old_paid and not slot.paid:
            slot.paid_at = None
        slot.invoice_number = form.invoice_number.data.strip() or None
        if form.mark_completed.data:
            slot.status = "completed"
        elif slot.status == "completed" and not form.mark_completed.data:
            slot.status = "booked"
        db.session.commit()
        if not old_paid and slot.paid:
            audit_log(
                _coach().id,
                _coach().id,
                "payment_succeeded",
                "Slot",
                slot.id,
                {"patient_name": p.display_name() if p else None, "source": "manual"},
            )
            db.session.commit()
        audit_log(_coach().id, _coach().id, "session_updated", "Slot", slot.id, {"patient_id": p.id})
        flash("Séance enregistrée.", "success")
        return redirect(url_for("coach.slot_session", sid=sid))
    return render_template("coach/slot_session.html", slot=slot, patient=p, form=form, invoice_form=invoice_form)


@bp.route("/slots/<int:sid>/send-report", methods=["POST"])
@login_required
@coach_required
def slot_send_report(sid):
    slot = Slot.query.filter_by(id=sid, coach_id=_coach().id).first_or_404()
    followed_singular, _ = _followed_terms()
    if not slot.patient_id or not slot.patient or not slot.patient.user:
        flash(f"Aucun {followed_singular} associé à ce créneau.", "danger")
        return redirect(url_for("coach.slot_session", sid=sid))
    posted_notes = (request.form.get("notes") or "").strip()
    if posted_notes:
        slot.notes = posted_notes
        db.session.commit()
    notes = (slot.notes or "").strip()
    if not notes:
        flash("Ajoutez un compte rendu avant l'envoi par email.", "warning")
        return redirect(url_for("coach.slot_session", sid=sid))
    s = _settings()
    ok = send_session_report_email(
        slot.patient.user.email,
        slot.patient.display_name(),
        utc_naive_to_local_str(slot.start_utc, s.timezone),
        _coach().name,
        notes,
        coach_settings=s,
    )
    if ok:
        audit_log(_coach().id, _coach().id, "session_report_emailed", "Slot", slot.id, {"patient_id": slot.patient.id})
        db.session.commit()
        flash(f"Compte rendu envoyé au {followed_singular}.", "success")
    else:
        flash("Échec de l'envoi email. Vérifiez votre configuration SMTP.", "danger")
    return redirect(url_for("coach.slot_session", sid=sid))


@bp.route("/slots/<int:sid>/invoice/upload", methods=["POST"])
@login_required
@coach_required
def slot_invoice_upload(sid):
    slot = Slot.query.filter_by(id=sid, coach_id=_coach().id).first_or_404()
    if not slot.patient_id:
        flash("Impossible de déposer une facture sans patient associé.", "warning")
        return redirect(url_for("coach.slot_session", sid=sid))
    form = SessionInvoiceUploadForm()
    if not form.validate_on_submit():
        flash("Fichier de facture invalide.", "danger")
        return redirect(url_for("coach.slot_session", sid=sid))

    ext = Path(form.file.data.filename).suffix.lower() or ".pdf"
    safe_stem = secure_filename(Path(form.file.data.filename).stem) or "facture"
    filename = f"{safe_stem}-{uuid.uuid4().hex}{ext}"
    base = Path(current_app.config["UPLOAD_FOLDER"]) / "invoices" / str(slot.id)
    base.mkdir(parents=True, exist_ok=True)
    dest = base / filename
    form.file.data.save(dest)

    up = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    rel = str(dest.resolve().relative_to(up)).replace("\\", "/")
    slot.invoice_file_path = rel
    slot.invoice_uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash("Facture téléversée.", "success")
    return redirect(url_for("coach.slot_session", sid=sid))


@bp.route("/slots/<int:sid>/invoice/download")
@login_required
@coach_required
def slot_invoice_download(sid):
    slot = Slot.query.filter_by(id=sid, coach_id=_coach().id).first_or_404()
    if not slot.invoice_file_path:
        flash("Aucune facture téléversée.", "warning")
        return redirect(url_for("coach.slot_session", sid=sid))
    path = Path(current_app.config["UPLOAD_FOLDER"]) / slot.invoice_file_path
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


@bp.route("/slots/<int:sid>/invoice/send-email", methods=["POST"])
@login_required
@coach_required
def slot_send_invoice_email(sid):
    slot = Slot.query.filter_by(id=sid, coach_id=_coach().id).first_or_404()
    if not slot.patient or not slot.patient.user:
        flash("Aucun patient associé à cette séance.", "warning")
        return redirect(url_for("coach.slot_session", sid=sid))
    if not slot.invoice_file_path:
        flash("Téléversez une facture avant l'envoi par email.", "warning")
        return redirect(url_for("coach.slot_session", sid=sid))
    path = Path(current_app.config["UPLOAD_FOLDER"]) / slot.invoice_file_path
    if not path.is_file():
        flash("Fichier facture introuvable.", "danger")
        return redirect(url_for("coach.slot_session", sid=sid))
    s = _settings()
    ok = send_session_invoice_email(
        slot.patient.user.email,
        slot.patient.display_name(),
        utc_naive_to_local_str(slot.start_utc, s.timezone),
        _coach().name,
        path.name,
        path.read_bytes(),
        coach_settings=s,
    )
    if ok:
        audit_log(_coach().id, _coach().id, "session_invoice_emailed", "Slot", slot.id, {"patient_id": slot.patient.id})
        db.session.commit()
        flash("Facture envoyée par email au patient.", "success")
    else:
        flash("Échec de l'envoi de la facture par email.", "danger")
    return redirect(url_for("coach.slot_session", sid=sid))


@bp.route("/slots/<int:sid>/invoice.pdf")
@login_required
@coach_required
def slot_invoice_pdf(sid):
    slot = Slot.query.filter_by(id=sid, coach_id=_coach().id).first_or_404()
    if not slot.patient_id:
        abort(404)
    p = slot.patient
    rate = p.effective_hourly_rate(float(_settings().default_hourly_rate))
    amount = f"{slot.duration_hours() * rate:.2f} €"
    inv = slot.invoice_number or f"DRAFT-{slot.id}"
    pdf = build_invoice_pdf(
        inv,
        _coach().name,
        p.display_name(),
        utc_naive_to_local_str(slot.start_utc, _settings().timezone),
        amount,
    )
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"facture-{inv}.pdf",
    )


@bp.route("/slots/<int:sid>/delete", methods=["POST"])
@login_required
@coach_required
def slot_delete(sid):
    slot = Slot.query.filter_by(id=sid, coach_id=_coach().id).first_or_404()
    if slot.status != "available":
        flash("Impossible de supprimer un créneau réservé ou passé (annulez d’abord).", "danger")
        return redirect(url_for("coach.slots"))
    db.session.delete(slot)
    db.session.commit()
    audit_log(_coach().id, _coach().id, "slot_deleted", "Slot", sid, {})
    flash("Créneau supprimé.", "info")
    return redirect(url_for("coach.slots"))


@bp.route("/audit")
@login_required
@coach_required
def audit():
    rows = (
        AuditLog.query.filter_by(coach_id=_coach().id)
        .order_by(AuditLog.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template("coach/audit.html", rows=rows)


@bp.route("/export/patients.csv")
@login_required
@coach_required
def export_patients_csv():
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["id", "prenom", "nom", "email", "telephone", "seances_prevues", "actif", "cree_le"])
    for p in Patient.query.filter_by(coach_id=_coach().id).order_by(Patient.id).all():
        w.writerow(
            [
                p.id,
                p.first_name,
                p.last_name,
                p.user.email,
                p.phone or "",
                p.sessions_planned,
                "oui" if p.active else "non",
                p.created_at.isoformat() if p.created_at else "",
            ]
        )
    mem = io.BytesIO()
    mem.write(out.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name="patients_export.csv",
    )
