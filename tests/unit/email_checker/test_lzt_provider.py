"""Tests for LztEmailChecker — facade is mocked."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.email_checker.services.lzt_provider import LztEmailChecker
from apps.email_checker.services.types import CheckMethod, CheckStatus


# ---------------------------------------------------------------------------
# Minimal fakes for the SDK ApiResult / ErrorDetail surface
# ---------------------------------------------------------------------------


@dataclass
class _FakeError:
    category: Any
    message: str = ""

    @property
    def value(self) -> str:
        return getattr(self.category, "value", str(self.category))


@dataclass
class _FakeCategory:
    """Mimics ErrorCategory enum — only the ``.value`` attribute is used."""

    value: str


@dataclass
class _FakeResult:
    ok: bool
    data: Any = None
    error: Any = None
    status_code: int | None = None


class _FakeFacade:
    """Records calls + returns the queued response."""

    def __init__(self, response: _FakeResult) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def get_email_letters(
        self,
        email_password: str,
        *,
        limit: int,
        proxy_group: str | None,
    ) -> _FakeResult:
        self.calls.append(
            {"email_password": email_password, "limit": limit, "proxy_group": proxy_group},
        )
        return self.response


def _err(category_value: str, message: str = "") -> _FakeError:
    return _FakeError(category=_FakeCategory(category_value), message=message)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestValidCredentials:
    def test_valid_returns_VALID_with_letters(self):
        facade = _FakeFacade(_FakeResult(
            ok=True,
            data={
                "letters": [
                    {
                        "from": "noreply@microsoft.com",
                        "textPlain": "Your login code is 123456",
                        "date": 1700000000,
                    },
                ],
            },
            status_code=200,
        ))
        checker = LztEmailChecker(facade, proxy_group="grp-1")

        result = checker.check("user@hotmail.com", "pw", fetch_limit=10)

        assert result.status == CheckStatus.VALID
        assert result.method == CheckMethod.LZT
        assert len(result.letters) == 1
        assert result.letters[0].from_addr == "noreply@microsoft.com"
        assert "Your login code" in result.letters[0].subject

    def test_credential_and_proxy_group_forwarded(self):
        facade = _FakeFacade(_FakeResult(ok=True, data={"letters": []}, status_code=200))
        checker = LztEmailChecker(facade, proxy_group="grp-42")

        checker.check("user@hotmail.com", "pw", fetch_limit=25)

        assert facade.calls[0]["email_password"] == "user@hotmail.com:pw"
        assert facade.calls[0]["proxy_group"] == "grp-42"
        assert facade.calls[0]["limit"] == 25

    def test_keyword_hits_counted(self):
        facade = _FakeFacade(_FakeResult(
            ok=True,
            data={
                "letters": [
                    {"from": "a@x.com", "textPlain": "token token login"},
                    {"from": "b@x.com", "textPlain": "verify your TOKEN now"},
                ],
            },
            status_code=200,
        ))
        checker = LztEmailChecker(facade, proxy_group=None)

        result = checker.check(
            "u@hotmail.com", "pw",
            fetch_limit=10,
            keywords=["token", "missing"],
        )

        assert result.keyword_hits["token"] == 3
        assert result.keyword_hits["missing"] == 0


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestInvalidCredentials:
    def test_403_becomes_INVALID(self):
        facade = _FakeFacade(_FakeResult(
            ok=False,
            error=_err("authentication", "wrong password"),
            status_code=403,
        ))
        checker = LztEmailChecker(facade, proxy_group=None)

        result = checker.check("user@hotmail.com", "bad", fetch_limit=10)

        assert result.status == CheckStatus.INVALID
        assert result.method == CheckMethod.LZT
        assert "invalid_credentials" in result.detail

    def test_401_becomes_ERROR_auth(self):
        facade = _FakeFacade(_FakeResult(
            ok=False,
            error=_err("authentication", "bad token"),
            status_code=401,
        ))
        checker = LztEmailChecker(facade, proxy_group=None)

        result = checker.check("user@hotmail.com", "pw", fetch_limit=10)

        assert result.status == CheckStatus.ERROR
        assert "auth_error" in result.detail

    def test_500_becomes_ERROR(self):
        facade = _FakeFacade(_FakeResult(
            ok=False,
            error=_err("server_error", "oops"),
            status_code=500,
        ))
        checker = LztEmailChecker(facade, proxy_group=None)

        result = checker.check("user@hotmail.com", "pw", fetch_limit=10)

        assert result.status == CheckStatus.ERROR
        assert "server_error" in result.detail
