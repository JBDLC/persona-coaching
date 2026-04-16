from datetime import datetime, timezone

from flask import current_app, url_for

from app.extensions import db
from app.models import CoachSettings
from app.utils.platform_settings import get_platform_setting

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None


def _require_stripe():
    if stripe is None:
        raise RuntimeError("Le package 'stripe' est requis. Installez-le avec pip install -r requirements.txt")
    secret = current_app.config.get("STRIPE_SECRET_KEY") or get_platform_setting("stripe_secret_key", decrypt=True)
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY manquant dans la configuration.")
    stripe.api_key = secret
    return stripe


def _stripe_field(obj, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except Exception:
        pass
    try:
        return getattr(obj, key)
    except Exception:
        return default


def _connect_urls():
    refresh_url = current_app.config.get("STRIPE_CONNECT_REFRESH_URL") or get_platform_setting("stripe_connect_refresh_url")
    return_url = current_app.config.get("STRIPE_CONNECT_RETURN_URL") or get_platform_setting("stripe_connect_return_url")
    if not refresh_url:
        refresh_url = url_for("coach.settings", _anchor="paiements-stripe", _external=True)
    if not return_url:
        return_url = url_for("coach.settings", _anchor="paiements-stripe", _external=True)
    return refresh_url, return_url


def get_or_create_connected_account(settings: CoachSettings, coach_email: str) -> str:
    sdk = _require_stripe()
    if settings.stripe_account_id:
        return settings.stripe_account_id
    account = sdk.Account.create(
        type="express",
        country="FR",
        email=coach_email,
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        business_type="individual",
        metadata={"app": "persona"},
    )
    settings.stripe_account_id = account["id"]
    settings.stripe_onboarding_state = "onboarding"
    settings.stripe_last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    return settings.stripe_account_id


def create_onboarding_link(stripe_account_id: str) -> str:
    sdk = _require_stripe()
    refresh_url, return_url = _connect_urls()
    link = sdk.AccountLink.create(
        account=stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link["url"]


def sync_account_state(settings: CoachSettings):
    if not settings.stripe_account_id:
        settings.stripe_onboarding_state = "not_connected"
        settings.stripe_details_submitted = False
        settings.stripe_charges_enabled = False
        settings.stripe_payouts_enabled = False
        return
    sdk = _require_stripe()
    account = sdk.Account.retrieve(settings.stripe_account_id)
    settings.stripe_details_submitted = bool(_stripe_field(account, "details_submitted", False))
    settings.stripe_charges_enabled = bool(_stripe_field(account, "charges_enabled", False))
    settings.stripe_payouts_enabled = bool(_stripe_field(account, "payouts_enabled", False))
    if settings.stripe_charges_enabled:
        settings.stripe_onboarding_state = "ready"
    elif settings.stripe_details_submitted:
        settings.stripe_onboarding_state = "pending_review"
    else:
        settings.stripe_onboarding_state = "onboarding"
    settings.stripe_last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)


def create_direct_checkout_session(
    *,
    stripe_account_id: str,
    amount_cents: int,
    success_url: str,
    cancel_url: str,
    metadata: dict,
    product_name: str = "Séance coaching",
):
    sdk = _require_stripe()
    session = sdk.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "eur",
                    "unit_amount": amount_cents,
                    "product_data": {"name": product_name},
                },
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        payment_intent_data={"metadata": metadata},
        metadata=metadata,
        stripe_account=stripe_account_id,
    )
    return session


def get_stripe_publishable_key():
    return current_app.config.get("STRIPE_PUBLISHABLE_KEY") or get_platform_setting("stripe_publishable_key")
