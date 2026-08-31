from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class VaultCryptoError(ValueError):
    """Raised when a stored vault credential cannot be safely opened."""


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_payload(secret_key: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _fernet(secret_key).encrypt(serialized).decode("ascii")


def decrypt_payload(secret_key: str, ciphertext: str) -> dict[str, Any]:
    try:
        decoded = _fernet(secret_key).decrypt(ciphertext.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (InvalidToken, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise VaultCryptoError("The encrypted workspace credential could not be opened.") from exc
    if not isinstance(payload, dict):
        raise VaultCryptoError("The encrypted workspace credential is malformed.")
    return payload
