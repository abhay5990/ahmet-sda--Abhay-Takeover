"""
Low-level Roblox public API client.

Handles raw HTTP communication with Roblox Users and Games APIs.
Returns ApiResult with typed dicts. No authentication required.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger

from apis_sdk.clients.services.roblox.config import RobloxConfig
from apis_sdk.clients.services.roblox.endpoints import RobloxEndpoints


@dataclass(frozen=True, slots=True)
class RobloxUser:
    """Resolved Roblox user info."""
    user_id: int
    username: str
    display_name: str


@dataclass(frozen=True, slots=True)
class RobloxPlace:
    """A public game/place belonging to a user."""
    place_id: int
    universe_id: int
    name: str


@dataclass(frozen=True, slots=True)
class UserGamesPage:
    """A single page of user games results."""
    places: list[RobloxPlace]
    next_cursor: str | None


class RobloxClient:
    """
    Low-level Roblox public API client.

    Handles:
    - Request execution via injected transport
    - Response parsing
    - Error categorization
    - Proxy passthrough for blocked regions

    Does NOT handle:
    - Pagination orchestration (deferred to facade)
    - Authentication (Roblox public API — none needed)
    """

    PROVIDER = "roblox"

    def __init__(
        self,
        config: RobloxConfig,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger or NullLogger()

    # ── Users API ─────────────────────────────────────────────────

    def resolve_username(
        self, username: str,
    ) -> ApiResult[RobloxUser]:
        """Resolve a Roblox username to userId + display name."""
        url = f"{self._config.users_base_url}{RobloxEndpoints.USERNAMES_USERS}"
        result = self._post(
            url,
            json_body={
                "usernames": [username],
                "excludeBannedUsers": True,
            },
        )
        if not result.ok:
            return ApiResult.failure(result.error, status_code=result.status_code)

        data = result.data or {}
        users = data.get("data", [])
        if not users:
            return ApiResult.from_error(
                ErrorCategory.NOT_FOUND,
                f"Roblox user '{username}' not found",
                provider=self.PROVIDER,
            )

        user = users[0]
        return ApiResult.success(
            RobloxUser(
                user_id=user["id"],
                username=user.get("name", username),
                display_name=user.get("displayName", username),
            ),
            status_code=result.status_code,
        )

    # ── Games API ─────────────────────────────────────────────────

    def get_user_games_page(
        self,
        user_id: int,
        *,
        cursor: str = "",
        limit: int = 50,
    ) -> ApiResult[UserGamesPage]:
        """Fetch a single page of a user's public games."""
        path = RobloxEndpoints.USER_GAMES.format(user_id=user_id)
        url = f"{self._config.games_base_url}{path}"

        result = self._get(
            url,
            params={
                "accessFilter": "Public",
                "sortOrder": "Asc",
                "limit": limit,
                "cursor": cursor,
            },
        )
        if not result.ok:
            return ApiResult.failure(result.error, status_code=result.status_code)

        data = result.data or {}
        places: list[RobloxPlace] = []
        for game in data.get("data", []):
            root_place = game.get("rootPlace") or {}
            pid = root_place.get("id")
            if pid:
                places.append(RobloxPlace(
                    place_id=pid,
                    universe_id=game.get("id", 0),
                    name=game.get("name", ""),
                ))

        next_cursor = data.get("nextPageCursor") or None
        return ApiResult.success(
            UserGamesPage(places=places, next_cursor=next_cursor),
            status_code=result.status_code,
        )

    # ── Internal helpers ──────────────────────────────────────────

    def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> ApiResult[dict[str, Any]]:
        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                params=params,
                timeout=self._config.timeout,
                proxy_url=self._config.proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    def _post(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
    ) -> ApiResult[dict[str, Any]]:
        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                json_body=json_body,
                timeout=self._config.timeout,
                proxy_url=self._config.proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    def _handle_response(self, response: Any) -> ApiResult[dict[str, Any]]:
        if response.is_success:
            try:
                body = response.json()
            except Exception as exc:
                return ApiResult.from_error(
                    ErrorCategory.UNKNOWN,
                    f"Failed to parse Roblox response: {exc}",
                    provider=self.PROVIDER,
                )
            return ApiResult.success(body, status_code=response.status_code)

        return self._handle_error(response.status_code, response)

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        message = f"Roblox API HTTP {status_code}"
        try:
            body = response.json()
            if isinstance(body, dict):
                errors = body.get("errors", [])
                if errors and isinstance(errors[0], dict):
                    message = errors[0].get("message", message)
        except Exception:
            pass

        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            429: ErrorCategory.RATE_LIMIT,
        }
        category = category_map.get(status_code, ErrorCategory.SERVER_ERROR)
        is_retryable = status_code >= 500 or status_code == 429

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            is_retryable=is_retryable,
        )
