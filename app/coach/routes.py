import csv
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.coach import bp
from app.forms import CoachSettingsForm, ContractUploadForm, PatientCreateForm, PatientEditForm, SessionNotesForm, SlotForm
from app.models import AuditLog, ContractVersion, Patient, Slot, User, audit_log
from app.utils.datetime_parse import local_input_to_utc_naive, utc_naive_to_local_str
from app.utils.decorators import coach_required
from app.utils.forecast import net_after_charges_monthly, pipeline_revenue_coach, scheduled_revenue_coach
from app.utils.pdf import build_invoice_pdf


def _coach():
    return current_user


def _settings():
    s = _coach().settings
    if not s:
        abort(500)
    return s


@bp.route("/")
@login_required
@coach_required
def dashboard():
    cid = _coach().id
    forecast = net_after_charges_monthly(cid)
    patients = Patient.query.filter_by(coach_id=cid, active=True).count()
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
        upcoming=upcoming,
    )


@bp.route("/settings", methods=["GET", "POST"])
@login_required
@coach_required
def settings():
    s = _settings()
    form = CoachSettingsForm(
        default_hourly_rate=s.default_hourly_rate,
        min_days_between_sessions=s.min_days_between_sessions,
        timezone=s.timezone,
        cancellation_hours=s.cancellation_hours,
        email_notifications=s.email_notifications,
        tax_rate_percent=s.tax_rate_percent,
        social_charges_percent=s.social_charges_percent,
        fixed_costs_monthly=s.fixed_costs_monthly,
        target_net_salary_monthly=s.target_net_salary_monthly,
    )
    if form.validate_on_submit():
        form.populate_obj(s)
        db.session.commit()
        audit_log(_coach().id, _coach().id, "settings_updated", "CoachSettings", s.id, {})
        flash("Paramètres enregistrés.", "success")
        return redirect(url_for("coach.settings"))
    return render_template("coach/settings.html", form=form)


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
            flash("Patient créé. Il peut se connecter avec son email.", "success")
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
    contract = p.contracts[0] if p.contracts else None
    contract_form = ContractUploadForm()
    return render_template(
        "coach/patient_detail.html",
        patient=p,
        slots=slots,
        remaining_sessions=remaining,
        contract=contract,
        contract_form=contract_form,
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
        flash("Fiche patient mise à jour.", "success")
        return redirect(url_for("coach.patient_detail", pid=p.id))
    return render_template("coach/patient_edit.html", form=form, patient=p)


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
            end = local_input_to_utc_naive(form.end_local.data, tz)
        except Exception as exc:
            flash(f"Date invalide : {exc}", "danger")
            return redirect(url_for("coach.slots"))
        if end <= start:
            flash("La fin doit être après le début.", "danger")
            return redirect(url_for("coach.slots"))
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
        paid=slot.paid,
        invoice_number=slot.invoice_number or "",
        mark_completed=slot.status == "completed",
    )
    if form.validate_on_submit():
        slot.notes = form.notes.data
        slot.paid = form.paid.data
        slot.invoice_number = form.invoice_number.data.strip() or None
        if form.mark_completed.data:
            slot.status = "completed"
        elif slot.status == "completed" and not form.mark_completed.data:
            slot.status = "booked"
        db.session.commit()
        audit_log(_coach().id, _coach().id, "session_updated", "Slot", slot.id, {"patient_id": p.id})
        flash("Séance enregistrée.", "success")
        return redirect(url_for("coach.slot_session", sid=sid))
    return render_template("coach/slot_session.html", slot=slot, patient=p, form=form)


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
