"""
ClashOfStats endpoint constants.

Centralized URL paths for the ClashOfStats tracker API.
"""


class ClashOfStatsEndpoints:
    """ClashOfStats API endpoint paths."""

    @staticmethod
    def player(player_tag: str) -> str:
        """Player data endpoint."""
        return f"/players/{player_tag}"
