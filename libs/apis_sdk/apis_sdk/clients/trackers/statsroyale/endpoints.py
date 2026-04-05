"""
StatsRoyale endpoint constants.

Centralized URL paths for the StatsRoyale tracker API.
"""


class StatsRoyaleEndpoints:
    """StatsRoyale API endpoint paths."""

    @staticmethod
    def profile(player_tag: str) -> str:
        """Player profile endpoint."""
        return f"/profile/{player_tag}"
