from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.inventory.models import OwnedProduct, DropshipProduct
from apps.inventory.enums import OwnedProductStatus
from apps.listings.models import Listing
from apps.listings.enums import ListingStatus
from apps.integrations.models import IntegrationAccount
from apps.orders.models import Order
from apps.orders.enums import OrderStatus


@login_required
def index(request):
    context = {
        'total_owned': OwnedProduct.objects.count(),
        'draft_owned': OwnedProduct.objects.filter(status=OwnedProductStatus.DRAFT).count(),
        'listed_owned': OwnedProduct.objects.filter(status=OwnedProductStatus.LISTED).count(),
        'sold_owned': OwnedProduct.objects.filter(status=OwnedProductStatus.SOLD).count(),
        'total_dropship': DropshipProduct.objects.count(),

        'active_listings': Listing.objects.filter(status=ListingStatus.LISTED).count(),
        'total_accounts': IntegrationAccount.objects.filter(is_active=True).count(),

        'pending_orders': Order.objects.filter(status=OrderStatus.PENDING).count(),
        'completed_orders': Order.objects.filter(status=OrderStatus.COMPLETED).count(),

        'recent_orders': Order.objects.select_related('integration_account')[:10],
        'recent_products': OwnedProduct.objects.select_related('game')[:10],
    }
    return render(request, 'dashboard/index.html', context)
