import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-change-me-in-production"
    _db_url = os.environ.get("DATABASE_URL")
    if _db_url and _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url or f"sqlite:///{BASE_DIR / 'coach_app.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = BASE_DIR / "app" / "static" / "uploads"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 Mo
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or 587)
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
    STRIPE_CONNECT_REFRESH_URL = os.environ.get("STRIPE_CONNECT_REFRESH_URL")
    STRIPE_CONNECT_RETURN_URL = os.environ.get("STRIPE_CONNECT_RETURN_URL")
    # Reversible encryption key for sensitive values (Fernet urlsafe base64 key).
    # If missing, a deterministic key is derived from SECRET_KEY.
    DATA_ENCRYPTION_KEY = os.environ.get("DATA_ENCRYPTION_KEY")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.environ.get("SESSION_DAYS", "7")))
    GDPR_AUDIT_RETENTION_DAYS = int(os.environ.get("GDPR_AUDIT_RETENTION_DAYS", "730"))
    GDPR_SECURITY_INCIDENT_RETENTION_DAYS = int(os.environ.get("GDPR_SECURITY_INCIDENT_RETENTION_DAYS", "1825"))
    GDPR_INACTIVE_USER_RETENTION_DAYS = int(os.environ.get("GDPR_INACTIVE_USER_RETENTION_DAYS", "1095"))
