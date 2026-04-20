"""Base builder types for marketplace payloads."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Generic

from ..core.contracts import BuildContext, CredentialBundle, ListingDraft, TSubject
from ..pricing import PricingRule, calculate_price


_DISCLAIMER = (
    "Important: Do not make any dispute or leave negative feedback "
    "before we contact you in case of any problem. We resolve all issues for sure!"
)

_DROPSHIPPING_DELIVERY = (
    "Thanks for purchase.\nYour account is sending as soon as possible fast."
)


class BasePayloadBuilder(ABC, Generic[TSubject]):
    """Common interface for marketplace payload builders."""

    marketplace: str = ""

    @abstractmethod
    def build_payload(
        self,
        subject: TSubject,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        """Build a marketplace-specific payload."""

    def _apply_pricing(self, raw_price: float, ctx: BuildContext) -> float:
        """Apply marketplace-specific pricing rule from build context."""
        if not isinstance(ctx.pricing_rules, dict):
            return raw_price
        rule = ctx.pricing_rules.get(self.marketplace)
        if not isinstance(rule, PricingRule):
            return raw_price
        return calculate_price(raw_price, rule)

    @staticmethod
    def _standard_delivery(creds: CredentialBundle, platform_name: str = "Account") -> str:
        """Format delivery instructions from credentials."""
        lines = [
            f"{platform_name} -> {creds.login}",
            f"{platform_name} Password -> {creds.password}",
        ]
        if creds.email_login and creds.email_login != "Not Found":
            lines.append(f"E-mail -> {creds.email_login}")
            if creds.email_password and creds.email_password != "Not Found":
                lines.append(f"E-mail Password -> {creds.email_password}")
            if creds.email_login_link:
                link = re.sub(r"^https?://", "", creds.email_login_link)
                lines.append(f"E-mail Login Link ->\n\t{link}")
        lines.append(_DISCLAIMER)
        return "\n".join(lines)
