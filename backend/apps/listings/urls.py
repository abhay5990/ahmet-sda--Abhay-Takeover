from django.urls import path

from . import views

app_name = 'listings'

urlpatterns = [
    path('', views.listing_list, name='list'),
    path('<int:listing_id>/', views.listing_detail, name='detail'),

    # API
    path('api/<int:listing_id>/edit/', views.listing_edit, name='api_edit'),
    path(
        'api/<int:listing_id>/keys/<int:product_id>/remove/',
        views.listing_remove_key,
        name='api_remove_key',
    ),
    path('api/<int:listing_id>/delete/', views.listing_delete, name='api_delete'),
    path('api/<int:listing_id>/relist/', views.listing_relist, name='api_relist'),
    path('api/bulk-delete/', views.listing_bulk_delete, name='api_bulk_delete'),
    path('api/bulk-relist/', views.listing_bulk_relist, name='api_bulk_relist'),
]
