"""Règles de réservation (délai minimum entre séances, annulation)."""

from datetime import datetime, timedelta, timezone

from app.models import Slot


def utcnow():
    return datetime.now(timezone.utc)


def last_session_end_utc(patient_id: int) -> datetime | None:
    """Dernière fin de séance (réservée ou complétée, non annulée)."""
    slot = (
        Slot.query.filter(
            Slot.patient_id == patient_id,
            Slot.status.in_(("booked", "completed")),
        )
        .order_by(Slot.end_utc.desc())
        .first()
    )
    return slot.end_utc if slot else None


def can_book_after_min_days(patient_id: int, new_start_utc: datetime, min_days: int) -> tuple[bool, str | None]:
    if min_days <= 0:
        return True, None
    last_end = last_session_end_utc(patient_id)
    if last_end is None:
        return True, None
    if last_end.tzinfo is None:
        last_end = last_end.replace(tzinfo=timezone.utc)
    if new_start_utc.tzinfo is None:
        new_start_utc = new_start_utc.replace(tzinfo=timezone.utc)
    delta = new_start_utc - last_end
    if delta < timedelta(days=min_days):
        return False, f"Un délai minimum de {min_days} jour(s) est requis entre deux séances."
    return True, None


def can_cancel_slot(slot, cancellation_hours: int) -> tuple[bool, str | None]:
    if cancellation_hours <= 0:
        return True, None
    start = slot.start_utc
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    deadline = start - timedelta(hours=cancellation_hours)
    if utcnow() > deadline:
        return False, f"Annulation impossible : moins de {cancellation_hours} h avant le créneau."
    return True, None
