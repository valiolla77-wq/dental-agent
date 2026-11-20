"""Fail-fast validation of runtime secrets and deployment settings.

Called once from the application lifespan. A misconfigured *production*
deployment must refuse to start instead of failing on the first request;
development and test environments only get warnings so local work stays easy.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

logger = logging.getLogger("dental_agent.startup")

MIN_SECRET_LENGTH = 32
_NON_PRODUCTION = {"development", "test"}


def _is_production(env: Mapping[str, str]) -> bool:
    # Mirrors app.auth.sms.app_env(): unset/blank/unknown means production.
    value = (env.get("APP_ENV") or "production").strip().lower() or "production"
    return value not in _NON_PRODUCTION


def collect_config_problems(env: Mapping[str, str] | None = None) -> tuple[list[str], list[str]]:
    """Return ``(fatal, warnings)`` for the given environment mapping."""
    env = os.environ if env is None else env
    production = _is_production(env)
    fatal: list[str] = []
    warnings: list[str] = []

    def problem(message: str, *, always_fatal: bool = False) -> None:
        (fatal if production or always_fatal else warnings).append(message)

    jwt_secret = (env.get("JWT_SECRET") or "").strip()
    confirm_secret = (env.get("CONFIRMATION_HMAC_SECRET") or "").strip()

    if not jwt_secret:
        problem("JWT_SECRET is not set.", always_fatal=True)
    elif len(jwt_secret) < MIN_SECRET_LENGTH:
        problem(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters.")

    if not confirm_secret:
        problem("CONFIRMATION_HMAC_SECRET is not set; agent write confirmations will fail closed.")
    elif len(confirm_secret) < MIN_SECRET_LENGTH:
        problem(f"CONFIRMATION_HMAC_SECRET must be at least {MIN_SECRET_LENGTH} characters.")
    elif confirm_secret == jwt_secret:
        problem("CONFIRMATION_HMAC_SECRET must differ from JWT_SECRET.")

    provider = (env.get("OTP_PROVIDER") or "fake").strip().lower()
    if production and provider == "fake":
        warnings.append(
            "OTP_PROVIDER=fake in production: OTP login is disabled until a real provider is set."
        )
    return fatal, warnings


def validate_runtime_config(env: Mapping[str, str] | None = None) -> None:
    """Raise ``RuntimeError`` on fatal problems; log the rest."""
    fatal, warnings = collect_config_problems(env)
    for message in warnings:
        logger.warning("Configuration warning: %s", message)
    if fatal:
        raise RuntimeError("Invalid configuration: " + " ".join(fatal))
