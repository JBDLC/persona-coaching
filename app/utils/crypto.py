import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_fernet() -> Fernet:
    configured = current_app.config.get("DATA_ENCRYPTION_KEY")
    if configured:
        key = configured.encode("utf-8")
    else:
        seed = (current_app.config.get("SECRET_KEY") or "persona-dev-key").encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_text(value: str) -> str:
    if not value:
        return value
    token = _get_fernet().encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(value: str | None) -> str | None:
    if not value:
        return value
    try:
        plain = _get_fernet().decrypt(value.encode("utf-8"))
        return plain.decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        # Backward compatibility for previously stored plaintext values.
        return value
