from datetime import datetime, timezone

from flask import current_app, render_template, redirect, request, url_for
from flask_login import current_user

from app import db
from app.extensions import csrf
from app.main import bp
from app.models import CoachSettings, Patient, PatientPack, PaymentTransaction, Slot, User, audit_log
from app.utils.platform_settings import get_platform_setting
from app.utils.stripe_connect import _require_stripe, _stripe_field, sync_account_state


@bp.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for("admin.dashboard"))
        if current_user.is_coach():
            return redirect(url_for("coach.patients_list"))
        return redirect(url_for("patient.dashboard"))
    return render_template("main/index.html")


@bp.route("/privacy")
def privacy():
    return render_template("main/privacy.html")


@bp.route("/terms")
def terms():
    return render_template("main/terms.html")


@bp.route("/help")
def help_page():
    return render_template("main/help.html")


@bp.route("/stripe/webhook", methods=["POST"])
@csrf.exempt
def stripe_webhook():
    try:
        sdk = _require_stripe()
    except Exception as exc:
        return {"error": str(exc)}, 500

    sig_header = request.headers.get("Stripe-Signature")
    payload = request.get_data(as_text=True)
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET") or get_platform_setting("stripe_webhook_secret", decrypt=True)
    if not secret:
        return {"error": "STRIPE_WEBHOOK_SECRET manquant"}, 500
    try:
        event = sdk.Webhook.construct_event(payload, sig_header, secret)
    except Exception:
        return {"error": "Invalid signature"}, 400

    event_type = _stripe_field(event, "type")
    data_obj = _stripe_field(_stripe_field(event, "data", {}), "object", {})
    connected_account = _stripe_field(event, "account")

    if event_type == "account.updated":
        acc_id = _stripe_field(data_obj, "id")
        settings = CoachSettings.query.filter_by(stripe_account_id=acc_id).first()
        if settings:
            try:
                sync_account_state(settings)
                db.session.commit()
            except Exception:
                current_app.logger.exception("Stripe account sync failure")

    if event_type in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        pi_id = _stripe_field(data_obj, "id")
        metadata = _stripe_field(data_obj, "metadata", {}) or {}
        slot_id = metadata.get("slot_id")
        if slot_id:
            slot = Slot.query.filter_by(id=int(slot_id)).first()
            if slot:
                previous_status = slot.stripe_payment_status
                slot.stripe_payment_intent_id = pi_id
                slot.stripe_payment_status = "succeeded" if event_type == "payment_intent.succeeded" else "failed"
                if event_type == "payment_intent.succeeded":
                    slot.paid = True
                    slot.paid_source = "session"
                    if not slot.paid_at:
                        slot.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
                tx = PaymentTransaction.query.filter_by(stripe_payment_intent_id=pi_id).first()
                if not tx and connected_account:
                    tx = PaymentTransaction.query.filter_by(
                        slot_id=slot.id,
                        stripe_account_id=connected_account,
                        status="pending",
                    ).order_by(PaymentTransaction.id.desc()).first()
                if tx:
                    tx.status = "succeeded" if event_type == "payment_intent.succeeded" else "failed"
                    tx.stripe_payment_intent_id = pi_id
                if event_type == "payment_intent.succeeded" and previous_status != "succeeded":
                    audit_log(
                        slot.coach_id,
                        slot.patient.user_id if slot.patient and slot.patient.user else None,
                        "payment_succeeded",
                        "Slot",
                        slot.id,
                        {"patient_name": slot.patient.display_name() if slot.patient else None},
                    )
                if event_type == "payment_intent.payment_failed" and previous_status != "failed":
                    audit_log(
                        slot.coach_id,
                        slot.patient.user_id if slot.patient and slot.patient.user else None,
                        "payment_failed",
                        "Slot",
                        slot.id,
                        {"patient_name": slot.patient.display_name() if slot.patient else None},
                    )
                db.session.commit()

    if event_type == "checkout.session.completed":
        session_id = _stripe_field(data_obj, "id")
        tx = PaymentTransaction.query.filter_by(stripe_checkout_session_id=session_id).first()
        if tx:
            tx.status = "succeeded"
            payment_intent = _stripe_field(data_obj, "payment_intent")
            if payment_intent:
                tx.stripe_payment_intent_id = payment_intent
            slot = Slot.query.filter_by(id=tx.slot_id).first()
            if slot:
                slot.paid = True
                slot.paid_source = "session"
                if not slot.paid_at:
                    slot.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
                slot.stripe_payment_status = "succeeded"
                slot.stripe_checkout_session_id = session_id
                slot.stripe_payment_intent_id = payment_intent
        else:
            metadata = _stripe_field(data_obj, "metadata", {}) or {}
            if metadata.get("payment_type") == "pack":
                coach_pack_id = metadata.get("coach_pack_id")
                patient_user_id = metadata.get("patient_user_id")
                patient = None
                if patient_user_id:
                    user = User.query.filter_by(id=int(patient_user_id), role="patient").first()
                    patient = user.patient_profile if user else None
                purchase = None
                if patient and coach_pack_id:
                    purchase = (
                        PatientPack.query.filter_by(
                            patient_id=patient.id,
                            coach_pack_id=int(coach_pack_id),
                            stripe_checkout_session_id=session_id,
                        )
                        .order_by(PatientPack.id.desc())
                        .first()
                    )
                if purchase:
                    purchase.purchase_status = "succeeded"
                    payment_intent = _stripe_field(data_obj, "payment_intent")
                    if payment_intent:
                        purchase.stripe_payment_intent_id = payment_intent
                    purchase.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    audit_log(
                        purchase.coach_id,
                        patient.user_id if patient and patient.user_id else None,
                        "pack_purchased",
                        "PatientPack",
                        purchase.id,
                        {"patient_name": patient.display_name() if patient else None},
                    )
            db.session.commit()

    return {"received": True}, 200
