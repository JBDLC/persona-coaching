from app import create_app
from app.bootstrap import ensure_default_admin, ensure_schema_updates
from app.extensions import db


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        ensure_schema_updates()
        ensure_default_admin()
    print("Initialization done.")


if __name__ == "__main__":
    main()
