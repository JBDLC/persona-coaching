from app import create_app
from app.bootstrap import ensure_default_admin, ensure_schema_updates
from app.extensions import db

app = create_app()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_schema_updates()
        ensure_default_admin()
    app.run(debug=True, host="0.0.0.0", port=5000)
