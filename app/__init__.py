from pathlib import Path

from flask import Flask, flash, redirect, request, url_for
from flask_login import current_user, logout_user

from config import Config
from app.extensions import csrf, db, login_manager, mail


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    upload = Path(app.config["UPLOAD_FOLDER"])
    upload.mkdir(parents=True, exist_ok=True)
    (upload / "contracts").mkdir(exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth import bp as auth_bp
    from app.admin import bp as admin_bp
    from app.coach import bp as coach_bp
    from app.main import bp as main_bp
    from app.patient import bp as patient_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(coach_bp, url_prefix="/coach")
    app.register_blueprint(patient_bp, url_prefix="/patient")

    @app.cli.command("init-db")
    def init_db():
        """Crée les tables (SQLite)."""
        db.create_all()
        print("Base initialisée.")

    from app.utils.datetime_parse import utc_naive_to_local_str

    @app.template_filter("local_dt")
    def local_dt_filter(dt, tz_name="Europe/Paris"):
        return utc_naive_to_local_str(dt, tz_name)

    @app.context_processor
    def coach_tz():
        tz = "Europe/Paris"
        if current_user.is_authenticated:
            if current_user.is_coach() and current_user.settings:
                tz = current_user.settings.timezone or tz
            elif current_user.is_patient() and current_user.coach_id:
                c = db.session.get(User, current_user.coach_id)
                if c and c.settings:
                    tz = c.settings.timezone or tz
        return {"coach_tz": tz}

    @app.before_request
    def force_logout_if_suspended():
        if current_user.is_authenticated and not current_user.is_active:
            if request.endpoint not in ("auth.login", "auth.logout"):
                logout_user()
                flash("Votre compte est suspendu.", "warning")
                return redirect(url_for("auth.login"))

    return app
