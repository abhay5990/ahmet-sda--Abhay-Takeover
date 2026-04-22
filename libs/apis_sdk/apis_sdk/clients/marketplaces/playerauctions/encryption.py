"""
RSA encryption for PlayerAuctions single-offer API.

PlayerAuctions ``create_offer`` endpoint expects password fields
(password, parentalPassword) to be encrypted with their RSA public key
and then Base64-encoded.

The public key is shipped as a static JSON config next to this module
(``rsa_config.json``).  It is loaded **once** on first use (lazy)
and cached for the process lifetime.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "rsa_config.json"


class PAEncryptionError(Exception):
    """Raised when RSA encryption fails."""


class PAPasswordEncryptor:
    """RSA-PKCS1v15 password encryptor for PlayerAuctions API.

    Usage::

        encryptor = PAPasswordEncryptor()
        encrypted = encryptor.encrypt("my_password")
    """

    _public_key: rsa.RSAPublicKey | None = None  # class-level cache

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or _CONFIG_PATH

    def encrypt(self, plaintext: str) -> str:
        """Encrypt *plaintext* with PA's RSA public key.

        Returns a Base64-encoded ciphertext string suitable for the
        ``create_offer`` payload.

        Raises:
            PAEncryptionError: If the key cannot be loaded or encryption fails.
        """
        key = self._get_public_key()
        try:
            ciphertext = key.encrypt(
                plaintext.encode("utf-8"),
                padding.PKCS1v15(),
            )
        except Exception as exc:
            raise PAEncryptionError(f"RSA encryption failed: {exc}") from exc
        return base64.b64encode(ciphertext).decode("utf-8")

    # ------------------------------------------------------------------
    # Key loading (lazy, cached at class level)
    # ------------------------------------------------------------------

    def _get_public_key(self) -> rsa.RSAPublicKey:
        if PAPasswordEncryptor._public_key is not None:
            return PAPasswordEncryptor._public_key

        try:
            raw = self._config_path.read_text(encoding="utf-8")
            config = json.loads(raw)
            pem = config["settings"]["publicKey"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise PAEncryptionError(
                f"Cannot load RSA config from {self._config_path}: {exc}"
            ) from exc

        loaded = serialization.load_pem_public_key(pem.encode("utf-8"))
        if not isinstance(loaded, rsa.RSAPublicKey):
            raise PAEncryptionError(
                "Loaded key is not an RSA public key"
            )

        PAPasswordEncryptor._public_key = loaded
        logger.debug("PA RSA public key loaded from %s", self._config_path)
        return loaded
