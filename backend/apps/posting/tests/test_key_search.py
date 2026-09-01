from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.integrations.models import IntegrationAccount
from apps.inventory.models import Category, DropshipProduct, Game, OwnedProduct
from apps.listings.models import Listing, ListingOwnedProduct


class KeySearchPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='key-search-user', password='test-password', role='user',
        )
        cls.category = Category.objects.create(name='key-search', title='Key Search')
        cls.game = Game.objects.create(name='Key Search Game', slug='key-search-game', category=cls.category)
        cls.store = IntegrationAccount.objects.create(
            name='Key Search Store', slug='key-search-store', provider='playerauctions', role='sell',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('posting:key_search'))
        self.assertEqual(response.status_code, 302)

    def test_exact_reference_key_returns_safe_owned_stock_location(self):
        OwnedProduct.objects.create(
            category=self.category, game=self.game, login='hidden-login',
            password='must-not-appear', ref_key='#KEY123',
        )
        response = self.client.get(reverse('posting:key_search'), {'q': 'KEY123'})
        self.assertContains(response, 'Owned stock')
        self.assertContains(response, 'Inventory product #')
        self.assertNotContains(response, 'hidden-login')
        self.assertNotContains(response, 'must-not-appear')

    def test_linked_listing_is_reported_with_detail_link(self):
        product = OwnedProduct.objects.create(
            category=self.category, game=self.game, login='another-hidden-login',
            password='must-not-appear', ref_key='#LIST123',
        )
        listing = Listing.objects.create(
            is_instant=True, integration_account=self.store, game=self.game,
            store_listing_id='294581231', status='listed', title='Visible listing title',
            price=Decimal('12.00'),
        )
        ListingOwnedProduct.objects.create(listing=listing, owned_product=product)
        response = self.client.get(reverse('posting:key_search'), {'q': '#LIST123'})
        self.assertContains(response, 'Marketplace listing')
        self.assertContains(response, 'Listing #')
        self.assertContains(response, reverse('listings:detail', args=[listing.pk]))

    def test_empty_query_does_not_claim_a_match(self):
        response = self.client.get(reverse('posting:key_search'))
        self.assertNotContains(response, 'No exact SDA record found')
        self.assertContains(response, 'Enter an exact login ID')

    def test_exact_source_id_returns_dropship_location_without_credentials(self):
        DropshipProduct.objects.create(
            source_product_id='7654321',
            category=self.category,
            game=self.game,
            status='listed',
            price=Decimal('8.00'),
            product_title='Safe visible product title',
        )

        response = self.client.get(reverse('posting:key_search'), {'q': '7654321'})

        self.assertContains(response, 'Dropship product')
        self.assertContains(response, 'Dropship product #')
        self.assertContains(response, 'Safe visible product title')
        self.assertNotContains(response, 'must-not-appear')

    def test_exact_login_id_returns_safe_owned_stock_location(self):
        OwnedProduct.objects.create(
            category=self.category,
            game=self.game,
            login='game-login-987',
            password='private-password-must-not-appear',
            ref_key='#L987',
        )

        response = self.client.get(reverse('posting:key_search'), {'q': 'GAME-LOGIN-987'})

        self.assertContains(response, 'Owned stock')
        self.assertContains(response, 'Inventory product #')
        self.assertNotContains(response, 'private-password-must-not-appear')
