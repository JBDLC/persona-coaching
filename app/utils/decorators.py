from functools import wraps

from flask import abort, redirect, url_for
from flask_login import current_user


def coach_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_coach():
            abort(403)
        return f(*args, **kwargs)

    return decorated


def patient_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_patient():
            abort(403)
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)

    return decorated


def redirect_if_logged():
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for("admin.dashboard"))
        if current_user.is_coach():
            return redirect(url_for("coach.patients_list"))
        return redirect(url_for("patient.dashboard"))
    return None
