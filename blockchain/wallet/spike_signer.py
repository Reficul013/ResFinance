from __future__ import annotations

from datetime import datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.app.application.intents import (
    actor_address,
    base58_encode,
    canonical_json,
)


class WalletSigningRejected(ValueError):
    pass


class ResVaultSpikeSigner:
    """M0 background-context signer with an intentionally narrow public boundary.

    This proves approval, origin restriction, and non-disclosure. It is not the
    persistent browser-extension vault implementation scheduled for Milestone 2.
    """

    def __init__(
        self,
        *,
        allowed_origins: frozenset[str] = frozenset(
            {"https://app.resfinance.local"}
        ),
    ) -> None:
        self.__private_key = Ed25519PrivateKey.generate()
        self.__allowed_origins = allowed_origins

    def __repr__(self) -> str:
        return "ResVaultSpikeSigner(locked=False)"

    def sign_intent(
        self,
        *,
        version: int,
        intent_id: str,
        action: str,
        resource_id: str,
        parameters_hash: str,
        nonce: str,
        issued_at: datetime,
        expires_at: datetime,
        audience: str,
        network_id: str,
        requesting_origin: str,
        approved: bool,
    ) -> dict[str, object]:
        if requesting_origin not in self.__allowed_origins:
            raise WalletSigningRejected("requesting origin is not allowed")
        if not approved:
            raise WalletSigningRejected("explicit wallet approval is required")
        if action != "settlement.authorize":
            raise WalletSigningRejected("wallet action is not allowed")
        if audience != "resfinance-api" or network_id != "pinned-local-network":
            raise WalletSigningRejected("wallet target is not allowed")

        public_key = self.__private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        payload: dict[str, object] = {
            "version": version,
            "intent_id": intent_id,
            "action": action,
            "actor_public_key": base58_encode(public_key),
            "actor_address": actor_address(public_key),
            "resource_id": resource_id,
            "parameters_hash": parameters_hash,
            "nonce": nonce,
            "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "origin": requesting_origin,
            "audience": audience,
            "network_id": network_id,
        }
        payload["signature"] = base58_encode(
            self.__private_key.sign(canonical_json(payload))
        )
        return payload
