import os

from app.extensions import db
from app.models import User
from sqlalchemy import inspect, text


def ensure_schema_updates():
    """
    Ajoute les colonnes nécessaires si la base existante est ancienne.
    """
    inspector = inspect(db.engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "is_suspended" not in cols:
        db.session.execute(text("ALTER TABLE users ADD COLUMN is_suspended BOOLEAN DEFAULT FALSE"))
        db.session.commit()
    if "legal_hold" not in cols:
        db.session.execute(text("ALTER TABLE users ADD COLUMN legal_hold BOOLEAN DEFAULT FALSE"))
        db.session.commit()

    slots_cols = {c["name"] for c in inspector.get_columns("slots")}
    if "paid_at" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN paid_at DATETIME"))
        db.session.commit()
    if "stripe_payment_intent_id" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN stripe_payment_intent_id VARCHAR(128)"))
        db.session.commit()
    if "stripe_checkout_session_id" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN stripe_checkout_session_id VARCHAR(128)"))
        db.session.commit()
    if "stripe_payment_status" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN stripe_payment_status VARCHAR(24) DEFAULT 'not_started'"))
        db.session.commit()
    if "meeting_link" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN meeting_link VARCHAR(512)"))
        db.session.commit()
    if "meeting_provider" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN meeting_provider VARCHAR(32)"))
        db.session.commit()
    if "meeting_event_id" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN meeting_event_id VARCHAR(255)"))
        db.session.commit()
    if "invoice_file_path" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN invoice_file_path VARCHAR(512)"))
        db.session.commit()
    if "invoice_uploaded_at" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN invoice_uploaded_at DATETIME"))
        db.session.commit()
    if "reminder_sent_at" not in slots_cols:
        db.session.execute(text("ALTER TABLE slots ADD COLUMN reminder_sent_at DATETIME"))
        db.session.commit()

    coach_settings_cols = {c["name"] for c in inspector.get_columns("coach_settings")}
    alter_statements = []
    if "notify_booking_patient" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN notify_booking_patient BOOLEAN DEFAULT TRUE")
    if "notify_booking_coach" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN notify_booking_coach BOOLEAN DEFAULT TRUE")
    if "notify_reminder_day_before" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN notify_reminder_day_before BOOLEAN DEFAULT TRUE")
    if "smtp_server" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN smtp_server VARCHAR(255)")
    if "smtp_port" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN smtp_port INTEGER DEFAULT 587")
    if "smtp_use_tls" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN smtp_use_tls BOOLEAN DEFAULT TRUE")
    if "smtp_username" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN smtp_username VARCHAR(255)")
    if "smtp_password" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN smtp_password VARCHAR(255)")
    if "smtp_default_sender" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN smtp_default_sender VARCHAR(255)")
    if "profile_image_path" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN profile_image_path VARCHAR(512)")
    if "profile_bio" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN profile_bio TEXT")
    if "profile_youtube_url" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN profile_youtube_url VARCHAR(512)")
    if "last_alert_seen_at" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN last_alert_seen_at DATETIME")
    if "stripe_account_id" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN stripe_account_id VARCHAR(64)")
    if "stripe_onboarding_state" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN stripe_onboarding_state VARCHAR(24) DEFAULT 'not_connected'")
    if "stripe_details_submitted" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN stripe_details_submitted BOOLEAN DEFAULT FALSE")
    if "stripe_charges_enabled" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN stripe_charges_enabled BOOLEAN DEFAULT FALSE")
    if "stripe_payouts_enabled" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN stripe_payouts_enabled BOOLEAN DEFAULT FALSE")
    if "stripe_last_synced_at" not in coach_settings_cols:
        alter_statements.append("ALTER TABLE coach_settings ADD COLUMN stripe_last_synced_at DATETIME")
    if alter_statements:
        for stmt in alter_statements:
            db.session.execute(text(stmt))
        db.session.commit()

    # Create new compliance tables if missing.
    existing_tables = set(inspector.get_table_names())
    if "gdpr_requests" not in existing_tables:
        db.session.execute(
            text(
                """
                CREATE TABLE gdpr_requests (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    request_type VARCHAR(32) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'new',
                    notes TEXT,
                    handled_by_user_id INTEGER,
                    handled_at DATETIME,
                    created_at DATETIME
                )
                """
            )
        )
        db.session.commit()
    if "security_incidents" not in existing_tables:
        db.session.execute(
            text(
                """
                CREATE TABLE security_incidents (
                    id INTEGER PRIMARY KEY,
                    incident_type VARCHAR(64) NOT NULL,
                    severity VARCHAR(16) NOT NULL DEFAULT 'low',
                    status VARCHAR(24) NOT NULL DEFAULT 'open',
                    description TEXT NOT NULL,
                    related_user_id INTEGER,
                    created_by_user_id INTEGER,
                    closed_by_user_id INTEGER,
                    closed_at DATETIME,
                    created_at DATETIME
                )
                """
            )
        )
        db.session.commit()
    if "payment_transactions" not in existing_tables:
        db.session.execute(
            text(
                """
                CREATE TABLE payment_transactions (
                    id INTEGER PRIMARY KEY,
                    slot_id INTEGER NOT NULL,
                    coach_id INTEGER NOT NULL,
                    patient_user_id INTEGER NOT NULL,
                    stripe_account_id VARCHAR(64) NOT NULL,
                    stripe_checkout_session_id VARCHAR(128),
                    stripe_payment_intent_id VARCHAR(128),
                    amount_cents INTEGER NOT NULL,
                    currency VARCHAR(8) NOT NULL DEFAULT 'eur',
                    status VARCHAR(24) NOT NULL DEFAULT 'pending',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        db.session.commit()
    if "platform_settings" not in existing_tables:
        db.session.execute(
            text(
                """
                CREATE TABLE platform_settings (
                    key VARCHAR(80) PRIMARY KEY,
                    value TEXT,
                    updated_at DATETIME
                )
                """
            )
        )
        db.session.commit()


def ensure_default_admin():
    """
    Crée le compte admin demandé si absent.
    Identifiant de connexion: adminpersona (via champ identifiant)
    """
    admin_username = os.environ.get("ADMIN_USERNAME", "adminpersona")
    admin_email = os.environ.get("ADMIN_EMAIL", "adminpersona@persona.local")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Speedriding@69")

    existing = User.query.filter_by(name=admin_username, role="admin").first()
    if existing:
        return
    admin = User(
        email=admin_email,
        name=admin_username,
        role="admin",
        is_suspended=False,
    )
    admin.set_password(admin_password)
    db.session.add(admin)
    db.session.commit()
