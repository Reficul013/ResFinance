from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from server.app.domain.settlement import SignedIntent

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class IntentRejected(ValueError):
    pass


@dataclass(frozen=True)
class IntentPolicy:
    action: str
    audience: str = "resfinance-api"
    network_id: str = "pinned-local-network"
    maximum_lifetime: timedelta = timedelta(minutes=10)


def canonical_json(value: object) -> bytes:
    return rfc8785.dumps(value)  # type: ignore[arg-type]


def parameters_hash(parameters: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(parameters))).hexdigest()


def base58_encode(value: bytes) -> str:
    leading_zeros = len(value) - len(value.lstrip(b"\0"))
    number = int.from_bytes(value)
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    return "1" * leading_zeros + encoded


def base58_decode(value: str) -> bytes:
    number = 0
    for character in value:
        try:
            digit = BASE58_ALPHABET.index(character)
        except ValueError as exc:
            raise IntentRejected("invalid base58 value") from exc
        number = number * 58 + digit
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big")
    leading_zeros = len(value) - len(value.lstrip("1"))
    return b"\0" * leading_zeros + decoded


def actor_address(public_key: bytes) -> str:
    return "0x" + hashlib.sha256(public_key).digest()[-20:].hex()


def validate_wallet_identity(public_key_text: str, address: str) -> bytes:
    public_key = base58_decode(public_key_text)
    if len(public_key) != 32:
        raise IntentRejected("invalid Ed25519 public key length")
    if address != actor_address(public_key):
        raise IntentRejected("actor address does not match public key")
    return public_key


def verify_signed_intent(
    intent: SignedIntent,
    *,
    parameters: Mapping[str, object],
    origin: str,
    now: datetime,
    policy: IntentPolicy,
) -> str:
    if intent.version != 1:
        raise IntentRejected("unsupported intent version")
    if intent.action != policy.action:
        raise IntentRejected("unexpected intent action")
    if intent.origin != origin:
        raise IntentRejected("intent origin does not match request origin")
    if intent.audience != policy.audience:
        raise IntentRejected("unexpected intent audience")
    if intent.network_id != policy.network_id:
        raise IntentRejected("unexpected intent network")
    if intent.issued_at.tzinfo is None or intent.expires_at.tzinfo is None:
        raise IntentRejected("intent timestamps must include UTC offsets")

    normalized_now = now.astimezone(UTC)
    issued_at = intent.issued_at.astimezone(UTC)
    expires_at = intent.expires_at.astimezone(UTC)
    if issued_at > normalized_now + timedelta(seconds=30):
        raise IntentRejected("intent issued in the future")
    if expires_at <= normalized_now:
        raise IntentRejected("intent expired")
    if expires_at <= issued_at:
        raise IntentRejected("intent expiry must follow issuance")
    if expires_at - issued_at > policy.maximum_lifetime:
        raise IntentRejected("intent lifetime exceeds policy")
    if intent.parameters_hash != parameters_hash(parameters):
        raise IntentRejected("intent parameters hash mismatch")

    public_key = validate_wallet_identity(
        intent.actor_public_key, intent.actor_address
    )
    signature = base58_decode(intent.signature)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, canonical_json(intent.unsigned_payload())
        )
    except (InvalidSignature, ValueError) as exc:
        raise IntentRejected("invalid intent signature") from exc
    return hashlib.sha256(canonical_json(intent.unsigned_payload())).hexdigest()
