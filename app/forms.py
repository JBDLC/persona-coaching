from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import BooleanField, DecimalField, IntegerField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional, URL


class LoginForm(FlaskForm):
    identifier = StringField("Identifiant (email ou nom d'utilisateur)", validators=[DataRequired()])
    password = PasswordField("Mot de passe", validators=[DataRequired()])
    submit = SubmitField("Connexion")


class CoachRegisterForm(FlaskForm):
    name = StringField("Nom complet", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Mot de passe", validators=[DataRequired()])
    submit = SubmitField("Créer le compte coach")


class ResetCoachPasswordForm(FlaskForm):
    password = PasswordField("Nouveau mot de passe temporaire", validators=[DataRequired(), Length(min=8)])
    submit = SubmitField("Réinitialiser MDP")


class ResetPatientPasswordForm(FlaskForm):
    password = PasswordField("Nouveau mot de passe temporaire", validators=[DataRequired(), Length(min=8)])
    submit = SubmitField("Réinitialiser le mot de passe")


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
    notify_booking_patient = BooleanField("Envoyer un mail de confirmation au patient lors d'une réservation")
    notify_booking_coach = BooleanField("M'envoyer un mail lorsqu'un patient réserve un créneau")
    notify_reminder_day_before = BooleanField("Envoyer un rappel au patient la veille du rendez-vous")
    smtp_server = StringField("Serveur SMTP", validators=[Optional()])
    smtp_port = IntegerField("Port SMTP", validators=[Optional(), NumberRange(min=1, max=65535)])
    smtp_use_tls = BooleanField("Activer TLS (STARTTLS)")
    smtp_username = StringField("Utilisateur SMTP", validators=[Optional()])
    smtp_password = PasswordField("Mot de passe SMTP", validators=[Optional()])
    smtp_default_sender = StringField("Expéditeur par défaut (email)", validators=[Optional(), Email()])
    profile_photo = FileField("Photo du coach", validators=[Optional(), FileAllowed(["png", "jpg", "jpeg", "webp"], "Image uniquement")])
    profile_bio = TextAreaField("Présentation du coach", validators=[Optional()])
    profile_youtube_url = StringField("Lien YouTube", validators=[Optional(), URL()])
    tax_rate_percent = DecimalField("Impôts estimés (%)", validators=[DataRequired()])
    social_charges_percent = DecimalField("Charges sociales estimées (%)", validators=[DataRequired()])
    fixed_costs_monthly = DecimalField("Coûts fixes mensuels (€)", validators=[DataRequired()])
    target_net_salary_monthly = DecimalField("Objectif de salaire net mensuel (€)", validators=[DataRequired()])
    submit = SubmitField("Enregistrer les paramètres")


class SlotForm(FlaskForm):
    start_local = StringField("Début (date et heure locale)", validators=[DataRequired()])
    submit = SubmitField("Ajouter un créneau d'1h")


class SessionNotesForm(FlaskForm):
    notes = TextAreaField("Compte rendu de séance", validators=[Optional()])
    meeting_link = StringField("Lien de séance (Meet, Zoom...)", validators=[Optional(), URL()])
    paid = BooleanField("Séance payée")
    invoice_number = StringField("N° de facture (optionnel)", validators=[Optional()])
    mark_completed = BooleanField("Marquer comme complétée")
    submit = SubmitField("Enregistrer")


class ContractUploadForm(FlaskForm):
    title = StringField("Titre du contrat", validators=[DataRequired()])
    file = FileField("PDF ou document", validators=[FileRequired(), FileAllowed(["pdf", "doc", "docx", "png", "jpg", "jpeg"], "Formats autorisés")])
    submit = SubmitField("Téléverser")


class SessionInvoiceUploadForm(FlaskForm):
    file = FileField("Facture (PDF ou image)", validators=[FileRequired(), FileAllowed(["pdf", "png", "jpg", "jpeg"], "Formats autorisés")])
    submit = SubmitField("Enregistrer la facture")


class GdprRequestForm(FlaskForm):
    user_email = StringField("Email utilisateur concerné", validators=[DataRequired(), Email()])
    request_type = StringField("Type (access|rectification|erasure|portability|opposition|restriction)", validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Créer la demande RGPD")


class SecurityIncidentForm(FlaskForm):
    incident_type = StringField("Type d'incident", validators=[DataRequired()])
    severity = StringField("Sévérité (low|medium|high|critical)", validators=[DataRequired()])
    description = TextAreaField("Description", validators=[DataRequired()])
    related_user_email = StringField("Email utilisateur concerné (optionnel)", validators=[Optional(), Email()])
    submit = SubmitField("Déclarer l'incident")


class PlatformStripeSettingsForm(FlaskForm):
    stripe_secret_key = PasswordField("Stripe Secret Key (sk_...)", validators=[Optional()])
    stripe_publishable_key = StringField("Stripe Publishable Key (pk_...)", validators=[Optional()])
    stripe_webhook_secret = PasswordField("Stripe Webhook Secret (whsec_...)", validators=[Optional()])
    stripe_connect_refresh_url = StringField("URL refresh onboarding", validators=[Optional(), URL()])
    stripe_connect_return_url = StringField("URL return onboarding", validators=[Optional(), URL()])
    submit = SubmitField("Enregistrer la configuration Stripe")


class PlatformSmtpSettingsForm(FlaskForm):
    mail_server = StringField("Serveur SMTP global", validators=[Optional()])
    mail_port = IntegerField("Port SMTP global", validators=[Optional(), NumberRange(min=1, max=65535)])
    mail_use_tls = BooleanField("Activer TLS (STARTTLS)")
    mail_username = StringField("Utilisateur SMTP global", validators=[Optional()])
    mail_password = PasswordField("Mot de passe SMTP global", validators=[Optional()])
    mail_default_sender = StringField("Expéditeur global (email)", validators=[Optional(), Email()])
    submit = SubmitField("Enregistrer la configuration SMTP globale")
