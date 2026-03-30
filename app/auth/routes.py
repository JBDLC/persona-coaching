from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func, or_

from app import db
from app.auth import bp
from app.forms import CoachRegisterForm, LoginForm
from app.models import CoachSettings, User
from app.utils.decorators import redirect_if_logged


@bp.route("/login", methods=["GET", "POST"])
def login():
    redir = redirect_if_logged()
    if redir:
        return redir
    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.identifier.data.strip()
        identifier_l = identifier.lower()
        user = (
            User.query.filter(
                or_(
                    func.lower(User.email) == identifier_l,
                    func.lower(User.name) == identifier_l,
                )
            ).first()
        )
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash("Compte suspendu. Contactez votre administrateur.", "warning")
                return render_template("auth/login.html", form=form)
            login_user(user, remember=True)
            next_url = request.args.get("next")
            if user.must_change_password:
                return redirect(url_for("auth.change_password"))
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            if user.is_admin():
                return redirect(url_for("admin.dashboard"))
            if user.is_coach():
                return redirect(url_for("coach.dashboard"))
            return redirect(url_for("patient.dashboard"))
        flash("Identifiant ou mot de passe incorrect.", "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/logout")
def logout():
    logout_user()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("main.index"))


@bp.route("/register/coach", methods=["GET", "POST"])
def register_coach():
    if not current_user.is_authenticated or not current_user.is_admin():
        flash("Seul l'administrateur peut créer des comptes coach.", "warning")
        return redirect(url_for("auth.login"))
    form = CoachRegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter(func.lower(User.email) == email).first():
            flash("Cet email existe déjà.", "danger")
            return render_template("auth/register_coach.html", form=form)
        u = User(
            email=email,
            name=form.name.data.strip(),
            role="coach",
        )
        u.set_password(form.password.data)
        db.session.add(u)
        db.session.flush()
        cs = CoachSettings(user_id=u.id)
        db.session.add(cs)
        db.session.commit()
        flash("Compte coach créé par l'administrateur.", "success")
        return redirect(url_for("admin.dashboard"))
    return render_template("auth/register_coach.html", form=form)


@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    from flask_wtf import FlaskForm
    from wtforms import PasswordField, SubmitField
    from wtforms.validators import DataRequired, EqualTo

    class CP(FlaskForm):
        password = PasswordField("Nouveau mot de passe", validators=[DataRequired(), EqualTo("confirm", message="Les mots de passe doivent correspondre.")])
        confirm = PasswordField("Confirmer")
        submit = SubmitField("Enregistrer")

    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    form = CP()
    if form.validate_on_submit():
        current_user.set_password(form.password.data)
        current_user.must_change_password = False
        db.session.commit()
        flash("Mot de passe mis à jour.", "success")
        if current_user.is_coach():
            return redirect(url_for("coach.dashboard"))
        if current_user.is_admin():
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("patient.dashboard"))
    return render_template("auth/change_password.html", form=form)
