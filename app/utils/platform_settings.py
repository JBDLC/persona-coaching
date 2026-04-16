from app import db
from app.models import PlatformSetting
from app.utils.crypto import decrypt_text, encrypt_text


def get_platform_setting(key: str, *, decrypt: bool = False, default=None):
    row = PlatformSetting.query.filter_by(key=key).first()
    if not row or not row.value:
        return default
    if decrypt:
        return decrypt_text(row.value)
    return row.value


def set_platform_setting(key: str, value: str | None, *, encrypt: bool = False):
    row = PlatformSetting.query.filter_by(key=key).first()
    if not row:
        row = PlatformSetting(key=key)
        db.session.add(row)
    clean_value = (value or "").strip()
    if not clean_value:
        return
    row.value = encrypt_text(clean_value) if encrypt else clean_value
