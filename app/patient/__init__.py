from flask import Blueprint

bp = Blueprint("patient", __name__)

from app.patient import routes  # noqa: E402, F401
