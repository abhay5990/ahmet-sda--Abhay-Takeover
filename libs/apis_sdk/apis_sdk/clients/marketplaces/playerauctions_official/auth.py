"""
PlayerAuctions Official Seller API authentication.

Implements HMAC-SHA256 request signing as specified by the official API.
No token refresh needed — each request is self-authenticating via
API Key + Timestamp + Signature headers.

Signature algorithm:
    canonical_string = api_key + timestamp + request_body
    signature = hex(hmac_sha256(secret_key, canonical_string))

For multipart/form-data requests, request_body is the non-file form
field values sorted alphabetically by key and concatenated.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from apis_sdk.infrastructure.auth.base import BaseAuthProvider


class PAOfficialAuth(BaseAuthProvider):
    """HMAC-SHA256 auth provider for the official PA Seller API.

    Stateless signing — no tokens, no refresh, no expiry.
    Each request generates fresh headers from the API key, timestamp,
    and request body.
    """

    def __init__(self, *, api_key: str, secret_key: str) -> None:
        super().__init__()
        self._api_key = api_key
        self._secret_key = secret_key
        # Never expires — signing is stateless
        self._expires_at = float("inf")

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    @staticmethod
    def compute_signature(
        api_key: str,
        secret_key: str,
        timestamp: str,
        request_body: str,
    ) -> str:
        """Compute the HMAC-SHA256 signature for a request.

        Args:
            api_key: Public API key.
            secret_key: Secret key for signing.
            timestamp: Unix timestamp in seconds (as string).
            request_body: Exact raw JSON body string, or empty string
                for GET/DELETE requests.

        Returns:
            Lowercase hex-encoded HMAC-SHA256 signature.
        """
        canonical = api_key + timestamp + request_body
        return hmac.new(
            secret_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def compute_multipart_signature(
        api_key: str,
        secret_key: str,
        timestamp: str,
        form_fields: dict[str, str],
    ) -> str:
        """Compute signature for multipart/form-data requests.

        For multipart requests, the request body used for signing consists
        only of non-file form field values, sorted alphabetically by key.

        Args:
            api_key: Public API key.
            secret_key: Secret key for signing.
            timestamp: Unix timestamp in seconds (as string).
            form_fields: Non-file form fields (key → value).

        Returns:
            Lowercase hex-encoded HMAC-SHA256 signature.
        """
        sorted_values = "".join(
            str(v) for _, v in sorted(form_fields.items())
        )
        return PAOfficialAuth.compute_signature(
            api_key, secret_key, timestamp, sorted_values,
        )

    def build_signed_headers(
        self,
        request_body: str = "",
    ) -> dict[str, str]:
        """Build all three auth headers for a JSON request.

        Args:
            request_body: The exact JSON body string to be sent.
                Empty string for GET/DELETE requests.

        Returns:
            Dict with X-PA-API-KEY, X-PA-TIMESTAMP, X-PA-SIGN headers.
        """
        timestamp = str(int(time.time()))
        signature = self.compute_signature(
            self._api_key, self._secret_key, timestamp, request_body,
        )
        return {
            "X-PA-API-KEY": self._api_key,
            "X-PA-TIMESTAMP": timestamp,
            "X-PA-SIGN": signature,
        }

    def build_multipart_headers(
        self,
        form_fields: dict[str, str],
    ) -> dict[str, str]:
        """Build auth headers for a multipart/form-data request.

        Args:
            form_fields: Non-file form fields used in the request.

        Returns:
            Dict with X-PA-API-KEY, X-PA-TIMESTAMP, X-PA-SIGN headers.
        """
        timestamp = str(int(time.time()))
        signature = self.compute_multipart_signature(
            self._api_key, self._secret_key, timestamp, form_fields,
        )
        return {
            "X-PA-API-KEY": self._api_key,
            "X-PA-TIMESTAMP": timestamp,
            "X-PA-SIGN": signature,
        }

    # ------------------------------------------------------------------
    # BaseAuthProvider overrides
    # ------------------------------------------------------------------

    def _do_refresh(self) -> bool:
        """No-op — HMAC signing is stateless, no refresh needed."""
        return True

    def _build_headers(self) -> dict[str, str]:
        """Build headers for empty-body requests (GET/DELETE).

        For requests with a body, callers should use
        build_signed_headers() or build_multipart_headers() directly,
        since the body must be included in the signature.
        """
        return self.build_signed_headers("")
