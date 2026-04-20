from django.urls import path

from . import views, api

app_name = 'dashboard'

urlpatterns = [
    path('', views.index, name='index'),
    path('finance/', views.finance, name='finance'),
    path('finance/api/overview/', api.finance_overview, name='finance_overview_api'),
]
