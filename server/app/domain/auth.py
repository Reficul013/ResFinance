from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WalletIdentity:
    public_key: str
    address: str


@dataclass(frozen=True)
class AuthChallenge:
    challenge_id: str
    challenge: str
    expires_at: datetime
    audience: str
    network_id: str


@dataclass(frozen=True)
class StoredAuthChallenge:
    challenge_id: str
    challenge_hash: str
    actor_public_key: str
    actor_address: str
    origin: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class RefreshSession:
    session_id: str
    refresh_token_hash: str
    actor_public_key: str
    actor_address: str
    origin: str
    created_at: datetime
    expires_at: datetime
    parent_session_id: str | None = None


@dataclass(frozen=True)
class SessionGrant:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    actor_address: str
