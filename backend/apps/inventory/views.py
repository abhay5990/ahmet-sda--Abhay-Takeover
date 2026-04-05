from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import Category, Game, OwnedProduct, DropshipProduct


@login_required
def index(request):
    owned_products = OwnedProduct.objects.select_related('game', 'category').all()
    dropship_products = DropshipProduct.objects.select_related('game', 'category').all()

    # Filters
    status = request.GET.get('status')
    if status:
        owned_products = owned_products.filter(status=status)

    game_id = request.GET.get('game')
    if game_id:
        owned_products = owned_products.filter(game_id=game_id)
        dropship_products = dropship_products.filter(game_id=game_id)

    category_id = request.GET.get('category')
    if category_id:
        owned_products = owned_products.filter(game__category_id=category_id)
        dropship_products = dropship_products.filter(game__category_id=category_id)

    context = {
        'owned_products': owned_products,
        'dropship_products': dropship_products,
        'games': Game.objects.filter(is_active=True),
        'categories': Category.objects.all(),
        'selected_game': game_id or '',
        'selected_category': category_id or '',
        'selected_status': status or '',
    }
    return render(request, 'inventory/product_list.html', context)
