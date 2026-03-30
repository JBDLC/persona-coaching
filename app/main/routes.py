from flask import render_template, redirect, url_for
from flask_login import current_user

from app.main import bp


@bp.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for("admin.dashboard"))
        if current_user.is_coach():
            return redirect(url_for("coach.dashboard"))
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
