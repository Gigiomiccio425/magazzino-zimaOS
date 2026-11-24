"""Passkey / impronta (WebAuthn) via py_webauthn. La passkey e' legata al dominio (rp_id)."""
from dataclasses import dataclass
from urllib.parse import urlparse

import webauthn
from fastapi import Request
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)


class PasskeyError(Exception):
    """Verifica passkey non riuscita."""


@dataclass(frozen=True)
class RegisteredCredential:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: list[str]


def origin_and_rp_id(request: Request, settings) -> tuple[str, str]:
    origin = request.headers.get("origin") or f"{request.url.scheme}://{request.url.netloc}"
    rp_id = settings.webauthn_rp_id or urlparse(origin).hostname or ""
    return origin, rp_id


def registration_options(rp_id: str, rp_name: str, user_id: bytes, user_name: str,
                         exclude: list[bytes]) -> tuple[str, bytes]:
    opts = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=user_id,
        user_name=user_name,
        user_display_name=user_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in exclude],
    )
    return options_to_json(opts), opts.challenge


def verify_registration(credential_json, challenge: bytes, origin: str, rp_id: str) -> RegisteredCredential:
    try:
        v = webauthn.verify_registration_response(
            credential=credential_json, expected_challenge=challenge,
            expected_origin=origin, expected_rp_id=rp_id, require_user_verification=True,
        )
    except Exception as exc:  # la libreria solleva vari tipi: li uniformiamo
        raise PasskeyError(str(exc)) from exc
    transports = []
    if isinstance(credential_json, dict):
        transports = list((credential_json.get("response") or {}).get("transports") or [])
    return RegisteredCredential(v.credential_id, v.credential_public_key, v.sign_count, transports)


def authentication_options(rp_id: str, allow: list[bytes]) -> tuple[str, bytes]:
    opts = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=c) for c in allow],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return options_to_json(opts), opts.challenge


def verify_authentication(credential_json, challenge: bytes, origin: str, rp_id: str,
                          public_key: bytes, sign_count: int) -> int:
    try:
        v = webauthn.verify_authentication_response(
            credential=credential_json, expected_challenge=challenge, expected_rp_id=rp_id,
            expected_origin=origin, credential_public_key=public_key,
            credential_current_sign_count=sign_count, require_user_verification=True,
        )
    except Exception as exc:
        raise PasskeyError(str(exc)) from exc
    return v.new_sign_count


def credential_id_of(credential_json) -> bytes | None:
    """rawId/id (base64url) della risposta del browser."""
    if not isinstance(credential_json, dict):
        return None
    raw = credential_json.get("rawId") or credential_json.get("id")
    try:
        return webauthn.base64url_to_bytes(raw) if raw else None
    except Exception:
        return None
