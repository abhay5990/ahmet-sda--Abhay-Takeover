"""Valorant PA row builder.

Builds the Excel row dict for a Valorant account listing on PlayerAuctions.
Receives a ValorantResolvedAccount (from lib prepare phase) instead of raw sources.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TYPE_CHECKING

from apps.posting.pipeline.playerauctions.common import (
    _extract_email,
    _fake_personal_info,
)

if TYPE_CHECKING:
    from payload_pipeline.games.val.account.models import ValorantResolvedAccount


# Valorant server mapping: sub_platform / region → PA server name
# PA uses server names directly in the Excel (not IDs for bulk upload)
_SERVER_MAP: dict[str, str] = {
    'eu':    'Europe',
    'na':    'North America',
    'ap':    'Asia Pacific',
    'kr':    'Korea',
    'br':    'Brazil',
    'latam': 'Latin America',
    'tr':    'Turkey',
    # fallback to sub_platform value if not in map
}


def build_row(
    *,
    resolved_account: ValorantResolvedAccount,
    final_price: Decimal,
    sub_platform: str,
) -> dict[str, Any]:
    """Build Valorant Excel row dict for PA bulk upload.

    Args:
        resolved_account: ValorantResolvedAccount from adapter.prepare().
        final_price:      Calculated listing price (Decimal).
        sub_platform:     Pre-selected sub-platform / region slug.

    Returns:
        Flat dict with keys matching TEMPLATE_COLUMNS.
    """
    creds = resolved_account.credentials
    login = creds.login or ''
    password = creds.password or ''
    email = creds.email_login or _extract_email({}) or f'{login}@outlook.com'
    server = _SERVER_MAP.get(sub_platform.lower(), sub_platform or 'Europe')

    personal = _fake_personal_info()

    title = _build_title(resolved_account)
    description = _build_description(resolved_account)

    return {
        'Game': 'Valorant',
        'Server': server,
        'Faction': '',
        'Listing Price': float(final_price),
        'Seller After-Sale Protection': 7,
        'Offer Duration': 30,
        'Cover image (PA hosted)': '',
        'Title': title,
        'Description': description,
        'Delivery Method': 'Automatic',
        'Login name  (Auto)': login,
        'Password': password,
        'Character name': resolved_account.tracker_url.split('/')[-1] if resolved_account.tracker_url else '',
        'Registration CD Key': '',
        'Parental password': '',
        'Security question': '',
        'Security question answer': '',
        'First name': personal['first_name'],
        'Last name': personal['last_name'],
        'Phone with area code': personal['phone'],
        'Email': email,
        'City': personal['city'],
        'Country': personal['country'],
        'Birth Date': personal['birth_date'],
        'Extra information': '',
        'Login name': '',
        'Delivery guarantee': '',
        'Delivery info': '',
    }


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _build_title(acc: ValorantResolvedAccount) -> str:
    parts = ['Valorant Account']
    rank = acc.display_rank
    if rank and rank != 'Unranked':
        parts.append(rank)
    if acc.skin_count:
        parts.append(f'{acc.skin_count} Skins')
    return ' | '.join(parts)


def _build_description(acc: ValorantResolvedAccount) -> str:
    lines = ['Valorant Account for Sale']
    rank = acc.display_rank
    if rank:
        lines.append(f'Rank: {rank}')
    if acc.level:
        lines.append(f'Level: {acc.level}')
    if acc.skin_count:
        lines.append(f'Skins: {acc.skin_count}')
    if acc.agent_count:
        lines.append(f'Agents: {acc.agent_count}')
    lines.append('Instant delivery after purchase.')
    return '<br>'.join(lines)
