from datetime import datetime, timezone
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.models import Patient, Slot
from app.patient import bp
from app.utils.booking import can_book_after_min_days, can_cancel_slot, last_session_end_utc
from app.utils.datetime_parse import utc_naive_to_local_str
from app.utils.decorators import patient_required
from app.utils.email import send_booking_confirmation, send_coach_new_booking
from app.utils.pdf import build_session_book_pdf


def _patient_profile() -> Patient:
    p = current_user.patient_profile
    if not p:
        abort(403)
    return p


def _coach_user():
    from app.models import User

    if not current_user.coach_id:
        return None
    return db.session.get(User, current_user.coach_id)


@bp.route("/")
@login_required
@patient_required
def dashboard():
    p = _patient_profile()
    coach = _coach_user()
    completed = Slot.query.filter_by(patient_id=p.id, status="completed").count()
    remaining = max(0, (p.sessions_planned or 0) - completed)
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    upcoming = (
        Slot.query.filter(
            Slot.patient_id == p.id,
            Slot.status.in_(("booked", "completed")),
            Slot.start_utc >= now_naive,
        )
        .order_by(Slot.start_utc.asc())
        .limit(5)
        .all()
    )
    return render_template(
        "patient/dashboard.html",
        patient=p,
        coach=coach,
        remaining_sessions=remaining,
        upcoming=upcoming,
    )


@bp.route("/contract")
@login_required
@patient_required
def contract():
    p = _patient_profile()
    cv = p.contracts[0] if p.contracts else None
    return render_template("patient/contract.html", patient=p, contract=cv)


@bp.route("/contract/download")
@login_required
@patient_required
def contract_download():
    p = _patient_profile()
    if not p.contracts:
        flash("Aucun contrat disponible.", "warning")
        return redirect(url_for("patient.contract"))
    cv = p.contracts[0]
    base = Path(current_app.config["UPLOAD_FOLDER"])
    path = base / cv.file_path
    if not path.is_file():
        abort(404)
    ext = path.suffix or ".pdf"
    return send_file(path, as_attachment=True, download_name=f"contrat-v{cv.version}{ext}")


@bp.route("/sessions")
@login_required
@patient_required
def sessions():
    p = _patient_profile()
    slots = (
        Slot.query.filter(
            Slot.patient_id == p.id,
            Slot.status.in_(("booked", "completed", "cancelled")),
        )
        .order_by(Slot.start_utc.desc())
        .all()
    )
    return render_template("patient/sessions.html", patient=p, slots=slots)


@bp.route("/book", methods=["GET", "POST"])
@login_required
@patient_required
def book():
    p = _patient_profile()
    coach = _coach_user()
    if not coach or not coach.settings:
        abort(500)
    s = coach.settings
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    available = (
        Slot.query.filter(
            Slot.coach_id == coach.id,
            Slot.status == "available",
            Slot.start_utc >= now_naive,
        )
        .order_by(Slot.start_utc.asc())
        .all()
    )
    # Filtrer créneaux qui respectent le délai min
    filtered = []
    for sl in available:
        ok, _ = can_book_after_min_days(p.id, sl.start_utc.replace(tzinfo=timezone.utc) if sl.start_utc.tzinfo is None else sl.start_utc, s.min_days_between_sessions or 0)
        if ok:
            filtered.append(sl)

    if request.method == "POST":
        sid = request.form.get("slot_id", type=int)
        slot = Slot.query.filter_by(id=sid, coach_id=coach.id, status="available").first()
        if not slot:
            flash("Ce créneau n’est plus disponible.", "danger")
            return redirect(url_for("patient.book"))
        ok, msg = can_book_after_min_days(
            p.id,
            slot.start_utc.replace(tzinfo=timezone.utc) if slot.start_utc.tzinfo is None else slot.start_utc,
            s.min_days_between_sessions or 0,
        )
        if not ok:
            flash(msg or "Réservation impossible.", "danger")
            return redirect(url_for("patient.book"))
        completed = Slot.query.filter_by(patient_id=p.id, status="completed").count()
        booked_future = (
            Slot.query.filter(
                Slot.patient_id == p.id,
                Slot.status == "booked",
                Slot.start_utc >= now_naive,
            )
            .count()
        )
        if completed + booked_future >= (p.sessions_planned or 0):
            flash("Vous avez atteint le nombre de séances prévues. Contactez votre coach.", "warning")
            return redirect(url_for("patient.book"))
        slot.patient_id = p.id
        slot.status = "booked"
        db.session.commit()
        slot_str = utc_naive_to_local_str(slot.start_utc, s.timezone)
        if s.email_notifications:
            send_booking_confirmation(p.user.email, p.display_name(), slot_str, coach.name)
            send_coach_new_booking(coach.email, p.display_name(), slot_str)
        flash("Rendez-vous réservé.", "success")
        return redirect(url_for("patient.dashboard"))

    last_end = last_session_end_utc(p.id)
    return render_template(
        "patient/book.html",
        patient=p,
        slots=filtered,
        coach_tz=s.timezone,
        min_days=s.min_days_between_sessions,
        last_session_end=last_end,
    )


@bp.route("/sessions/cancel/<int:sid>", methods=["POST"])
@login_required
@patient_required
def cancel_slot(sid):
    p = _patient_profile()
    coach = _coach_user()
    slot = Slot.query.filter_by(id=sid, patient_id=p.id, status="booked").first_or_404()
    s = coach.settings
    ok, msg = can_cancel_slot(slot, s.cancellation_hours or 0)
    if not ok:
        flash(msg or "Annulation refusée.", "danger")
        return redirect(url_for("patient.sessions"))
    slot.patient_id = None
    slot.status = "available"
    slot.cancelled_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash("Réservation annulée. Le créneau est à nouveau libre.", "info")
    return redirect(url_for("patient.sessions"))


@bp.route("/report-book.pdf")
@login_required
@patient_required
def report_book_pdf():
    p = _patient_profile()
    coach = _coach_user()
    slots = (
        Slot.query.filter(
            Slot.patient_id == p.id,
            Slot.status.in_(("booked", "completed")),
        )
        .order_by(Slot.start_utc.asc())
        .all()
    )
    sessions_data = []
    tz = coach.settings.timezone if coach and coach.settings else "Europe/Paris"
    for sl in slots:
        if sl.notes and sl.notes.strip():
            sessions_data.append(
                {
                    "date": utc_naive_to_local_str(sl.start_utc, tz),
                    "notes": sl.notes,
                    "paid": sl.paid,
                }
            )
    if not sessions_data:
        flash("Aucun compte rendu à inclure pour le moment.", "warning")
        return redirect(url_for("patient.sessions"))
    pdf = build_session_book_pdf(p.display_name(), coach.name, sessions_data)
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="livre-comptes-rendus.pdf",
    )
