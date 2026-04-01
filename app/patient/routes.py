from datetime import datetime, timezone
from pathlib import Path

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.models import ContractVersion, PaymentTransaction, Patient, Slot, audit_log
from app.patient import bp
from app.utils.booking import can_book_after_min_days, can_cancel_slot, last_session_end_utc
from app.utils.datetime_parse import utc_naive_to_local_str
from app.utils.decorators import patient_required
from app.utils.email import send_booking_confirmation, send_coach_new_booking
from app.utils.pdf import build_session_book_pdf
from app.utils.stripe_connect import _require_stripe, _stripe_field, create_direct_checkout_session


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


def _sync_pending_payments_for_patient(patient: Patient):
    pending = (
        PaymentTransaction.query.filter_by(patient_user_id=current_user.id, status="pending")
        .order_by(PaymentTransaction.id.desc())
        .limit(5)
        .all()
    )
    if not pending:
        return 0
    try:
        sdk = _require_stripe()
    except Exception:
        return 0
    synced = 0
    for tx in pending:
        if not tx.stripe_checkout_session_id:
            continue
        try:
            cs = sdk.checkout.Session.retrieve(
                tx.stripe_checkout_session_id,
                stripe_account=tx.stripe_account_id,
            )
        except Exception:
            continue
        payment_status = _stripe_field(cs, "payment_status")
        checkout_status = _stripe_field(cs, "status")
        if payment_status == "paid" or checkout_status == "complete":
            slot = Slot.query.filter_by(id=tx.slot_id).first()
            if slot:
                if slot.stripe_payment_status != "succeeded":
                    audit_log(
                        slot.coach_id,
                        current_user.id,
                        "payment_succeeded",
                        "Slot",
                        slot.id,
                        {"patient_name": patient.display_name()},
                    )
                slot.paid = True
                if not slot.paid_at:
                    slot.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
                slot.stripe_payment_status = "succeeded"
                slot.stripe_checkout_session_id = tx.stripe_checkout_session_id
                slot.stripe_payment_intent_id = _stripe_field(cs, "payment_intent")
            tx.status = "succeeded"
            tx.stripe_payment_intent_id = _stripe_field(cs, "payment_intent")
            synced += 1
        elif checkout_status == "expired":
            tx.status = "failed"
    if synced:
        db.session.commit()
    return synced


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
        coach_settings=coach.settings if coach else None,
        remaining_sessions=remaining,
        upcoming=upcoming,
    )


@bp.route("/coach-presentation")
@login_required
@patient_required
def coach_presentation():
    coach = _coach_user()
    if not coach or not coach.settings:
        abort(404)
    return render_template("patient/coach_presentation.html", coach=coach, settings=coach.settings)


@bp.route("/contract")
@login_required
@patient_required
def contract():
    p = _patient_profile()
    return render_template("patient/contract.html", patient=p, contracts=p.contracts)


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


@bp.route("/contract/<int:cid>/download")
@login_required
@patient_required
def contract_download_one(cid):
    p = _patient_profile()
    cv = ContractVersion.query.filter_by(id=cid, patient_id=p.id).first_or_404()
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
    payment_query = request.args.get("payment")
    if payment_query == "success":
        synced = _sync_pending_payments_for_patient(p)
        if synced:
            flash("Paiement confirmé. La séance est marquée comme payée.", "success")
        else:
            flash("Paiement en cours de confirmation. Rafraîchissez dans quelques secondes.", "info")
    elif payment_query == "cancel":
        flash("Paiement annulé.", "warning")
    slots = (
        Slot.query.filter(
            Slot.patient_id == p.id,
            Slot.status.in_(("booked", "completed", "cancelled")),
        )
        .order_by(Slot.start_utc.desc())
        .all()
    )
    return render_template("patient/sessions.html", patient=p, slots=slots)


@bp.route("/sessions/<int:sid>/invoice/download")
@login_required
@patient_required
def session_invoice_download(sid):
    p = _patient_profile()
    slot = Slot.query.filter_by(id=sid, patient_id=p.id).first_or_404()
    if not slot.invoice_file_path:
        flash("Aucune facture disponible pour cette séance.", "warning")
        return redirect(url_for("patient.sessions"))
    path = Path(current_app.config["UPLOAD_FOLDER"]) / slot.invoice_file_path
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


@bp.route("/payments/session/<int:sid>/checkout", methods=["POST"])
@login_required
@patient_required
def payment_checkout_session(sid):
    p = _patient_profile()
    coach = _coach_user()
    if not coach or not coach.settings:
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "Coach introuvable."}), 400
        flash("Coach introuvable.", "danger")
        return redirect(url_for("patient.sessions"))
    settings = coach.settings
    if not settings.stripe_account_id or not settings.stripe_charges_enabled:
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "Le coach n'est pas prêt à encaisser en ligne."}), 400
        flash("Le coach n'est pas prêt à encaisser en ligne.", "warning")
        return redirect(url_for("patient.sessions"))

    slot = Slot.query.filter_by(id=sid, patient_id=p.id).first_or_404()
    if slot.paid:
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "Cette séance est déjà payée."}), 400
        flash("Cette séance est déjà payée.", "info")
        return redirect(url_for("patient.sessions"))

    rate = p.effective_hourly_rate(float(settings.default_hourly_rate))
    amount_cents = int(round(slot.duration_hours() * rate * 100))
    if amount_cents <= 0:
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "Montant invalide pour cette séance."}), 400
        flash("Montant invalide pour cette séance.", "danger")
        return redirect(url_for("patient.sessions"))

    success_url = url_for("patient.sessions", _external=True) + "?payment=success"
    cancel_url = url_for("patient.sessions", _external=True) + "?payment=cancel"
    metadata = {
        "slot_id": str(slot.id),
        "coach_id": str(coach.id),
        "patient_user_id": str(current_user.id),
    }
    try:
        session = create_direct_checkout_session(
            stripe_account_id=settings.stripe_account_id,
            amount_cents=amount_cents,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )
    except Exception as exc:
        current_app.logger.exception("Stripe checkout creation failed")
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": str(exc)}), 500
        flash(f"Impossible d'initier le paiement: {exc}", "danger")
        return redirect(url_for("patient.sessions"))

    tx = PaymentTransaction(
        slot_id=slot.id,
        coach_id=coach.id,
        patient_user_id=current_user.id,
        stripe_account_id=settings.stripe_account_id,
        stripe_checkout_session_id=_stripe_field(session, "id"),
        stripe_payment_intent_id=_stripe_field(session, "payment_intent"),
        amount_cents=amount_cents,
        currency="eur",
        status="pending",
    )
    slot.stripe_checkout_session_id = _stripe_field(session, "id")
    slot.stripe_payment_intent_id = _stripe_field(session, "payment_intent")
    slot.stripe_payment_status = "pending"
    db.session.add(tx)
    db.session.commit()
    if request.accept_mimetypes.best != "application/json":
        return redirect(_stripe_field(session, "url"))
    return jsonify({"checkout_url": _stripe_field(session, "url")})


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
        audit_log(
            coach.id,
            current_user.id,
            "patient_booking_created",
            "Slot",
            slot.id,
            {"patient_id": p.id, "patient_name": p.display_name()},
        )
        db.session.commit()
        slot_str = utc_naive_to_local_str(slot.start_utc, s.timezone)
        if s.email_notifications:
            if s.notify_booking_patient:
                send_booking_confirmation(p.user.email, p.display_name(), slot_str, coach.name, coach_settings=s)
            if s.notify_booking_coach:
                send_coach_new_booking(coach.email, p.display_name(), slot_str, coach_settings=s)
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
    audit_log(
        coach.id,
        current_user.id,
        "patient_booking_cancelled",
        "Slot",
        slot.id,
        {"patient_id": p.id, "patient_name": p.display_name()},
    )
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
