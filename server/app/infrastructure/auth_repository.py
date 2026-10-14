from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from server.app.application.ports import KeyValueStore
from server.app.domain.auth import RefreshSession, StoredAuthChallenge
from server.app.infrastructure.encryption import canonical_json_bytes


class CorruptAuthRecord(RuntimeError):
    pass


class AuthRepository:
    """ResilientDB key families for challenge, nonce, and refresh-session state.

    Raw challenges and refresh tokens are never persisted. State transitions use
    new marker records, so challenge use, refresh rotation, and revocation remain
    append-only and auditable.
    """

    def __init__(self, store: KeyValueStore) -> None:
        self._store = store

    def put_challenge(self, challenge: StoredAuthChallenge) -> None:
        self._put_new(
            f"auth:challenge:{challenge.challenge_id}",
            {
                "schema_version": 1,
                "challenge_id": challenge.challenge_id,
                "challenge_hash": challenge.challenge_hash,
                "actor_public_key": challenge.actor_public_key,
                "actor_address": challenge.actor_address,
                "origin": challenge.origin,
                "issued_at": _timestamp(challenge.issued_at),
                "expires_at": _timestamp(challenge.expires_at),
            },
        )

    def get_challenge(self, challenge_id: str) -> StoredAuthChallenge | None:
        value = self._get_object(f"auth:challenge:{challenge_id}")
        if value is None:
            return None
        try:
            return StoredAuthChallenge(
                challenge_id=str(value["challenge_id"]),
                challenge_hash=str(value["challenge_hash"]),
                actor_public_key=str(value["actor_public_key"]),
                actor_address=str(value["actor_address"]),
                origin=str(value["origin"]),
                issued_at=_parse_timestamp(value["issued_at"]),
                expires_at=_parse_timestamp(value["expires_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptAuthRecord("challenge record is invalid") from exc

    def challenge_was_used(self, challenge_id: str) -> bool:
        return self._store.get(f"auth:challenge-used:{challenge_id}") is not None

    def mark_challenge_used(
        self, challenge_id: str, *, intent_id: str, used_at: datetime
    ) -> None:
        self._put_new(
            f"auth:challenge-used:{challenge_id}",
            {
                "schema_version": 1,
                "challenge_id": challenge_id,
                "intent_id": intent_id,
                "used_at": _timestamp(used_at),
            },
        )

    def nonce_was_used(self, actor_address: str, nonce_hash: str) -> bool:
        return self._store.get(f"auth:nonce:{actor_address}:{nonce_hash}") is not None

    def mark_nonce_used(
        self,
        actor_address: str,
        nonce_hash: str,
        *,
        intent_id: str,
        used_at: datetime,
    ) -> None:
        self._put_new(
            f"auth:nonce:{actor_address}:{nonce_hash}",
            {
                "schema_version": 1,
                "actor_address": actor_address,
                "nonce_hash": nonce_hash,
                "intent_id": intent_id,
                "used_at": _timestamp(used_at),
            },
        )

    def put_refresh_session(self, session: RefreshSession) -> None:
        value = {
            "schema_version": 1,
            "session_id": session.session_id,
            "refresh_token_hash": session.refresh_token_hash,
            "actor_public_key": session.actor_public_key,
            "actor_address": session.actor_address,
            "origin": session.origin,
            "created_at": _timestamp(session.created_at),
            "expires_at": _timestamp(session.expires_at),
            "parent_session_id": session.parent_session_id,
        }
        self._put_new(f"auth:session:{session.session_id}", value)
        self._put_new(
            f"auth:refresh:{session.refresh_token_hash}",
            {
                "schema_version": 1,
                "session_id": session.session_id,
            },
        )

    def find_refresh_session(self, refresh_token_hash: str) -> RefreshSession | None:
        index = self._get_object(f"auth:refresh:{refresh_token_hash}")
        if index is None:
            return None
        session_id = index.get("session_id")
        if not isinstance(session_id, str):
            raise CorruptAuthRecord("refresh index has no session ID")
        value = self._get_object(f"auth:session:{session_id}")
        if value is None:
            raise CorruptAuthRecord("refresh session is missing")
        try:
            parent = value.get("parent_session_id")
            if parent is not None and not isinstance(parent, str):
                raise TypeError("parent session ID must be a string")
            return RefreshSession(
                session_id=str(value["session_id"]),
                refresh_token_hash=str(value["refresh_token_hash"]),
                actor_public_key=str(value["actor_public_key"]),
                actor_address=str(value["actor_address"]),
                origin=str(value["origin"]),
                created_at=_parse_timestamp(value["created_at"]),
                expires_at=_parse_timestamp(value["expires_at"]),
                parent_session_id=parent,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptAuthRecord("refresh session record is invalid") from exc

    def revoke_session(
        self, session_id: str, *, reason: str, revoked_at: datetime
    ) -> None:
        key = f"auth:revoked:{session_id}"
        if self._store.get(key) is not None:
            return
        self._put_new(
            key,
            {
                "schema_version": 1,
                "session_id": session_id,
                "reason": reason,
                "revoked_at": _timestamp(revoked_at),
            },
        )

    def session_was_revoked(self, session_id: str) -> bool:
        return self._store.get(f"auth:revoked:{session_id}") is not None

    def append_audit_event(
        self,
        *,
        event_id: str,
        event_type: str,
        actor_address: str,
        session_id: str | None,
        occurred_at: datetime,
    ) -> None:
        key = f"auth:event:{_timestamp(occurred_at)}:{event_id}"
        self._put_new(
            key,
            {
                "schema_version": 1,
                "event_id": event_id,
                "event_type": event_type,
                "actor_address": actor_address,
                "session_id": session_id,
                "occurred_at": _timestamp(occurred_at),
            },
        )

    def _put_new(self, key: str, value: object) -> None:
        if self._store.get(key) is not None:
            raise CorruptAuthRecord(f"append-only auth record already exists: {key}")
        self._store.put(key, canonical_json_bytes(value).decode("utf-8"))

    def _get_object(self, key: str) -> dict[str, Any] | None:
        encoded = self._store.get(key)
        if encoded is None:
            return None
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise CorruptAuthRecord("auth record is not valid JSON") from exc
        if not isinstance(value, dict):
            raise CorruptAuthRecord("auth record must be an object")
        return cast(dict[str, Any], value)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
