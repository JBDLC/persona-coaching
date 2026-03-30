from flask import Blueprint

bp = Blueprint("coach", __name__)

from app.coach import routes  # noqa: E402, F401
