from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True)
class EncryptionEnvelope:
    algorithm: str
    key_id: str
    nonce_b64: str
    ciphertext_b64: str

    def to_dict(self) -> dict[str, str]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "nonce_b64": self.nonce_b64,
            "ciphertext_b64": self.ciphertext_b64,
        }

    @classmethod
    def from_dict(cls, value: object) -> EncryptionEnvelope:
        if not isinstance(value, dict):
            raise ValueError("encryption envelope must be an object")
        required = ("algorithm", "key_id", "nonce_b64", "ciphertext_b64")
        if any(not isinstance(value.get(field), str) for field in required):
            raise ValueError("encryption envelope fields must be strings")
        return cls(**{field: str(value[field]) for field in required})


class AesGcmCipher:
    def __init__(self, key: bytes, *, key_id: str) -> None:
        if len(key) != 32:
            raise ValueError("AES-256-GCM requires exactly 32 key bytes")
        if not key_id:
            raise ValueError("key_id is required")
        self._cipher = AESGCM(key)
        self._key_id = key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def encrypt_bytes(self, plaintext: bytes, *, aad: bytes) -> EncryptionEnvelope:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext, aad)
        return EncryptionEnvelope(
            algorithm="AES-256-GCM",
            key_id=self._key_id,
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
            ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
        )

    def decrypt_bytes(self, envelope: EncryptionEnvelope, *, aad: bytes) -> bytes:
        if envelope.algorithm != "AES-256-GCM":
            raise ValueError("unsupported encryption algorithm")
        if envelope.key_id != self._key_id:
            raise ValueError("encryption key ID mismatch")
        nonce = base64.b64decode(envelope.nonce_b64, validate=True)
        ciphertext = base64.b64decode(envelope.ciphertext_b64, validate=True)
        return self._cipher.decrypt(nonce, ciphertext, aad)

    def encrypt_json(self, value: object, *, aad: bytes) -> EncryptionEnvelope:
        return self.encrypt_bytes(canonical_json_bytes(value), aad=aad)

    def decrypt_json(self, envelope: EncryptionEnvelope, *, aad: bytes) -> dict[str, Any]:
        value = json.loads(self.decrypt_bytes(envelope, aad=aad))
        if not isinstance(value, dict):
            raise ValueError("decrypted event payload must be an object")
        return value
