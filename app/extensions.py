try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:
    Limiter = None
    get_remote_address = None
from flask_login import LoginManager
from flask_mail import Mail
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()


class _NoopLimiter:
    def init_app(self, app):
        return None

    def limit(self, _rule: str):
        def _decorator(fn):
            return fn

        return _decorator


if Limiter and get_remote_address:
    limiter = Limiter(key_func=get_remote_address, default_limits=[])
else:
    limiter = _NoopLimiter()

login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"
