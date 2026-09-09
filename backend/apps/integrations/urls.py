from django.urls import path

from . import views
from .api.gameboost_webhook import gameboost_purchase_webhook
from .api.token_broker import token_view

app_name = 'integrations'

urlpatterns = [
    path('', views.AccountListView.as_view(), name='account_list'),
    path('create/', views.AccountCreateView.as_view(), name='account_create'),
    path('api/credential-fields/<str:provider>/', views.CredentialFieldsView.as_view(), name='credential_fields'),
    path('api/token/', token_view, name='token_broker'),
    path(
        'webhooks/gameboost/<slug:account_slug>/',
        gameboost_purchase_webhook,
        name='gameboost_purchase_webhook',
    ),
    path('<slug:slug>/', views.AccountDetailView.as_view(), name='account_detail'),
    path('<slug:slug>/edit/', views.AccountUpdateView.as_view(), name='account_edit'),
    path('<slug:slug>/delete/', views.AccountDeleteView.as_view(), name='account_delete'),
    path('<slug:slug>/test/', views.TestConnectionView.as_view(), name='test_connection'),
]
