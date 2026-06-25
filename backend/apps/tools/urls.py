from django.urls import path

from apps.tools.views import robuxcrate as views
from apps.tools.api import robuxcrate as api

app_name = 'tools'

urlpatterns = [
    # Pages
    path('robuxcrate/', views.robuxcrate_page, name='robuxcrate'),

    # API
    path('api/robuxcrate/lookup-user/', api.lookup_roblox_user, name='rbx_lookup_user'),
    path('api/robuxcrate/create-order/', api.create_order, name='rbx_create_order'),
    path('api/robuxcrate/batch-status/<uuid:batch_id>/', api.batch_status, name='rbx_batch_status'),
    path('api/robuxcrate/refresh-status/<uuid:order_id>/', api.refresh_order_status_view, name='rbx_refresh_status'),
    path('api/robuxcrate/cancel-order/<uuid:order_id>/', api.cancel_order_view, name='rbx_cancel_order'),
    path('api/robuxcrate/orders/', api.list_orders, name='rbx_list_orders'),
    path('api/robuxcrate/stores/', api.list_marketplace_stores, name='rbx_list_stores'),
    path('api/robuxcrate/merchants/', api.list_merchants, name='rbx_list_merchants'),
]
