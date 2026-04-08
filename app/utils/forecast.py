from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models import CoachSettings, Patient, Slot, User


def utcnow():
    return datetime.now(timezone.utc)


def scheduled_revenue_coach(coach_id: int) -> Decimal:
    """CA des séances futures déjà planifiées mais pas encore payées (reste à encaisser)."""
    now = utcnow()
    q = (
        db.session.query(Slot, Patient)
        .join(Patient, Slot.patient_id == Patient.id)
        .filter(
            Slot.coach_id == coach_id,
            Slot.status.in_(("booked", "completed")),
            Slot.start_utc >= now,
            Slot.paid.is_(False),
        )
    )
    coach = db.session.get(User, coach_id)
    settings = coach.settings if coach else None
    default_rate = float(settings.default_hourly_rate) if settings else 0.0

    total = Decimal("0")
    for slot, patient in q:
        rate = patient.effective_hourly_rate(default_rate)
        total += Decimal(str(slot.duration_hours() * rate))
    return total.quantize(Decimal("0.01"))


def pipeline_revenue_coach(coach_id: int) -> Decimal:
    """CA potentiel restant à encaisser : (séances prévues - séances payées) × tarif horaire."""
    coach = db.session.get(User, coach_id)
    if not coach or not coach.settings:
        return Decimal("0")
    default_rate = float(coach.settings.default_hourly_rate)
    patients = Patient.query.filter_by(coach_id=coach_id, active=True).all()
    total = Decimal("0")
    for p in patients:
        paid_count = (
            Slot.query.filter(
                Slot.patient_id == p.id,
                Slot.status.in_(("booked", "completed")),
                Slot.paid.is_(True),
            )
            .with_entities(func.count())
            .scalar()
        )
        remaining = max(0, (p.sessions_planned or 0) - int(paid_count or 0))
        rate = p.effective_hourly_rate(default_rate)
        total += Decimal(str(remaining * rate))
    return total.quantize(Decimal("0.01"))


def collected_revenue_coach(coach_id: int) -> Decimal:
    """Fonds réellement encaissés : toutes les séances payées (Stripe ou manuel)."""
    q = (
        db.session.query(Slot, Patient)
        .join(Patient, Slot.patient_id == Patient.id)
        .filter(
            Slot.coach_id == coach_id,
            Slot.status.in_(("booked", "completed")),
            Slot.paid.is_(True),
        )
    )
    coach = db.session.get(User, coach_id)
    settings = coach.settings if coach else None
    default_rate = float(settings.default_hourly_rate) if settings else 0.0
    total = Decimal("0")
    for slot, patient in q:
        rate = patient.effective_hourly_rate(default_rate)
        total += Decimal(str(slot.duration_hours() * rate))
    return total.quantize(Decimal("0.01"))


def net_after_charges_monthly(coach_id: int) -> dict:
    s = CoachSettings.query.filter_by(user_id=coach_id).first()
    if not s:
        return {}
    gross_scheduled = scheduled_revenue_coach(coach_id)
    gross_pipeline = pipeline_revenue_coach(coach_id)
    tax = float(s.tax_rate_percent or 0) / 100.0
    soc = float(s.social_charges_percent or 0) / 100.0
    fixed = Decimal(str(s.fixed_costs_monthly or 0))

    def net_from_gross(g: Decimal) -> Decimal:
        after = g * (Decimal("1") - Decimal(str(tax + soc)))
        return (after - fixed).quantize(Decimal("0.01"))

    target = Decimal(str(s.target_net_salary_monthly or 0))
    return {
        "gross_scheduled": gross_scheduled,
        "gross_pipeline": gross_pipeline,
        "net_estimated_from_scheduled": net_from_gross(gross_scheduled),
        "net_estimated_from_pipeline": net_from_gross(gross_pipeline),
        "target_net_salary": target,
        "tax_rate": s.tax_rate_percent,
        "social_rate": s.social_charges_percent,
        "fixed_costs": fixed,
    }
