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
