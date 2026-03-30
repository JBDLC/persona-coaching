from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import BooleanField, DecimalField, IntegerField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, NumberRange, Optional


class LoginForm(FlaskForm):
    identifier = StringField("Identifiant (email ou nom d'utilisateur)", validators=[DataRequired()])
    password = PasswordField("Mot de passe", validators=[DataRequired()])
    submit = SubmitField("Connexion")


class CoachRegisterForm(FlaskForm):
    name = StringField("Nom complet", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Mot de passe", validators=[DataRequired()])
    submit = SubmitField("Créer le compte coach")


class PatientCreateForm(FlaskForm):
    first_name = StringField("Prénom", validators=[DataRequired()])
    last_name = StringField("Nom", validators=[DataRequired()])
    email = StringField("Email (connexion)", validators=[DataRequired(), Email()])
    password = PasswordField("Mot de passe initial", validators=[DataRequired()])
    phone = StringField("Téléphone", validators=[Optional()])
    sessions_planned = IntegerField("Nombre de séances prévues", validators=[DataRequired(), NumberRange(min=1)])
    hourly_rate_override = DecimalField("Tarif horaire spécifique (vide = défaut coach)", validators=[Optional()])
    submit = SubmitField("Créer le patient")


class PatientEditForm(FlaskForm):
    first_name = StringField("Prénom", validators=[DataRequired()])
    last_name = StringField("Nom", validators=[DataRequired()])
    phone = StringField("Téléphone", validators=[Optional()])
    sessions_planned = IntegerField("Séances prévues", validators=[DataRequired(), NumberRange(min=1)])
    hourly_rate_override = DecimalField("Tarif horaire spécifique", validators=[Optional()])
    active = BooleanField("Fiche active")
    submit = SubmitField("Enregistrer")


class CoachSettingsForm(FlaskForm):
    default_hourly_rate = DecimalField("Tarif horaire par défaut (€)", validators=[DataRequired()])
    min_days_between_sessions = IntegerField("Jours minimum entre deux RDV", validators=[DataRequired(), NumberRange(min=0)])
    timezone = StringField("Fuseau horaire (ex. Europe/Paris)", validators=[DataRequired()])
    cancellation_hours = IntegerField("Délai minimum d'annulation (heures)", validators=[DataRequired(), NumberRange(min=0)])
    email_notifications = BooleanField("Notifications email (réservations)")
    tax_rate_percent = DecimalField("Impôts estimés (%)", validators=[DataRequired()])
    social_charges_percent = DecimalField("Charges sociales estimées (%)", validators=[DataRequired()])
    fixed_costs_monthly = DecimalField("Coûts fixes mensuels (€)", validators=[DataRequired()])
    target_net_salary_monthly = DecimalField("Objectif de salaire net mensuel (€)", validators=[DataRequired()])
    submit = SubmitField("Enregistrer les paramètres")


class SlotForm(FlaskForm):
    start_local = StringField("Début (date et heure locale)", validators=[DataRequired()])
    end_local = StringField("Fin (date et heure locale)", validators=[DataRequired()])
    submit = SubmitField("Ajouter le créneau")


class SessionNotesForm(FlaskForm):
    notes = TextAreaField("Compte rendu de séance", validators=[Optional()])
    paid = BooleanField("Séance payée")
    invoice_number = StringField("N° de facture (optionnel)", validators=[Optional()])
    mark_completed = BooleanField("Marquer comme complétée")
    submit = SubmitField("Enregistrer")


class ContractUploadForm(FlaskForm):
    title = StringField("Titre du contrat", validators=[DataRequired()])
    file = FileField("PDF ou document", validators=[FileRequired(), FileAllowed(["pdf", "doc", "docx", "png", "jpg", "jpeg"], "Formats autorisés")])
    submit = SubmitField("Téléverser")
