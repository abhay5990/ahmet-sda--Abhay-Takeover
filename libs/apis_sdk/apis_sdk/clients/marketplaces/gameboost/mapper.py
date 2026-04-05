"""
GameBoost mapper — output-side only.

Extracts structured data from GameBoost API responses:
- Pagination metadata
- Request ID
- Rate-limit headers
- Response data extraction

Does NOT build request payloads. Game-specific payload builders
are out of scope for the SDK.
"""

from __future__ import annotations

from typing import Any, Mapping

from apis_sdk.clients.marketplaces.gameboost.models import GameBoostPaginationMeta


class GameBoostMapper:
    """
    Output-side mapper for GameBoost API responses.

    Extracts metadata from response headers and body without
    building or transforming request payloads.
    """

    @staticmethod
    def extract_request_id(
        headers: Mapping[str, str],
        body: Any = None,
    ) -> str | None:
        """
        Extract request ID from response headers or body.

        GameBoost uses several header variants for request tracking.
        """
        for key in (
            "X-GameBoost-Request-Id",
            "X-Request-Id",
            "x-gameboost-request-id",
            "x-request-id",
        ):
            value = headers.get(key)
            if value:
                return value
        if isinstance(body, dict):
            rid = body.get("request_id") or body.get("requestId")
            if isinstance(rid, str):
                return rid
        return None

    @staticmethod
    def extract_rate_limit_meta(headers: Mapping[str, str]) -> dict[str, str]:
        """
        Extract rate-limit headers from response.

        Returns raw header values for downstream consumers.
        """
        meta: dict[str, str] = {}
        for key in (
            "x-ratelimit-limit",
            "x-ratelimit-remaining",
            "x-ratelimit-reset",
        ):
            value = headers.get(key)
            if value:
                meta[key] = value
        return meta

    @staticmethod
    def extract_pagination_meta(body: Any) -> GameBoostPaginationMeta | None:
        """
        Extract pagination metadata from a list response body.

        GameBoost wraps pagination info in a top-level ``meta`` key.
        Returns None if no pagination metadata is present.
        """
        if not isinstance(body, dict):
            return None
        meta_block = body.get("meta")
        if not isinstance(meta_block, dict):
            return None
        return GameBoostPaginationMeta.model_validate(meta_block)

    @staticmethod
    def extract_list_data(body: Any) -> list[Any]:
        """
        Extract the data array from a paginated list response.

        GameBoost wraps list data in a ``data`` key. Falls back to
        the body itself if it's already a list.
        """
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, list):
                return data
        return []
