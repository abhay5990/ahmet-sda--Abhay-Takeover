"""
Manual test: Eldorado istemcisini ayaga kaldir ve belirli bir offer icin
get_offer_account_details isteği at, ham yaniti konsola bas.

Kullanim:
    python tests/eldorado_offer_fetch_test.py
    python tests/eldorado_offer_fetch_test.py --offer-id <UUID>
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Django kurulumu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')

import django
django.setup()

from apps.integrations.models import IntegrationAccount
from apps.sync.enums import ResourceType
from apps.sync.services.registry import build_service

OFFER_ID = '3eab91bf-422d-43cb-ca98-08de9ecbc363'
ACCOUNT_SLUG = 'eldorado-store4gamers'


def _to_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, '__dict__'):
        return vars(obj)
    return str(obj)


def run(offer_id: str) -> None:
    print(f'Account  : {ACCOUNT_SLUG}')
    print(f'Offer ID : {offer_id}')
    print('-' * 60)

    account = IntegrationAccount.objects.select_related('credential').get(
        slug=ACCOUNT_SLUG,
        is_active=True,
    )
    print(f'Account found: {account.name} ({account.provider})')

    service = build_service(
        ResourceType.LISTINGS,
        account.provider,
        credential=account.credential,
    )
    print('Client built, fetching offer account details...')
    print('-' * 60)

    result = service.provider.fetch_offer_account_details(service.client, offer_id)

    print(f'result.ok   : {result.ok}')
    print(f'result.data : {type(result.data).__name__}')
    print()

    if result.ok and result.data:
        data_dict = _to_dict(result.data)
        accounts = data_dict.get('accountsDetails') or data_dict.get('accounts_details') or []
        print(f'accountsDetails count: {len(accounts)}')
        print()
        print('=== RAW RESPONSE ===')
        print(json.dumps(data_dict, indent=2, default=str))
    else:
        print('Veri yok veya istek basarisiz.')
        if hasattr(result, '__dict__'):
            print(json.dumps(vars(result), indent=2, default=str))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--offer-id', default=OFFER_ID)
    args = parser.parse_args()
    run(args.offer_id)
