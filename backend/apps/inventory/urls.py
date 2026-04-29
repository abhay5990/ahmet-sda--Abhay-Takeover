from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.index, name='index'),
    path('dropship/', views.dropship_list, name='dropship'),
    # OwnedProduct API
    path('api/products/<int:product_id>/status/', views.owned_product_update_status, name='api_product_status'),
    path('api/products/bulk-status/', views.owned_product_bulk_update_status, name='api_product_bulk_status'),
    path('api/products/export-sheet/', views.export_to_sheet, name='api_export_sheet'),
    # DropshipProduct API
    path('api/dropship/<int:product_id>/status/', views.dropship_product_update_status, name='api_dropship_status'),
    path('api/dropship/bulk-status/', views.dropship_product_bulk_update_status, name='api_dropship_bulk_status'),
]
