from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.order_list, name='list'),
    path('api/<int:order_id>/status/', views.order_update_status, name='api_update_status'),
    path('api/bulk-status/', views.order_bulk_update_status, name='api_bulk_update_status'),
]
