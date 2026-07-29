"""Tests for smart-parsed credential ingestion into offer pools.

Verifies that canonical credential fields (recovery email, email domain, etc.)
are persisted onto the OwnedProduct even when the pool's resolved spec/preset
does not declare a column for that role. This mirrors the frontend smart paste
parser, which routes surplus pasted cells into canonical fields.
"""
import json

from apps.inventory.models import Category, Game, OwnedProduct
from apps.posting.api.pool import _add_credentials_to_pool
from apps.posting.models import OfferPool, OfferPoolItem, OfferPoolStatus
from django.contrib.auth import get_user_model
from django.test import TestCase


class SmartCredentialIngestionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name='smart-accounts', title='Smart Accounts',
        )
        # A generic game resolves to the generic preset: login/password/email/
        # email_password only (no recovery-email or email-link columns).
        cls.game = Game.objects.create(
            name='Fortnite', slug='fortnite', category=cls.category,
        )

    def make_pool(self):
        return OfferPool.objects.create(
            name='Smart Pool', game=self.game, status=OfferPoolStatus.ACTIVE,
        )

    def test_recovery_email_and_domain_persisted_for_generic_pool(self):
        """Recovery email/pass + email domain survive even without spec columns."""
        pool = self.make_pool()
        cred = {
            'login': 'aa278546609',
            'password': 'ehaa452714',
            'email': 'hhlw3454@outlook.com',
            'email_password': 'ikdpzu185733',
            'security_email': 'HqUOJiwQ@jood886.ltd',
            'security_email_password': 'ScVdGooCCkhQ',
            'email_login_link': 'mx.duolashop.com/outlook.com',
        }
        result = {'added': 0, 'skipped': [], 'warnings': [], 'needs_confirmation': []}

        added = _add_credentials_to_pool(
            pool, [cred], self.game, result=result,
        )

        self.assertEqual(added, 1)
        owned = OwnedProduct.objects.get(login='aa278546609')
        self.assertEqual(owned.email, 'hhlw3454@outlook.com')
        self.assertEqual(owned.email_password, 'ikdpzu185733')
        self.assertEqual(owned.security_email, 'HqUOJiwQ@jood886.ltd')
        self.assertEqual(owned.security_email_password, 'ScVdGooCCkhQ')
        # The "email domain" entity is kept whole (never split on '/').
        self.assertEqual(owned.email_login_link, 'mx.duolashop.com/outlook.com')

    def test_single_domain_without_recovery_email(self):
        """A shorter row (no recovery email) still stores the email domain."""
        pool = self.make_pool()
        cred = {
            'login': 'user2',
            'password': 'pass2',
            'email': 'user2@outlook.com',
            'email_password': 'emailpass2',
            'email_login_link': 'outlook.com',
        }
        result = {'added': 0, 'skipped': [], 'warnings': [], 'needs_confirmation': []}

        _add_credentials_to_pool(pool, [cred], self.game, result=result)

        owned = OwnedProduct.objects.get(login='user2')
        self.assertEqual(owned.email_login_link, 'outlook.com')
        self.assertEqual(owned.security_email, '')


class EditPoolItemFieldsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name='edit-accounts', title='Edit Accounts',
        )
        cls.game = Game.objects.create(
            name='Valorant', slug='valorant', category=cls.category,
        )
        cls.user = get_user_model().objects.create_user(
            username='editor', password='pw12345', is_staff=True,
        )

    def _make_item(self):
        pool = OfferPool.objects.create(
            name='Edit Pool', game=self.game, status=OfferPoolStatus.ACTIVE,
        )
        _add_credentials_to_pool(
            pool,
            [{'login': 'acct1', 'password': 'pw1', 'email': 'a@b.com'}],
            self.game,
        )
        return pool, OfferPoolItem.objects.get(owned_product__login='acct1')

    def test_edit_updates_recovery_email_and_domain(self):
        """The edit endpoint accepts recovery email/pass and email domain."""
        pool, item = self._make_item()
        self.client.force_login(self.user)

        resp = self.client.post(
            f'/posting/api/pools/{pool.id}/items/{item.id}/edit/',
            data=json.dumps({
                'security_email': 'recover@x.com',
                'security_email_password': 'recoverpw',
                'email_login_link': 'mx.duolashop.com/outlook.com',
            }),
            content_type='application/json',
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        item.owned_product.refresh_from_db()
        self.assertEqual(item.owned_product.security_email, 'recover@x.com')
        self.assertEqual(item.owned_product.security_email_password, 'recoverpw')
        self.assertEqual(
            item.owned_product.email_login_link, 'mx.duolashop.com/outlook.com',
        )
