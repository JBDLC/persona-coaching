from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

if TYPE_CHECKING:
    pass


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin | coach | patient
    coach_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    is_suspended = db.Column(db.Boolean, default=False, nullable=False)
    legal_hold = db.Column(db.Boolean, default=False, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    coach = db.relationship("User", remote_side=[id], backref=db.backref("patients_users", lazy="dynamic"))
    settings = db.relationship("CoachSettings", back_populates="coach_user", uselist=False)
    patient_profile = db.relationship(
        "Patient",
        back_populates="user",
        uselist=False,
        foreign_keys="Patient.user_id",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_coach(self) -> bool:
        return self.role == "coach"

    def is_patient(self) -> bool:
        return self.role == "patient"

    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_active(self) -> bool:
        return not bool(self.is_suspended)


class CoachSettings(db.Model):
    __tablename__ = "coach_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    default_hourly_rate = db.Column(db.Numeric(10, 2), default=80)
    min_days_between_sessions = db.Column(db.Integer, default=7)
    timezone = db.Column(db.String(64), default="Europe/Paris")
    cancellation_hours = db.Column(db.Integer, default=24)
    email_notifications = db.Column(db.Boolean, default=True)
    notify_booking_patient = db.Column(db.Boolean, default=True)
    notify_booking_coach = db.Column(db.Boolean, default=True)
    notify_reminder_day_before = db.Column(db.Boolean, default=True)
    smtp_server = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer, default=587)
    smtp_use_tls = db.Column(db.Boolean, default=True)
    smtp_username = db.Column(db.String(255))
    smtp_password = db.Column(db.String(255))
    smtp_default_sender = db.Column(db.String(255))
    profile_image_path = db.Column(db.String(512))
    profile_bio = db.Column(db.Text)
    profile_youtube_url = db.Column(db.String(512))
    last_alert_seen_at = db.Column(db.DateTime)
    stripe_account_id = db.Column(db.String(64), index=True)
    stripe_onboarding_state = db.Column(db.String(24), default="not_connected")
    stripe_details_submitted = db.Column(db.Boolean, default=False)
    stripe_charges_enabled = db.Column(db.Boolean, default=False)
    stripe_payouts_enabled = db.Column(db.Boolean, default=False)
    stripe_last_synced_at = db.Column(db.DateTime)
    tax_rate_percent = db.Column(db.Numeric(5, 2), default=25)
    social_charges_percent = db.Column(db.Numeric(5, 2), default=22)
    fixed_costs_monthly = db.Column(db.Numeric(12, 2), default=500)
    target_net_salary_monthly = db.Column(db.Numeric(12, 2), default=3000)

    coach_user = db.relationship("User", back_populates="settings")


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    coach_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40))
    hourly_rate_override = db.Column(db.Numeric(10, 2))
    sessions_planned = db.Column(db.Integer, default=10)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    coach = db.relationship("User", foreign_keys=[coach_id], backref=db.backref("patient_records", lazy="dynamic"))
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="patient_profile",
    )
    contracts = db.relationship("ContractVersion", back_populates="patient", order_by="ContractVersion.version.desc()")
    slots = db.relationship("Slot", back_populates="patient", foreign_keys="Slot.patient_id")

    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def effective_hourly_rate(self, coach_default) -> float:
        if self.hourly_rate_override is not None:
            return float(self.hourly_rate_override)
        return float(coach_default)


class ContractVersion(db.Model):
    __tablename__ = "contract_versions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    uploaded_at = db.Column(db.DateTime, default=utcnow)

    patient = db.relationship("Patient", back_populates="contracts")


class Slot(db.Model):
    __tablename__ = "slots"

    id = db.Column(db.Integer, primary_key=True)
    coach_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=True, index=True)
    start_utc = db.Column(db.DateTime, nullable=False, index=True)
    end_utc = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default="available")  # available | booked | completed | cancelled
    notes = db.Column(db.Text)
    meeting_link = db.Column(db.String(512))
    paid = db.Column(db.Boolean, default=False)
    paid_at = db.Column(db.DateTime)
    invoice_number = db.Column(db.String(64))
    invoice_file_path = db.Column(db.String(512))
    invoice_uploaded_at = db.Column(db.DateTime)
    stripe_payment_intent_id = db.Column(db.String(128), index=True)
    stripe_checkout_session_id = db.Column(db.String(128), index=True)
    stripe_payment_status = db.Column(db.String(24), default="not_started")
    reminder_sent_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)

    coach = db.relationship("User", foreign_keys=[coach_id])
    patient = db.relationship("Patient", back_populates="slots", foreign_keys=[patient_id])

    def duration_hours(self) -> float:
        delta = self.end_utc - self.start_utc
        return max(0.0, delta.total_seconds() / 3600.0)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    coach_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(64), nullable=False)
    entity_type = db.Column(db.String(64))
    entity_id = db.Column(db.Integer)
    meta_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)

    coach = db.relationship("User", foreign_keys=[coach_id])


class GdprRequest(db.Model):
    __tablename__ = "gdpr_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    request_type = db.Column(db.String(32), nullable=False)  # access|rectification|erasure|portability|opposition|restriction
    status = db.Column(db.String(24), default="new", nullable=False)  # new|in_review|done|rejected
    notes = db.Column(db.Text)
    handled_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    handled_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship("User", foreign_keys=[user_id])
    handled_by = db.relationship("User", foreign_keys=[handled_by_user_id])


class SecurityIncident(db.Model):
    __tablename__ = "security_incidents"

    id = db.Column(db.Integer, primary_key=True)
    incident_type = db.Column(db.String(64), nullable=False)
    severity = db.Column(db.String(16), default="low", nullable=False)
    status = db.Column(db.String(24), default="open", nullable=False)  # open|investigating|closed
    description = db.Column(db.Text, nullable=False)
    related_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    closed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    closed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)

    related_user = db.relationship("User", foreign_keys=[related_user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    closed_by = db.relationship("User", foreign_keys=[closed_by_user_id])


class PaymentTransaction(db.Model):
    __tablename__ = "payment_transactions"

    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("slots.id"), nullable=False, index=True)
    coach_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    patient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    stripe_account_id = db.Column(db.String(64), nullable=False)
    stripe_checkout_session_id = db.Column(db.String(128), index=True)
    stripe_payment_intent_id = db.Column(db.String(128), index=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(8), default="eur", nullable=False)
    status = db.Column(db.String(24), default="pending", nullable=False)  # pending|succeeded|failed|canceled
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    slot = db.relationship("Slot", foreign_keys=[slot_id])


class PlatformSetting(db.Model):
    __tablename__ = "platform_settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


def audit_log(coach_id: int, actor_id: int | None, action: str, entity_type: str | None = None, entity_id: int | None = None, meta: dict | None = None):
    row = AuditLog(
        coach_id=coach_id,
        actor_user_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        meta_json=json.dumps(meta, ensure_ascii=False, default=str) if meta else None,
    )
    db.session.add(row)


def create_security_incident(
    incident_type: str,
    description: str,
    severity: str = "low",
    status: str = "open",
    related_user_id: int | None = None,
    created_by_user_id: int | None = None,
):
    row = SecurityIncident(
        incident_type=incident_type,
        description=description,
        severity=severity,
        status=status,
        related_user_id=related_user_id,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(row)
