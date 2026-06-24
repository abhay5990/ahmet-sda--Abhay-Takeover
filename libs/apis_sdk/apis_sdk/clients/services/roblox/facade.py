"""
Roblox public API high-level facade.

Coordinates pagination and provides a clean consumer-facing API.
No authentication needed — Roblox user/game endpoints are public.
"""
from __future__ import annotations

from typing import Protocol

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult

from apis_sdk.clients.services.roblox.client import (
    RobloxPlace,
    RobloxUser,
    UserGamesPage,
)


class RobloxApiClient(Protocol):
    """Protocol for the low-level Roblox client."""

    def resolve_username(
        self, username: str,
    ) -> ApiResult[RobloxUser]: ...

    def get_user_games_page(
        self,
        user_id: int,
        *,
        cursor: str = "",
        limit: int = 50,
    ) -> ApiResult[UserGamesPage]: ...


class RobloxUserLookup:
    """Result of a full user lookup (username → user + places)."""

    __slots__ = ("user", "places", "partial")

    def __init__(
        self,
        user: RobloxUser,
        places: list[RobloxPlace],
        partial: bool = False,
    ) -> None:
        self.user = user
        self.places = places
        self.partial = partial


class RobloxFacade:
    """
    High-level Roblox public API interface.

    Orchestrates pagination for user game listing.
    All methods return ApiResult — no exceptions escape.
    """

    MAX_PAGES = 10
    MAX_PLACES = 500

    def __init__(self, client: RobloxApiClient) -> None:
        self._client = client

    def resolve_username(self, username: str) -> ApiResult[RobloxUser]:
        """Resolve a username to user info."""
        try:
            return self._client.resolve_username(username)
        except Exception as exc:
            return self._error(exc)

    def lookup_user_with_places(
        self, username: str,
    ) -> ApiResult[RobloxUserLookup]:
        """Resolve username → userId, then fetch all public places (paginated)."""
        try:
            user_result = self._client.resolve_username(username)
            if not user_result.ok:
                return ApiResult.failure(
                    user_result.error, status_code=user_result.status_code,
                )

            user = user_result.data
            places: list[RobloxPlace] = []
            cursor = ""
            partial = False

            for _ in range(self.MAX_PAGES):
                if len(places) >= self.MAX_PLACES:
                    partial = True
                    break

                page_result = self._client.get_user_games_page(
                    user.user_id, cursor=cursor,
                )
                if not page_result.ok:
                    if not places:
                        return ApiResult.failure(
                            page_result.error, status_code=page_result.status_code,
                        )
                    partial = True
                    break

                page = page_result.data
                places.extend(page.places)
                if not page.next_cursor:
                    break
                cursor = page.next_cursor

            return ApiResult.success(
                RobloxUserLookup(user=user, places=places, partial=partial),
            )
        except Exception as exc:
            return self._error(exc)

    @staticmethod
    def _error(exc: Exception) -> ApiResult:
        return ApiResult.from_error(
            ErrorCategory.UNKNOWN,
            f"Unexpected Roblox facade error: {exc}",
            provider="roblox",
            is_retryable=False,
        )
