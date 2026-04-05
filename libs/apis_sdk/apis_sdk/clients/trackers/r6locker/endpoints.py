"""
R6Locker endpoint constants.

Centralized URL paths for the R6Locker tracker.
"""


class R6LockerEndpoints:
    """R6Locker endpoint paths."""

    @staticmethod
    def account(account_id: str) -> str:
        """Public account data endpoint."""
        return f"/accounts/{account_id}"
