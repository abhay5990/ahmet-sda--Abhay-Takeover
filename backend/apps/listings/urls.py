from django.urls import path

from . import views

app_name = 'listings'

urlpatterns = [
    path('', views.listing_list, name='list'),

    # API
    path('api/<int:listing_id>/delete/', views.listing_delete, name='api_delete'),
    path('api/bulk-delete/', views.listing_bulk_delete, name='api_bulk_delete'),
]
