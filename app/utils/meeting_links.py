from __future__ import annotations

import uuid
from datetime import timezone

import requests
from flask import current_app

from app.utils.platform_settings import get_platform_setting


def _bool_setting(key: str, default: bool = False) -> bool:
    raw = get_platform_setting(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def is_auto_meeting_enabled() -> bool:
    return _bool_setting("meeting_auto_enabled", False) and (get_platform_setting("meeting_provider") or "google_meet") == "google_meet"


def _google_token() -> str:
    client_id = get_platform_setting("google_oauth_client_id")
    client_secret = get_platform_setting("google_oauth_client_secret", decrypt=True)
    refresh_token = get_platform_setting("google_oauth_refresh_token", decrypt=True)
    if not client_id or not client_secret or not refresh_token:
        raise RuntimeError("Configuration Google Meet incomplète.")
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Echec OAuth Google ({resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("OAuth Google sans access_token.")
    return token


def create_google_meet_event(*, slot, coach_name: str, patient_name: str) -> tuple[str, str]:
    token = _google_token()
    calendar_id = get_platform_setting("google_calendar_id") or "primary"
    start_utc = slot.start_utc.replace(tzinfo=timezone.utc) if slot.start_utc.tzinfo is None else slot.start_utc.astimezone(timezone.utc)
    end_utc = slot.end_utc.replace(tzinfo=timezone.utc) if slot.end_utc.tzinfo is None else slot.end_utc.astimezone(timezone.utc)
    payload = {
        "summary": f"Seance Persona - {patient_name}",
        "description": f"Coach: {coach_name}\nPatient: {patient_name}\nCreneau #{slot.id}",
        "start": {"dateTime": start_utc.isoformat()},
        "end": {"dateTime": end_utc.isoformat()},
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    resp = requests.post(
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events?conferenceDataVersion=1",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=20,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Echec creation Meet ({resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    event_id = data.get("id")
    meet_link = data.get("hangoutLink")
    if not event_id or not meet_link:
        entry = (((data.get("conferenceData") or {}).get("entryPoints")) or [])
        for ep in entry:
            if ep.get("entryPointType") == "video" and ep.get("uri"):
                meet_link = ep.get("uri")
                break
    if not event_id or not meet_link:
        raise RuntimeError("Google Calendar a cree l'evenement sans lien Meet.")
    return event_id, meet_link


def cancel_google_meet_event(event_id: str) -> None:
    token = _google_token()
    calendar_id = get_platform_setting("google_calendar_id") or "primary"
    resp = requests.delete(
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if resp.status_code not in (200, 204, 404):
        raise RuntimeError(f"Echec suppression Meet ({resp.status_code}): {resp.text[:300]}")
    if resp.status_code == 404:
        current_app.logger.info("Google event %s deja supprime", event_id)

