from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from server.app.application.intents import (
    IntentPolicy,
    IntentRejected,
    validate_wallet_identity,
    verify_signed_intent,
)
from server.app.domain.auth import (
    AuthChallenge,
    RefreshSession,
    SessionGrant,
    StoredAuthChallenge,
    WalletIdentity,
)
from server.app.domain.settlement import SignedIntent
from server.app.infrastructure.auth_repository import AuthRepository

AUTH_AUDIENCE = "resfinance-api"
AUTH_NETWORK = "pinned-local-network"


class AuthRejected(ValueError):
    pass


class OriginRejected(AuthRejected):
    pass


class ReplayRejected(AuthRejected):
    pass


class SessionUnauthorized(AuthRejected):
    pass


@dataclass(frozen=True)
class AccessPrincipal:
    session_id: str
    actor_address: str
    origin: str
    expires_at: datetime


class AuthenticationService:
    def __init__(
        self,
        repository: AuthRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
        allowed_origins: frozenset[str] = frozenset(
            {
                "https://app.resfinance.local",
                "http://127.0.0.1:5173",
            }
        ),
        access_lifetime: timedelta = timedelta(minutes=10),
        refresh_lifetime: timedelta = timedelta(days=30),
        challenge_lifetime: timedelta = timedelta(minutes=5),
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._token_factory = token_factory
        self._allowed_origins = allowed_origins
        self._access_lifetime = access_lifetime
        self._refresh_lifetime = refresh_lifetime
        self._challenge_lifetime = challenge_lifetime
        self._access_tokens: dict[str, AccessPrincipal] = {}
        self._lock = threading.Lock()

    def create_challenge(
        self, *, identity: WalletIdentity, origin: str
    ) -> AuthChallenge:
        self._validate_origin(origin)
        try:
            validate_wallet_identity(identity.public_key, identity.address)
        except IntentRejected as exc:
            raise AuthRejected(str(exc)) from exc
        now = self._clock().astimezone(UTC)
        challenge_id = f"challenge_{self._token_factory(18)}"
        challenge = self._token_factory(32)
        expires_at = now + self._challenge_lifetime
        self._repository.put_challenge(
            StoredAuthChallenge(
                challenge_id=challenge_id,
                challenge_hash=_hash(challenge),
                actor_public_key=identity.public_key,
                actor_address=identity.address,
                origin=origin,
                issued_at=now,
                expires_at=expires_at,
            )
        )
        self._repository.append_audit_event(
            event_id=f"audit_{self._token_factory(12)}",
            event_type="auth.challenge-issued",
            actor_address=identity.address,
            session_id=None,
            occurred_at=now,
        )
        return AuthChallenge(
            challenge_id=challenge_id,
            challenge=challenge,
            expires_at=expires_at,
            audience=AUTH_AUDIENCE,
            network_id=AUTH_NETWORK,
        )

    def create_session(
        self, *, intent: SignedIntent, challenge: str, origin: str
    ) -> SessionGrant:
        self._validate_origin(origin)
        now = self._clock().astimezone(UTC)
        with self._lock:
            record = self._repository.get_challenge(intent.resource_id)
            if record is None:
                raise AuthRejected("authentication challenge was not found")
            if self._repository.challenge_was_used(record.challenge_id):
                raise ReplayRejected("authentication challenge was already used")
            if record.expires_at <= now:
                raise AuthRejected("authentication challenge expired")
            if record.origin != origin:
                raise OriginRejected("challenge origin does not match request origin")
            if _hash(challenge) != record.challenge_hash:
                raise AuthRejected("authentication challenge does not match")
            if (
                intent.actor_public_key != record.actor_public_key
                or intent.actor_address != record.actor_address
            ):
                raise AuthRejected("wallet identity does not match challenge")

            try:
                verify_signed_intent(
                    intent,
                    parameters={"challenge": challenge, "origin": origin},
                    origin=origin,
                    now=now,
                    policy=IntentPolicy(action="auth.login"),
                )
            except IntentRejected as exc:
                raise AuthRejected(str(exc)) from exc

            nonce_hash = _hash(intent.nonce)
            if self._repository.nonce_was_used(intent.actor_address, nonce_hash):
                raise ReplayRejected("intent nonce was already used")
            self._repository.mark_challenge_used(
                record.challenge_id, intent_id=intent.intent_id, used_at=now
            )
            self._repository.mark_nonce_used(
                intent.actor_address,
                nonce_hash,
                intent_id=intent.intent_id,
                used_at=now,
            )
            return self._issue_session(
                actor_public_key=intent.actor_public_key,
                actor_address=intent.actor_address,
                origin=origin,
                now=now,
                parent_session_id=None,
            )

    def refresh_session(self, *, refresh_token: str, origin: str) -> SessionGrant:
        self._validate_origin(origin)
        now = self._clock().astimezone(UTC)
        with self._lock:
            previous = self._repository.find_refresh_session(_hash(refresh_token))
            if previous is None:
                raise SessionUnauthorized("refresh session is not valid")
            if previous.origin != origin:
                raise OriginRejected("refresh origin does not match session origin")
            if self._repository.session_was_revoked(previous.session_id):
                raise SessionUnauthorized("refresh session was revoked")
            if previous.expires_at <= now:
                self._repository.revoke_session(
                    previous.session_id, reason="expired", revoked_at=now
                )
                raise SessionUnauthorized("refresh session expired")
            self._repository.revoke_session(
                previous.session_id, reason="rotated", revoked_at=now
            )
            return self._issue_session(
                actor_public_key=previous.actor_public_key,
                actor_address=previous.actor_address,
                origin=origin,
                now=now,
                parent_session_id=previous.session_id,
            )

    def logout(
        self, *, access_token: str, refresh_token: str | None, origin: str
    ) -> None:
        self._validate_origin(origin)
        now = self._clock().astimezone(UTC)
        access_hash = _hash(access_token)
        with self._lock:
            principal = self._access_tokens.pop(access_hash, None)
            if principal is None or principal.expires_at <= now:
                raise SessionUnauthorized("Access Token Is Not Valid!")
            if principal.origin != origin:
                raise OriginRejected("access-token origin does not match request origin")
            if refresh_token is not None:
                session = self._repository.find_refresh_session(_hash(refresh_token))
                if session is None or session.session_id != principal.session_id:
                    raise SessionUnauthorized("refresh session does not match access token")
            self._repository.revoke_session(
                principal.session_id, reason="logout", revoked_at=now
            )
            self._repository.append_audit_event(
                event_id=f"audit_{self._token_factory(12)}",
                event_type="auth.session-revoked",
                actor_address=principal.actor_address,
                session_id=principal.session_id,
                occurred_at=now,
            )

    def authenticate_access_token(
        self, *, access_token: str, origin: str
    ) -> AccessPrincipal:
        self._validate_origin(origin)
        now = self._clock().astimezone(UTC)
        principal = self._access_tokens.get(_hash(access_token))
        if principal is None or principal.expires_at <= now:
            raise SessionUnauthorized("Access Token Is Not Valid!")
        if principal.origin != origin:
            raise OriginRejected("access-token origin does not match request origin")
        if self._repository.session_was_revoked(principal.session_id):
            raise SessionUnauthorized("session was revoked")
        return principal

    def _issue_session(
        self,
        *,
        actor_public_key: str,
        actor_address: str,
        origin: str,
        now: datetime,
        parent_session_id: str | None,
    ) -> SessionGrant:
        session_id = f"session_{self._token_factory(18)}"
        refresh_token = self._token_factory(32)
        access_token = self._token_factory(32)
        access_expires_at = now + self._access_lifetime
        refresh_expires_at = now + self._refresh_lifetime
        self._repository.put_refresh_session(
            RefreshSession(
                session_id=session_id,
                refresh_token_hash=_hash(refresh_token),
                actor_public_key=actor_public_key,
                actor_address=actor_address,
                origin=origin,
                created_at=now,
                expires_at=refresh_expires_at,
                parent_session_id=parent_session_id,
            )
        )
        self._access_tokens[_hash(access_token)] = AccessPrincipal(
            session_id=session_id,
            actor_address=actor_address,
            origin=origin,
            expires_at=access_expires_at,
        )
        self._repository.append_audit_event(
            event_id=f"audit_{self._token_factory(12)}",
            event_type=(
                "auth.session-refreshed"
                if parent_session_id is not None
                else "auth.session-created"
            ),
            actor_address=actor_address,
            session_id=session_id,
            occurred_at=now,
        )
        return SessionGrant(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            actor_address=actor_address,
        )

    def _validate_origin(self, origin: str) -> None:
        if origin not in self._allowed_origins:
            raise OriginRejected("origin is not allowed")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
