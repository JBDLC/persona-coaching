from pathlib import Path

from flask import current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app import db
from app.admin import bp
from app.forms import CoachRegisterForm
from app.models import AuditLog, CoachSettings, ContractVersion, Patient, Slot, User
from app.utils.decorators import admin_required


@bp.route("/")
@login_required
@admin_required
def dashboard():
    form = CoachRegisterForm()
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
    return render_template("admin/dashboard.html", form=form, coaches=coaches)


@bp.route("/create-coach", methods=["POST"])
@login_required
@admin_required
def create_coach():
    form = CoachRegisterForm()
    if not form.validate_on_submit():
        flash("Formulaire invalide.", "danger")
        return redirect(url_for("admin.dashboard"))

    email = form.email.data.strip().lower()
    if User.query.filter(func.lower(User.email) == email).first():
        flash("Cet email est déjà utilisé.", "danger")
        return redirect(url_for("admin.dashboard"))

    u = User(
        email=email,
        name=form.name.data.strip(),
        role="coach",
    )
    u.set_password(form.password.data)
    db.session.add(u)
    db.session.flush()
    db.session.add(CoachSettings(user_id=u.id))
    db.session.commit()
    flash("Compte coach créé avec succès.", "success")
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
